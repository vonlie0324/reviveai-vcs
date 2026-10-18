from html import escape
from statistics import median

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.core.config import Settings, get_settings
from app.core.firebase_auth import require_tenant_context
from app.models.youtube_publishing import (
    YouTubeConnection,
    YouTubePerformanceSnapshot,
    YouTubePublication,
    YouTubePublicationDetail,
    YouTubePublishRequest,
)
from app.services.youtube_publishing_service import YouTubePublishingError, YouTubePublishingService
from app.services.youtube_performance_service import performance_signal
from app.services.autonomous_activity_service import autonomous_activity_store

router = APIRouter(prefix="/api/v1/youtube", tags=["youtube-publishing"])


def _primary_performance(service: YouTubePublishingService, publications: list[YouTubePublication], checkpoint: str) -> dict[str, dict]:
    checkpoint = str(checkpoint or "24H").upper()
    signals: dict[str, dict] = {}
    for publication in publications:
        snapshots = service.snapshots(publication.publication_id)
        exact = [item for item in snapshots if str(item.checkpoint).upper() == checkpoint]
        snapshot = exact[-1] if exact else None
        signal = performance_signal(snapshot)
        if signal is not None:
            signals[publication.publication_id] = signal

    def values(key: str) -> list[float]:
        return [float(item[key]) for item in signals.values() if item.get(key) is not None]

    baselines = {
        "views": median(values("views")) if values("views") else None,
        "retention_percent": median(values("retention_percent")) if values("retention_percent") else None,
        "engagement_percent": median(values("engagement_percent")) if values("engagement_percent") else None,
        "net_subscribers_per_1k_views": median(values("net_subscribers_per_1k_views")) if values("net_subscribers_per_1k_views") else None,
    }
    weights = {
        "views": 0.30,
        "retention_percent": 0.30,
        "engagement_percent": 0.20,
        "net_subscribers_per_1k_views": 0.20,
    }

    out: dict[str, dict] = {}
    comparable_count = len(signals)
    for publication_id, signal in signals.items():
        weighted = 0.0
        weight_total = 0.0
        deltas: dict[str, float | None] = {}
        for key, weight in weights.items():
            value = signal.get(key)
            baseline = baselines.get(key)
            if value is None or baseline is None or baseline <= 0:
                deltas[key] = None
                continue
            ratio = float(value) / float(baseline)
            deltas[key] = round((ratio - 1.0) * 100.0, 1)
            weighted += (max(0.0, min(2.0, ratio)) / 2.0) * weight
            weight_total += weight
        score = round((weighted / weight_total) * 100.0, 1) if comparable_count >= 2 and weight_total > 0 else None
        out[publication_id] = {
            **signal,
            "primary_checkpoint": checkpoint,
            "performance_score": score,
            "score_version": "v1_equal_age",
            "comparable_release_count": comparable_count,
            "baseline": {key: (round(value, 3) if value is not None else None) for key, value in baselines.items()},
            "delta_percent": deltas,
        }
    return out


def svc(settings: Settings) -> YouTubePublishingService:
    return YouTubePublishingService(settings)


@router.get("/publisher/connection", response_model=YouTubeConnection, dependencies=[Depends(require_tenant_context)])
async def connection(settings: Settings = Depends(get_settings)):
    return svc(settings).connection()


@router.post("/publisher/connect", dependencies=[Depends(require_tenant_context)])
async def connect(settings: Settings = Depends(get_settings)):
    try:
        return {"authorization_url": svc(settings).authorization_url()}
    except YouTubePublishingError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/publisher/oauth/callback", response_class=HTMLResponse)
async def callback(
    code: str = Query(...),
    state: str = Query(...),
    settings: Settings = Depends(get_settings),
):
    """Google callback deliberately does not require a ReviveAI session cookie.

    The authenticated /publisher/connect request created a one-time encrypted state
    that binds this callback to the initiating tenant. This avoids popup/cross-site
    cookie failures while preserving tenant isolation.
    """
    try:
        connected = await svc(settings).exchange_code(code, state)
        title = escape(connected.channel_title or "YouTube")
        return HTMLResponse(
            f"""<!doctype html><html><head><meta charset='utf-8'><title>YouTube connected</title></head>
<body style='font-family:system-ui;background:#0b1020;color:#fff;padding:32px'>
<h2>ReviveAI connected to {title}.</h2><p>You can close this window and return to ReviveAI.</p>
<script>
try {{ if (window.opener) window.opener.postMessage({{type:'reviveai-youtube-connected'}}, '*'); }} catch (e) {{}}
setTimeout(() => window.close(), 500);
</script></body></html>"""
        )
    except YouTubePublishingError as exc:
        message = escape(str(exc))
        return HTMLResponse(
            f"""<!doctype html><html><head><meta charset='utf-8'><title>YouTube connection failed</title></head>
<body style='font-family:system-ui;background:#0b1020;color:#fff;padding:32px'>
<h2>YouTube connection failed</h2><p>{message}</p><p>Close this window and try Connect YouTube again.</p>
<script>try {{ if (window.opener) window.opener.postMessage({{type:'reviveai-youtube-error',message:{message!r}}}, '*'); }} catch (e) {{}}</script>
</body></html>""",
            status_code=409,
        )


@router.delete("/publisher/connection", response_model=YouTubeConnection, dependencies=[Depends(require_tenant_context)])
async def disconnect(settings: Settings = Depends(get_settings)):
    return svc(settings).disconnect()


@router.get("/publications", response_model=list[YouTubePublication], dependencies=[Depends(require_tenant_context)])
async def publications(settings: Settings = Depends(get_settings)):
    return svc(settings).list()


@router.get("/autonomy/status", dependencies=[Depends(require_tenant_context)])
async def autonomy_status(settings: Settings = Depends(get_settings)):
    service = svc(settings)
    publications = service.list()
    scheduled = [p for p in publications if p.status.value == "SCHEDULED" and p.publish_at is not None]
    next_scheduled = min((p.publish_at for p in scheduled if p.publish_at is not None), default=None)
    return {
        "autonomous_publish_enabled": settings.autopilot_autonomous_publish_enabled,
        "autonomous_final_approval_enabled": settings.autopilot_autonomous_final_approval_enabled,
        "continuous_campaign_enabled": settings.autopilot_continuous_campaign_enabled,
        "continuous_learning_checkpoint": settings.autopilot_continuous_learning_checkpoint,
        "next_production_checkpoint": settings.autopilot_next_production_checkpoint,
        "primary_performance_checkpoint": settings.autopilot_primary_performance_checkpoint,
        "next_production_max_wait_hours": settings.autopilot_next_production_max_wait_hours,
        "continuous_learning_max_wait_hours": settings.autopilot_continuous_learning_max_wait_hours,
        "publication_idempotency_enabled": True,
        "event_driven_enabled": settings.autopilot_event_driven_enabled,
        "execution_mode": "cloud_tasks" if settings.autopilot_event_driven_enabled else "in_process",
        "youtube_connected": service.connection().connected,
        "publish_timezone": settings.autopilot_publish_timezone,
        "daily_publishing_enabled": settings.autopilot_daily_publishing_enabled,
        "daily_publish_hour_local": settings.autopilot_daily_publish_hour_local,
        "publish_min_spacing_hours": settings.autopilot_publish_min_spacing_hours,
        "candidate_hours_local": settings.autopilot_publish_candidate_hours_local,
        "next_scheduled_public_at": next_scheduled,
        "scheduled_count": len(scheduled),
        "publication_count": len(publications),
    }


@router.get("/autonomy/snapshot", dependencies=[Depends(require_tenant_context)])
async def autonomy_snapshot(activity_limit: int = Query(default=120, ge=1, le=500), settings: Settings = Depends(get_settings)):
    service = svc(settings)
    publications = service.list()
    scheduled = [p for p in publications if p.status.value == "SCHEDULED" and p.publish_at is not None]
    next_scheduled = min((p.publish_at for p in scheduled if p.publish_at is not None), default=None)
    connection_state = service.connection()
    primary_performance = _primary_performance(
        service, publications, settings.autopilot_primary_performance_checkpoint
    )
    publication_summaries = []
    for publication in publications:
        payload = publication.model_dump(mode="json")
        latest = service.latest_snapshot(publication.publication_id)
        payload["learning_synced"] = bool(latest and latest.learning_synced)
        payload["primary_performance"] = primary_performance.get(publication.publication_id)
        publication_summaries.append(payload)
    return {
        "autonomy": {
            "autonomous_publish_enabled": settings.autopilot_autonomous_publish_enabled,
            "autonomous_final_approval_enabled": settings.autopilot_autonomous_final_approval_enabled,
            "continuous_campaign_enabled": settings.autopilot_continuous_campaign_enabled,
            "continuous_learning_checkpoint": settings.autopilot_continuous_learning_checkpoint,
            "next_production_checkpoint": settings.autopilot_next_production_checkpoint,
            "primary_performance_checkpoint": settings.autopilot_primary_performance_checkpoint,
            "next_production_max_wait_hours": settings.autopilot_next_production_max_wait_hours,
            "continuous_learning_max_wait_hours": settings.autopilot_continuous_learning_max_wait_hours,
            "publication_idempotency_enabled": True,
            "event_driven_enabled": settings.autopilot_event_driven_enabled,
            "execution_mode": "cloud_tasks" if settings.autopilot_event_driven_enabled else "in_process",
            "youtube_connected": connection_state.connected,
            "publish_timezone": settings.autopilot_publish_timezone,
            "daily_publishing_enabled": settings.autopilot_daily_publishing_enabled,
            "daily_publish_hour_local": settings.autopilot_daily_publish_hour_local,
            "publish_min_spacing_hours": settings.autopilot_publish_min_spacing_hours,
            "candidate_hours_local": settings.autopilot_publish_candidate_hours_local,
            "next_scheduled_public_at": next_scheduled,
            "scheduled_count": len(scheduled),
            "publication_count": len(publications),
        },
        "connection": connection_state,
        "activity": autonomous_activity_store.list(limit=activity_limit),
        "publications": publication_summaries,
    }


@router.post("/publications", response_model=YouTubePublication, dependencies=[Depends(require_tenant_context)])
async def publish(req: YouTubePublishRequest, settings: Settings = Depends(get_settings)):
    try:
        return await svc(settings).publish(req)
    except (YouTubePublishingError, KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/publications/{publication_id}/retry", response_model=YouTubePublication, dependencies=[Depends(require_tenant_context)])
async def retry_publication(publication_id: str, settings: Settings = Depends(get_settings)):
    try:
        return await svc(settings).retry(publication_id)
    except (YouTubePublishingError, KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/publications/{publication_id}", response_model=YouTubePublicationDetail, dependencies=[Depends(require_tenant_context)])
async def publication(publication_id: str, settings: Settings = Depends(get_settings)):
    try:
        service = svc(settings)
        return YouTubePublicationDetail(publication=service.get(publication_id), snapshots=service.snapshots(publication_id))
    except YouTubePublishingError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/publications/{publication_id}/confirm-public", response_model=YouTubePublication, dependencies=[Depends(require_tenant_context)])
async def confirm_public(publication_id: str, settings: Settings = Depends(get_settings)):
    try:
        return await svc(settings).confirm_public(publication_id)
    except YouTubePublishingError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/publications/{publication_id}/analytics", response_model=YouTubePerformanceSnapshot, dependencies=[Depends(require_tenant_context)])
async def analytics(publication_id: str, settings: Settings = Depends(get_settings)):
    try:
        return await svc(settings).refresh_analytics(publication_id)
    except YouTubePublishingError as exc:
        raise HTTPException(409, str(exc)) from exc

@router.post('/publications/{publication_id}/replacement/stage', dependencies=[Depends(require_tenant_context)])
async def stage_scheduled_replacement(
    publication_id: str,
    request: __import__('fastapi').Request,
    sha256: str = Query(..., min_length=64, max_length=64, pattern=r'^[0-9a-fA-F]{64}$'),
    settings: Settings = Depends(get_settings),
):
    """Upload a corrected MP4 as a separate PRIVATE video; never change the old schedule."""
    from app.services.youtube_replacement_service import YouTubeReplacementService, MAX_BYTES
    length = request.headers.get('content-length')
    if request.headers.get('content-type', '').split(';')[0].strip() != 'video/mp4':
        raise HTTPException(415, 'Send raw MP4 bytes with Content-Type: video/mp4.')
    if length and int(length) > MAX_BYTES:
        raise HTTPException(413, 'Replacement exceeds 64 MiB.')
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > MAX_BYTES:
            raise HTTPException(413, 'Replacement exceeds 64 MiB.')
    try:
        return await YouTubeReplacementService(svc(settings)).stage(publication_id, bytes(content), expected_sha256=sha256)
    except (YouTubePublishingError, ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/publications/{publication_id}/replacement/status', dependencies=[Depends(require_tenant_context)])
async def scheduled_replacement_status(
    publication_id: str,
    sha256: str = Query(..., min_length=64, max_length=64, pattern=r'^[0-9a-fA-F]{64}$'),
    settings: Settings = Depends(get_settings),
):
    from app.services.youtube_replacement_service import YouTubeReplacementService
    result = YouTubeReplacementService(svc(settings)).status(publication_id, sha256)
    if not result:
        raise HTTPException(404, 'Replacement job not found.')
    return result


@router.post('/publications/{publication_id}/replacement/activate', dependencies=[Depends(require_tenant_context)])
async def activate_scheduled_replacement(
    publication_id: str,
    sha256: str = Query(..., min_length=64, max_length=64, pattern=r'^[0-9a-fA-F]{64}$'),
    confirm: bool = Query(False),
    settings: Settings = Depends(get_settings),
):
    """Explicit confirmation: retire old schedule, schedule verified new upload, switch Autopilot."""
    from app.services.youtube_replacement_service import YouTubeReplacementService
    try:
        return await YouTubeReplacementService(svc(settings)).commit(publication_id, sha256, confirm=confirm)
    except (YouTubePublishingError, ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc
