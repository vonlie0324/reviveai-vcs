from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.audio_finishing import AudioFinishingJob, AudioFinishingJobStage, AudioFinishingReviewStatus
from app.models.delivery_qc import DeliveryQcOverallStatus, DeliveryQcReport
from app.models.final_assembly import FinalAssemblyJob, FinalAssemblyJobStage
from app.models.media_studio import (
    ClipOperationStatus,
    KeyframeFidelityStatus,
    MediaAssetReviewStatus,
    MediaStudioJob,
    MediaStudioJobStage,
    ShotOperationStatus,
)
from app.models.publishing_assistant import PublishingDraft, PublishingDraftStatus
from app.models.production_brief import ProductionBriefJob, ProductionBriefJobStage
from app.services.ai_review_service import (
    AiReviewDecision,
    AiReviewError,
    AiReviewService,
    review_to_detail,
)
from app.services.autopilot_operation_service import autopilot_operation_store
from app.services.autopilot_recovery_service import (
    AutopilotRecoveryError,
    create_controlled_motion_fallback,
    salvage_keyframe_for_autopilot,
)
from app.services.audio_finishing_job_service import (
    AudioFinishingJobNotFoundError,
    audio_finishing_job_store,
    render_audio_finishing,
)
from app.services.delivery_package_service import delivery_package_store
from app.services.delivery_qc_service import DeliveryQcReportNotFoundError, delivery_qc_store
from app.services.final_assembly_job_service import (
    FinalAssemblyJobNotFoundError,
    final_assembly_job_store,
    render_final_assembly,
)
from app.services.media_studio_job_service import (
    MediaStudioJobNotFoundError,
    generate_keyframes_for_job,
    generate_reference_for_job,
    media_studio_job_store,
    regenerate_video_clip_for_job,
)
from app.services.production_brief_job_service import ProductionBriefJobNotFoundError, production_brief_job_store
from app.services.publishing_assistant_service import (
    PublishingAssistantError,
    PublishingDraftNotFoundError,
    publishing_assistant_service,
    publishing_draft_store,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["ai-review"], dependencies=[Depends(require_tenant_context)])


@router.post("/production-brief-jobs/{job_id}/ai-review", response_model=ProductionBriefJob)
async def ai_review_production_brief(
    job_id: str,
    settings: Settings = Depends(get_settings),
):
    try:
        job = production_brief_job_store.get(job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")
    if job.stage != ProductionBriefJobStage.COMPLETED or not job.result:
        raise HTTPException(status_code=409, detail="The production brief is not ready for AI review.")
    if job.result.consistency_report.status != "PASS" or job.result.direction_fidelity.status == "REVIEW_REQUIRED":
        raise HTTPException(status_code=409, detail="Deterministic consistency and direction fidelity must pass before AI plan review.")

    try:
        review = await AiReviewService(settings).review_production_brief(job_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    production_brief_job_store.update_stage(
        job_id,
        job.stage,
        "Production plan passed AI critic" if review.decision == AiReviewDecision.PASS else "AI critic requested a fresh production-plan pass",
        job.progress_current,
        job.progress_total,
        {
            "ai_plan_review": review_to_detail(review),
            "ai_plan_review_for_generated_at": job.result.model_dump(mode="json")["generated_at"],
            "approval_actor": "AI" if review.decision == AiReviewDecision.PASS else None,
        },
    )
    if review.decision == AiReviewDecision.PASS or not settings.autopilot_allow_regeneration:
        effective_review = review_to_detail(review)
        if review.decision != AiReviewDecision.PASS:
            effective_review = _salvaged_review_detail(
                effective_review,
                recovery_mode="ACCEPT_CURRENT_NO_REGENERATION",
                summary=f"AI_SALVAGED: automatic regeneration is disabled; keeping the current production plan. Reviewer note: {review.summary}",
            )
        production_brief_job_store.approve(job_id)
        approved = production_brief_job_store.get(job_id)
        production_brief_job_store.update_stage(
            job_id,
            approved.stage,
            "Production plan AI-reviewed and ready for visual generation",
            approved.progress_current,
            approved.progress_total,
            {
                "approval_actor": "AI",
                "ai_plan_review": effective_review,
                "ai_plan_review_for_generated_at": approved.result.model_dump(mode="json")["generated_at"] if approved.result else None,
                "automatic_regeneration_disabled": not settings.autopilot_allow_regeneration,
            },
        )
    return production_brief_job_store.get(job_id)

MAX_REFERENCE_ATTEMPTS = 3
MAX_CLIP_ATTEMPTS = 3
MAX_ASSEMBLY_REVIEW_ATTEMPTS = 2
MAX_AUDIO_REVIEW_ATTEMPTS = 3
MAX_PUBLISHING_REVIEW_ATTEMPTS = 4


def _record(job, key: str, payload: dict) -> None:
    job.detail = {**job.detail, key: payload}


def _review_pass(value) -> bool:
    return isinstance(value, dict) and str(value.get("decision") or "").upper() == AiReviewDecision.PASS.value


def _salvaged_review_detail(value, *, recovery_mode: str, summary: str) -> dict:
    payload = dict(value or {}) if isinstance(value, dict) else {}
    original_decision = str(payload.get("decision") or "REGENERATE")
    payload.update({
        "decision": AiReviewDecision.PASS.value,
        "original_decision": original_decision,
        "outcome": "AI_SALVAGED",
        "recovery_mode": recovery_mode,
        "summary": summary,
        "salvaged_at": datetime.now(timezone.utc).isoformat(),
    })
    return payload


def _require_complete_ai_review_chain(*, audio_job, assembly_job, media_job, production_job) -> None:
    if not production_job.result:
        raise HTTPException(status_code=409, detail="The AI-reviewed production plan could not be verified.")
    plan_detail = production_job.detail or {}
    plan_generated_at = production_job.result.model_dump(mode="json").get("generated_at")
    if (
        production_job.result.review_status.value != "APPROVED"
        or str(plan_detail.get("approval_actor") or "").upper() != "AI"
        or str(plan_detail.get("ai_plan_review_for_generated_at") or "") != str(plan_generated_at or "")
        or not _review_pass(plan_detail.get("ai_plan_review"))
    ):
        raise HTTPException(status_code=409, detail="Production plan + text fidelity must pass the current AI review before final approval.")

    if not media_job.result or not media_job.result.reference_asset:
        raise HTTPException(status_code=409, detail="AI-reviewed media assets could not be verified.")
    media_detail = media_job.detail or {}
    reference_review = media_detail.get("reference_ai_review") or media_detail.get("ai_reference_review")
    if (
        not media_job.result.reference_approved
        or str(media_detail.get("reference_approval_actor") or "").upper() != "AI"
        or not _review_pass(reference_review)
    ):
        raise HTTPException(status_code=409, detail="Visual identity must pass AI review before final approval.")

    keyframe_actors = dict(media_detail.get("keyframe_approval_actor") or {})
    salvaged_keyframes = dict(media_detail.get("ai_salvaged_keyframes") or {})
    if media_job.result.required_keyframes <= 0 or len(media_job.result.keyframes) < media_job.result.required_keyframes:
        raise HTTPException(status_code=409, detail="All required storyboard keyframes must exist before final approval.")
    for asset in media_job.result.keyframes:
        report = asset.fidelity_report
        salvage = salvaged_keyframes.get(str(asset.shot_number))
        salvage_ok = (
            isinstance(salvage, dict)
            and str(salvage.get("outcome") or "").upper() == "AI_SALVAGED"
            and report is not None
            and report.status == KeyframeFidelityStatus.ADAPTATION_ACCEPTED
            and report.creator_override is False
        )
        if (
            asset.review_status.value != "APPROVED"
            or report is None
            or (report.status != KeyframeFidelityStatus.PASS and not salvage_ok)
            or str(keyframe_actors.get(str(asset.shot_number)) or "").upper() != "AI"
        ):
            raise HTTPException(status_code=409, detail=f"Storyboard keyframe {asset.shot_number} has not passed or been AI-salvaged through the required fidelity gate.")

    clip_actors = dict(media_detail.get("clip_approval_actor") or {})
    clip_reviews = dict(media_detail.get("ai_clip_reviews") or {})
    if media_job.result.required_clips <= 0 or len(media_job.result.video_clips) < media_job.result.required_clips:
        raise HTTPException(status_code=409, detail="All required animated shots must exist before final approval.")
    for clip in media_job.result.video_clips:
        if (
            clip.review_status.value != "APPROVED"
            or str(clip_actors.get(str(clip.shot_number)) or "").upper() != "AI"
            or not _review_pass(clip_reviews.get(str(clip.shot_number)))
            or str(dict(clip_reviews.get(str(clip.shot_number)) or {}).get("outcome") or "").upper() == "AI_SALVAGED"
        ):
            raise HTTPException(status_code=409, detail=f"Animated shot {clip.shot_number} has not passed the required AI motion review.")

    current_clips = {clip.shot_number: clip.asset_id for clip in media_job.result.video_clips}
    if not assembly_job.result or len(assembly_job.result.timeline) != media_job.result.required_clips:
        raise HTTPException(status_code=409, detail="The final visual master does not match the current AI-reviewed shot set.")
    if any(current_clips.get(item.shot_number) != item.source_clip_asset_id for item in assembly_job.result.timeline):
        raise HTTPException(status_code=409, detail="The final visual master was rendered from stale clips and must be rebuilt before final approval.")
    if (
        str(assembly_job.detail.get("approval_actor") or "").upper() != "AI"
        or not _review_pass(assembly_job.detail.get("ai_visual_master_review"))
    ):
        raise HTTPException(status_code=409, detail="The visual master must pass AI review before final approval.")

    if (
        audio_job.assembly_job_id != assembly_job.job_id
        or str(audio_job.detail.get("approval_actor") or "").upper() != "AI"
        or not _review_pass(audio_job.detail.get("ai_audio_review"))
    ):
        raise HTTPException(status_code=409, detail="The current audio master must pass AI review against the current visual master before final approval.")


@router.post("/media-jobs/{job_id}/ai-review/reference", response_model=MediaStudioJob)
async def ai_review_reference(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if not job.result or not job.result.reference_asset:
        raise HTTPException(status_code=409, detail="The character reference is not ready for AI review.")
    if job.stage in {MediaStudioJobStage.QUEUED, MediaStudioJobStage.GENERATING_REFERENCE}:
        raise HTTPException(status_code=409, detail="The character reference is still being generated.")
    reference_review = job.detail.get("reference_ai_review") or job.detail.get("ai_reference_review")
    if job.detail.get("reference_approval_actor") == "AI" and _review_pass(reference_review):
        return job
    original_stage = job.stage

    try:
        review = await AiReviewService(settings).review_reference(job_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    job = media_studio_job_store.get(job_id)
    _record(job, "ai_reference_review", review_to_detail(review))
    _record(job, "approval_actor", "AI")
    media_studio_job_store.save(job)

    if review.decision == AiReviewDecision.PASS:
        if original_stage == MediaStudioJobStage.AWAITING_REFERENCE_APPROVAL:
            approved = media_studio_job_store.approve_reference(
                job_id,
                f"AI reviewer PASS: {review.summary}",
            )
            approved = media_studio_job_store.get(job_id)
            approved.detail = {
                **approved.detail,
                "reference_approval_actor": "AI",
                "reference_ai_review": review_to_detail(review),
            }
            media_studio_job_store.save(approved)
            background_tasks.add_task(tenant_bound(generate_keyframes_for_job), job_id, settings)
            return media_studio_job_store.get(job_id)

        # Adopt an existing downstream production without rebuilding assets when the
        # historical reference itself passes the independent AI identity critic.
        adopted = media_studio_job_store.get(job_id)
        assert adopted.result and adopted.result.reference_asset
        adopted.result.reference_approved = True
        adopted.result.reference_asset.review_note = f"AI reviewer PASS: {review.summary}"
        adopted.detail = {
            **adopted.detail,
            "reference_approval_actor": "AI",
            "reference_ai_review": review_to_detail(review),
        }
        adopted.message = "Existing character reference re-reviewed by AI"
        media_studio_job_store.save(adopted)
        return media_studio_job_store.get(job_id)

    if not settings.autopilot_allow_regeneration:
        salvage = _salvaged_review_detail(
            review_to_detail(review),
            recovery_mode="ACCEPT_CURRENT_NO_REGENERATION",
            summary=f"AI_SALVAGED: automatic regeneration is disabled; keeping the current character reference. Reviewer note: {review.summary}",
        )
        if original_stage == MediaStudioJobStage.AWAITING_REFERENCE_APPROVAL:
            approved = media_studio_job_store.approve_reference(
                job_id,
                salvage["summary"],
            )
            approved = media_studio_job_store.get(job_id)
            approved.detail = {
                **approved.detail,
                "reference_approval_actor": "AI",
                "reference_ai_review": salvage,
                "ai_reference_review": salvage,
                "automatic_regeneration_disabled": True,
            }
            media_studio_job_store.save(approved)
            background_tasks.add_task(tenant_bound(generate_keyframes_for_job), job_id, settings)
            return media_studio_job_store.get(job_id)

        adopted = media_studio_job_store.get(job_id)
        assert adopted.result and adopted.result.reference_asset
        adopted.result.reference_approved = True
        adopted.result.reference_asset.review_note = salvage["summary"]
        adopted.detail = {
            **adopted.detail,
            "reference_approval_actor": "AI",
            "reference_ai_review": salvage,
            "ai_reference_review": salvage,
            "automatic_regeneration_disabled": True,
        }
        adopted.message = "Existing character reference kept; automatic regeneration is disabled"
        media_studio_job_store.save(adopted)
        return media_studio_job_store.get(job_id)

    attempt = job.result.reference_asset.generation_attempt
    if attempt >= MAX_REFERENCE_ATTEMPTS:
        job = media_studio_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "ai_review_exhausted": True,
            "ai_review_exhausted_stage": "REFERENCE",
        }
        job.message = "AI reference review could not reach PASS after automatic regeneration attempts"
        media_studio_job_store.save(job)
        return media_studio_job_store.get(job_id)

    job = media_studio_job_store.get(job_id)
    assert job.result and job.result.reference_asset
    job.result.reference_asset.review_note = review.corrective_instruction or review.summary
    job.result.reference_approved = False
    # A rejected canonical reference invalidates every visual derived from it.
    # Clear downstream assets so Autopilot cannot accidentally reuse clips or an
    # assembly that was produced from the rejected identity anchor.
    job.result.keyframes = []
    job.result.shot_operations = {}
    job.result.video_clips = []
    job.result.clip_operations = {}
    job.result.approved_keyframes = 0
    job.result.fidelity_reviewed_keyframes = 0
    job.result.fidelity_passed_keyframes = 0
    job.result.approved_clips = 0
    job.result.assembly_ready = False
    job.result.animation_ready = False
    job.detail = {
        **job.detail,
        "reference_approval_actor": None,
        "keyframe_approval_actor": {},
        "clip_approval_actor": {},
    }
    job.stage = MediaStudioJobStage.GENERATING_REFERENCE
    job.message = f"AI reviewer requested reference regeneration (attempt {attempt + 1}/{MAX_REFERENCE_ATTEMPTS})"
    media_studio_job_store.save(job)
    background_tasks.add_task(tenant_bound(generate_reference_for_job), job_id, settings)
    return media_studio_job_store.get(job_id)


AUTOPILOT_STALE_OPERATION_SECONDS = 15 * 60
AI_REVIEW_HARD_TIMEOUT_SECONDS = 6 * 60
AI_REVIEW_HEARTBEAT_SECONDS = 20
AI_REVIEW_LEASE_STALE_SECONDS = 90
# A heartbeat proves the worker process is alive; it does not prove the model call is
# making useful progress.  Autopilot therefore has a separate wall-clock deadline.
# At this age the watchdog reclaims the reviewer even when heartbeats are still arriving.
AI_REVIEW_FORCE_RECLAIM_SECONDS = 8 * 60
# If an inherited/stale operation is already far beyond two watchdog windows, do not
# make the creator wait for another retry cycle: use the deterministic salvage path.
AI_REVIEW_EXTREME_STALE_SECONDS = AI_REVIEW_FORCE_RECLAIM_SECONDS * 2
MAX_CLIP_REVIEW_TIMEOUTS = 2


def _clip_review_key(shot_number: int) -> str:
    return f"clip_review:{shot_number}"


def _clip_review_operations(job: MediaStudioJob) -> dict[str, dict]:
    raw = job.detail.get("ai_clip_review_operations") if job.detail else None
    return dict(raw or {}) if isinstance(raw, dict) else {}


def _set_clip_review_operation(job: MediaStudioJob, shot_number: int, payload: dict) -> None:
    operations = _clip_review_operations(job)
    operations[str(shot_number)] = payload
    job.detail = {**dict(job.detail or {}), "ai_clip_review_operations": operations}


def _clip_review_timeout_count(job: MediaStudioJob, shot_number: int) -> int:
    raw = dict((job.detail or {}).get("ai_clip_review_timeouts") or {})
    try:
        return int(raw.get(str(shot_number)) or 0)
    except (TypeError, ValueError):
        return 0


def _set_clip_review_timeout_count(job: MediaStudioJob, shot_number: int, count: int) -> None:
    raw = dict((job.detail or {}).get("ai_clip_review_timeouts") or {})
    raw[str(shot_number)] = int(count)
    job.detail = {**dict(job.detail or {}), "ai_clip_review_timeouts": raw}


def _clip_ai_review_complete(job: MediaStudioJob, shot_number: int) -> bool:
    if not job.result:
        return False
    clip = next((item for item in job.result.video_clips if item.shot_number == shot_number), None)
    if clip is None or clip.review_status != MediaAssetReviewStatus.APPROVED:
        return False
    detail = dict(job.detail or {})
    actor = dict(detail.get("clip_approval_actor") or {}).get(str(shot_number))
    review = dict(detail.get("ai_clip_reviews") or {}).get(str(shot_number))
    return (str(actor or "").upper() == "AI" and _review_pass(review)
            and str(dict(review or {}).get("outcome") or "").upper() != "AI_SALVAGED")


async def _lease_heartbeat(job_id: str, operation_key: str, lease_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(AI_REVIEW_HEARTBEAT_SECONDS)
            if not autopilot_operation_store.heartbeat(job_id, operation_key, lease_id):
                return
    except asyncio.CancelledError:
        return


def _lease_is_current(job_id: str, operation_key: str, lease_id: str) -> bool:
    """Fence reviewer writes to the currently-owned lease.

    Provider calls cannot always be force-cancelled immediately.  A reclaimed reviewer may
    therefore return after the watchdog has already restarted/salvaged the shot.  Without
    this check that obsolete response could overwrite the recovered state.
    """
    lease = autopilot_operation_store.get(job_id, operation_key)
    return bool(
        lease
        and str(lease.get("lease_id") or "") == lease_id
        and str(lease.get("status") or "").upper() == "RUNNING"
    )


def _schedule_clip_review(
    *,
    job_id: str,
    shot_number: int,
    settings: Settings,
    background_tasks: BackgroundTasks,
    reason: str = "AI motion review started",
) -> MediaStudioJob:
    job = media_studio_job_store.get(job_id)
    if not job.result:
        raise ValueError("Media Studio result is unavailable.")
    clip = next((item for item in job.result.video_clips if item.shot_number == shot_number), None)
    if clip is None:
        raise ValueError(f"Animated shot {shot_number} not found.")
    if _clip_ai_review_complete(job, shot_number):
        return job

    operation_key = _clip_review_key(shot_number)
    current_lease = autopilot_operation_store.get(job_id, operation_key)
    if current_lease and current_lease.get("status") == "RUNNING" and not autopilot_operation_store.is_stale(
        current_lease, heartbeat_grace_seconds=AI_REVIEW_LEASE_STALE_SECONDS
    ):
        return job

    lease = autopilot_operation_store.begin(
        job_id,
        operation_key,
        timeout_seconds=AI_REVIEW_HARD_TIMEOUT_SECONDS,
        metadata={"shot_number": shot_number, "kind": "motion_fidelity_review"},
    )
    now = datetime.now(timezone.utc).isoformat()
    _set_clip_review_operation(job, shot_number, {
        "lease_id": lease["lease_id"],
        "status": "RUNNING",
        "attempt": lease["attempt"],
        "started_at": now,
        "updated_at": now,
        "finished_at": None,
        "reason": reason,
    })
    job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
    job.message = f"AI motion reviewer is validating animated shot {shot_number}"
    job.error = None
    media_studio_job_store.save(job)
    background_tasks.add_task(
        tenant_bound(run_ai_clip_review_background),
        job_id,
        shot_number,
        settings,
        str(lease["lease_id"]),
    )
    return media_studio_job_store.get(job_id)




def _parse_operation_started(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed

def _seconds_since(value: datetime | None) -> float:
    if value is None:
        return float("inf")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - value).total_seconds())


@router.post("/media-jobs/{job_id}/autopilot-reconcile", response_model=MediaStudioJob)
async def autopilot_reconcile_media_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Repair durable Media Studio checkpoints after a browser/provider stall.

    The endpoint is deliberately conservative: it only commits decisions that are already
    proven by persisted AI review output. AI reviewer leases have an eight-minute
    wall-clock recovery deadline even when heartbeats are still arriving; expensive media
    generation keeps its separate, more generous stale-operation window. Nothing is
    silently treated as passed.
    """
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if not job.result:
        raise HTTPException(status_code=409, detail="Media Studio result is unavailable.")

    result = job.result
    actions: list[str] = []
    detail = dict(job.detail or {})

    # A previous request may have completed Gemini fidelity review but failed before the
    # frontend received the AI-approval response. Re-commit those PASS decisions
    # idempotently so Autopilot can advance immediately.
    keyframe_actors = dict(detail.get("keyframe_approval_actor") or {})
    for asset in list(result.keyframes):
        shot_number = asset.shot_number
        if not shot_number or not asset.fidelity_report:
            continue
        if asset.fidelity_report.status != KeyframeFidelityStatus.PASS:
            continue
        if str(keyframe_actors.get(str(shot_number)) or "").upper() == "AI" and asset.review_status == MediaAssetReviewStatus.APPROVED:
            continue
        try:
            if asset.review_status != MediaAssetReviewStatus.APPROVED:
                media_studio_job_store.approve_keyframe(
                    job_id,
                    shot_number,
                    "Autopilot watchdog restored AI approval after persisted storyboard-fidelity PASS.",
                )
            job = media_studio_job_store.get(job_id)
            detail = dict(job.detail or {})
            keyframe_actors = dict(detail.get("keyframe_approval_actor") or {})
            keyframe_actors[str(shot_number)] = "AI"
            detail["keyframe_approval_actor"] = keyframe_actors
            job.detail = detail
            media_studio_job_store.save(job)
            actions.append(f"restored AI approval for keyframe {shot_number}")
        except ValueError:
            # The normal workflow will surface any genuine gate conflict.
            pass

    job = media_studio_job_store.get(job_id)
    result = job.result
    assert result is not None
    detail = dict(job.detail or {})

    # The same lost-response condition can occur after video review. If the persisted
    # review already says PASS, the watchdog may safely commit the clip approval.
    clip_actors = dict(detail.get("clip_approval_actor") or {})
    clip_reviews = dict(detail.get("ai_clip_reviews") or {})
    for clip in list(result.video_clips):
        review = clip_reviews.get(str(clip.shot_number))
        review_passed = isinstance(review, dict) and str(review.get("decision") or "").upper() == "PASS"
        actor_is_ai = str(clip_actors.get(str(clip.shot_number)) or "").upper() == "AI"
        if not review_passed or (actor_is_ai and clip.review_status == MediaAssetReviewStatus.APPROVED):
            continue
        try:
            if clip.review_status != MediaAssetReviewStatus.APPROVED:
                media_studio_job_store.approve_clip(
                    job_id,
                    clip.shot_number,
                    "Autopilot watchdog restored AI approval after persisted motion-review PASS.",
                )
            job = media_studio_job_store.get(job_id)
            detail = dict(job.detail or {})
            clip_actors = dict(detail.get("clip_approval_actor") or {})
            clip_actors[str(clip.shot_number)] = "AI"
            detail["clip_approval_actor"] = clip_actors
            job.detail = detail
            media_studio_job_store.save(job)
            actions.append(f"restored AI approval for animated shot {clip.shot_number}")
        except ValueError:
            pass

    job = media_studio_job_store.get(job_id)
    result = job.result
    assert result is not None

    # Reviewer leases live outside MediaStudioJob so their heartbeats cannot fake a
    # production checkpoint. If the process died or the reviewer stopped heartbeating,
    # restart that exact review idempotently. After repeated reviewer timeouts/failures,
    # use the controlled-motion fallback rather than leaving the production blocked.
    review_operations = _clip_review_operations(job)
    for raw_shot, operation in list(review_operations.items()):
        try:
            shot_number = int(raw_shot)
        except (TypeError, ValueError):
            continue
        status = str(dict(operation or {}).get("status") or "").upper()
        if status not in {"RUNNING", "TIMED_OUT", "FAILED", "STALE"}:
            continue
        if _clip_ai_review_complete(job, shot_number):
            continue

        operation_started = _parse_operation_started(dict(operation or {}).get("started_at"))
        operation_age = _seconds_since(operation_started)
        lease = autopilot_operation_store.get(job_id, _clip_review_key(shot_number))
        lease_stale = status == "RUNNING" and (
            lease is None
            or autopilot_operation_store.is_stale(lease, heartbeat_grace_seconds=AI_REVIEW_LEASE_STALE_SECONDS)
            # Hard wall-clock deadline.  A heartbeat cannot keep a reviewer alive forever.
            or operation_age >= AI_REVIEW_FORCE_RECLAIM_SECONDS
        )
        if status == "RUNNING" and not lease_stale:
            continue

        if lease and lease.get("status") == "RUNNING":
            autopilot_operation_store.finish(
                job_id, _clip_review_key(shot_number), str(lease.get("lease_id")),
                status="FAILED", error="Autopilot watchdog reclaimed a reviewer that exceeded the hard deadline.",
            )

        timeout_count = _clip_review_timeout_count(job, shot_number)
        failure_count = int(dict(job.detail.get("ai_clip_review_failures") or {}).get(str(shot_number)) or 0)

        # Reclaiming a RUNNING lease counts as a timeout.  Otherwise a worker that keeps
        # heartbeating while the provider call is hung could be restarted forever without
        # ever reaching the bounded salvage path.
        if status == "RUNNING":
            timeout_count += 1
            if operation_age >= AI_REVIEW_EXTREME_STALE_SECONDS:
                # Existing v2.6/v2.7 sessions can already be tens of minutes old.  Do not
                # make them wait through another full retry cycle after upgrading.
                timeout_count = max(timeout_count, MAX_CLIP_REVIEW_TIMEOUTS)
            _set_clip_review_timeout_count(job, shot_number, timeout_count)
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": None,
                "status": "STALE",
                "attempt": timeout_count,
                "started_at": dict(operation or {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": f"AI reviewer exceeded the {AI_REVIEW_FORCE_RECLAIM_SECONDS // 60}-minute watchdog deadline.",
            })
            media_studio_job_store.save(job)
            job = media_studio_job_store.get(job_id)

        if timeout_count >= MAX_CLIP_REVIEW_TIMEOUTS or failure_count >= MAX_CLIP_REVIEW_TIMEOUTS:
            _mark_autonomous_clip_blocked(job_id, shot_number, "AI motion reviewer timed out repeatedly")
            job = media_studio_job_store.get(job_id)
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": None,
                "status": "BLOCKED",
                "attempt": max(timeout_count, failure_count, 1),
                "started_at": None,
                "updated_at": now,
                "finished_at": now,
                "reason": "Reviewer exceeded bounded budget; shot blocked until a passing motion review is available.",
            })
            job.message = f"Animated shot {shot_number} blocked after stalled AI reviewer"
            media_studio_job_store.save(job)
            actions.append(f"blocked stale motion review for shot {shot_number}")
            continue

        job = _schedule_clip_review(
            job_id=job_id,
            shot_number=shot_number,
            settings=settings,
            background_tasks=background_tasks,
            reason=f"Autopilot watchdog restarted AI motion review after the {AI_REVIEW_FORCE_RECLAIM_SECONDS // 60}-minute hard deadline",
        )
        result = job.result
        assert result is not None
        actions.append(f"restarted stale AI motion review for shot {shot_number}")

    job = media_studio_job_store.get(job_id)
    result = job.result
    assert result is not None

    # Convert abandoned generation leases into explicit failures only after a generous
    # timeout. Existing Autopilot retry/salvage logic will then recover the affected shot
    # without touching successful work.
    for shot_number, operation in list(result.shot_operations.items()):
        if operation.status not in {ShotOperationStatus.REGENERATING, ShotOperationStatus.FIDELITY_REVIEW}:
            continue
        if _seconds_since(operation.updated_at) < AUTOPILOT_STALE_OPERATION_SECONDS:
            continue
        asset = next((item for item in result.keyframes if item.shot_number == shot_number), None)
        if asset and asset.generation_attempt >= operation.target_generation_attempt and asset.fidelity_report is not None:
            operation.status = ShotOperationStatus.READY
            operation.message = f"Watchdog restored completed shot {shot_number} checkpoint"
            operation.error = None
        else:
            operation.status = ShotOperationStatus.FAILED
            operation.message = f"Shot {shot_number} generation lease expired; Autopilot will retry safely"
            operation.error = "Autopilot watchdog detected a stale keyframe operation with no completed checkpoint."
        operation.updated_at = datetime.now(timezone.utc)
        actions.append(f"reconciled stale keyframe operation {shot_number}")

    for shot_number, operation in list(result.clip_operations.items()):
        if operation.status not in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING}:
            continue
        if _seconds_since(operation.updated_at) < AUTOPILOT_STALE_OPERATION_SECONDS:
            continue
        clip = next((item for item in result.video_clips if item.shot_number == shot_number), None)
        if clip and clip.generation_attempt >= operation.target_generation_attempt:
            operation.status = ClipOperationStatus.READY
            operation.message = f"Watchdog restored completed animated shot {shot_number} checkpoint"
            operation.error = None
        else:
            operation.status = ClipOperationStatus.FAILED
            operation.message = f"Animated shot {shot_number} generation lease expired; Autopilot will retry safely"
            operation.error = "Autopilot watchdog detected a stale video operation with no completed checkpoint."
        operation.updated_at = datetime.now(timezone.utc)
        actions.append(f"reconciled stale video operation {shot_number}")

    # Recover stage labels that can be left behind if a browser/backend response is lost.
    active_shot = any(op.status in {ShotOperationStatus.REGENERATING, ShotOperationStatus.FIDELITY_REVIEW} for op in result.shot_operations.values())
    active_clip = any(op.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING} for op in result.clip_operations.values())
    if job.stage == MediaStudioJobStage.REVIEWING_KEYFRAME_FIDELITY and not active_shot:
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Watchdog restored keyframe-review checkpoint; Autopilot is continuing"
        actions.append("restored keyframe review stage")
    elif job.stage == MediaStudioJobStage.GENERATING_CLIPS and not active_clip:
        job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
        job.message = "Watchdog restored clip-review checkpoint; Autopilot is continuing"
        actions.append("restored clip review stage")

    if actions:
        detail = dict(job.detail or {})
        detail["autopilot_watchdog"] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "actions": actions,
            "outcome": "RECOVERED",
        }
        job.detail = detail
        job.error = None
        media_studio_job_store.save(job)
        return media_studio_job_store.get(job_id)

    # A no-op health check must not update job.updated_at; otherwise the frontend would
    # mistake the watchdog itself for real production progress and postpone the next check.
    return job


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/ai-approve", response_model=MediaStudioJob)
async def ai_approve_keyframe(job_id: str, shot_number: int):
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if not job.result:
        raise HTTPException(status_code=409, detail="Media Studio result is unavailable.")
    asset = next((item for item in job.result.keyframes if item.shot_number == shot_number), None)
    if asset is None:
        raise HTTPException(status_code=404, detail=f"Storyboard keyframe {shot_number} not found.")
    if not asset.fidelity_report or asset.fidelity_report.status != KeyframeFidelityStatus.PASS:
        raise HTTPException(status_code=409, detail="A keyframe must have an AI fidelity PASS before Autopilot can approve it.")
    try:
        approved = media_studio_job_store.approve_keyframe(
            job_id,
            shot_number,
            "AI reviewer approval after storyboard-fidelity PASS.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    approved.detail = {
        **approved.detail,
        "keyframe_approval_actor": {
            **dict(approved.detail.get("keyframe_approval_actor") or {}),
            str(shot_number): "AI",
        },
    }
    media_studio_job_store.save(approved)
    return media_studio_job_store.get(job_id)


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/ai-salvage", response_model=MediaStudioJob)
async def ai_salvage_keyframe(job_id: str, shot_number: int):
    try:
        return salvage_keyframe_for_autopilot(job_id, shot_number)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except AutopilotRecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/media-jobs/{job_id}/clips/{shot_number}/ai-controlled-motion-fallback", response_model=MediaStudioJob)
async def ai_controlled_motion_fallback(
    job_id: str,
    shot_number: int,
    settings: Settings = Depends(get_settings),
):
    try:
        return create_controlled_motion_fallback(job_id, shot_number, settings)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except AutopilotRecoveryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _mark_autonomous_clip_blocked(job_id: str, shot_number: int, reason: str) -> None:
    """Fail closed: AI review failure cannot turn into approved motion."""
    job = media_studio_job_store.get(job_id)
    detail = dict(job.detail or {})
    exhausted = set(int(x) for x in detail.get("ai_review_exhausted_clips", []) if str(x).isdigit())
    exhausted.add(shot_number)
    detail["ai_review_exhausted_clips"] = sorted(exhausted)
    job.detail = detail
    job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
    job.message = f"Shot {shot_number} blocked: {reason}. No autonomous approval or fallback."
    media_studio_job_store.save(job)


async def run_ai_clip_review_background(
    job_id: str,
    shot_number: int,
    settings: Settings,
    lease_id: str,
) -> None:
    operation_key = _clip_review_key(shot_number)
    heartbeat_task = asyncio.create_task(_lease_heartbeat(job_id, operation_key, lease_id))
    try:
        job = media_studio_job_store.get(job_id)
        if _clip_ai_review_complete(job, shot_number):
            autopilot_operation_store.finish(job_id, operation_key, lease_id, status="COMPLETED")
            return
        if not job.result:
            raise AiReviewError("Media Studio result is unavailable.")
        clip = next((item for item in job.result.video_clips if item.shot_number == shot_number), None)
        if clip is None:
            raise AiReviewError(f"Animated shot {shot_number} not found.")

        try:
            review = await asyncio.wait_for(
                AiReviewService(settings).review_clip(job_id, shot_number),
                timeout=AI_REVIEW_HARD_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            if not _lease_is_current(job_id, operation_key, lease_id):
                return
            job = media_studio_job_store.get(job_id)
            timeout_count = _clip_review_timeout_count(job, shot_number) + 1
            _set_clip_review_timeout_count(job, shot_number, timeout_count)
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": lease_id,
                "status": "TIMED_OUT",
                "attempt": timeout_count,
                "started_at": _clip_review_operations(job).get(str(shot_number), {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": f"AI motion reviewer exceeded the {AI_REVIEW_HARD_TIMEOUT_SECONDS // 60}-minute hard timeout.",
            })
            autopilot_operation_store.finish(
                job_id, operation_key, lease_id, status="TIMED_OUT",
                error=f"AI motion reviewer exceeded {AI_REVIEW_HARD_TIMEOUT_SECONDS} seconds.",
            )
            if timeout_count >= MAX_CLIP_REVIEW_TIMEOUTS:
                media_studio_job_store.save(job)
                _mark_autonomous_clip_blocked(job_id, shot_number, "AI motion reviewer timed out repeatedly")
                recovered = media_studio_job_store.get(job_id)
                _set_clip_review_operation(recovered, shot_number, {
                    "lease_id": lease_id,
                    "status": "BLOCKED",
                    "attempt": timeout_count,
                    "started_at": None,
                    "updated_at": now,
                    "finished_at": now,
                    "reason": "Reviewer timed out repeatedly; shot blocked without substitute approval.",
                })
                recovered.message = f"Animated shot {shot_number} blocked after reviewer timeout"
                media_studio_job_store.save(recovered)
            else:
                job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
                job.message = f"AI motion reviewer timed out for shot {shot_number}; Autopilot will restart it automatically"
                job.error = None
                media_studio_job_store.save(job)
            return

        # The watchdog may have reclaimed this lease while the provider call was in
        # flight.  Discard obsolete responses instead of mutating the recovered asset.
        if not _lease_is_current(job_id, operation_key, lease_id):
            return

        job = media_studio_job_store.get(job_id)
        clip_reviews = dict(job.detail.get("ai_clip_reviews") or {})
        clip_reviews[str(shot_number)] = review_to_detail(review)
        job.detail = {**job.detail, "ai_clip_reviews": clip_reviews}
        media_studio_job_store.save(job)

        if review.decision == AiReviewDecision.PASS:
            approved = media_studio_job_store.approve_clip(
                job_id,
                shot_number,
                f"AI reviewer PASS: {review.summary}",
            )
            approved.detail = {
                **approved.detail,
                "clip_approval_actor": {
                    **dict(approved.detail.get("clip_approval_actor") or {}),
                    str(shot_number): "AI",
                },
            }
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(approved, shot_number, {
                "lease_id": lease_id,
                "status": "COMPLETED",
                "attempt": int((autopilot_operation_store.get(job_id, operation_key) or {}).get("attempt") or 1),
                "started_at": _clip_review_operations(approved).get(str(shot_number), {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": "AI motion review passed.",
            })
            media_studio_job_store.save(approved)
            autopilot_operation_store.finish(job_id, operation_key, lease_id, status="COMPLETED")
            return

        if not settings.autopilot_allow_regeneration:
            # This is a completed reviewer verdict, not an in-flight review.
            # Keep the clip blocked, but record a terminal operation state.
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": lease_id, "status": "BLOCKED",
                "attempt": int((autopilot_operation_store.get(job_id, operation_key) or {}).get("attempt") or 1),
                "started_at": _clip_review_operations(job).get(str(shot_number), {}).get("started_at"),
                "updated_at": now, "finished_at": now,
                "reason": "Motion review requires regeneration, but autonomous regeneration is disabled.",
            })
            media_studio_job_store.save(job)
            _mark_autonomous_clip_blocked(job_id, shot_number, "regeneration disabled and AI motion review did not PASS")
            autopilot_operation_store.finish(job_id, operation_key, lease_id, status="COMPLETED")
            return

        if clip.generation_attempt >= MAX_CLIP_ATTEMPTS:
            job = media_studio_job_store.get(job_id)
            exhausted = list(job.detail.get("ai_review_exhausted_clips") or [])
            if shot_number not in exhausted:
                exhausted.append(shot_number)
            now = datetime.now(timezone.utc).isoformat()
            job.detail = {**job.detail, "ai_review_exhausted_clips": exhausted}
            _set_clip_review_operation(job, shot_number, {
                "lease_id": lease_id,
                "status": "COMPLETED",
                "attempt": int((autopilot_operation_store.get(job_id, operation_key) or {}).get("attempt") or 1),
                "started_at": _clip_review_operations(job).get(str(shot_number), {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": "AI review completed with regeneration required; generation budget is exhausted.",
            })
            job.message = f"AI clip review could not clear shot {shot_number} after automatic regeneration attempts"
            media_studio_job_store.save(job)
            autopilot_operation_store.finish(job_id, operation_key, lease_id, status="COMPLETED")
            return

        next_job = media_studio_job_store.begin_clip_regeneration(
            job_id,
            shot_number,
            review.corrective_instruction or review.summary,
        )
        now = datetime.now(timezone.utc).isoformat()
        _set_clip_review_operation(next_job, shot_number, {
            "lease_id": lease_id,
            "status": "COMPLETED",
            "attempt": int((autopilot_operation_store.get(job_id, operation_key) or {}).get("attempt") or 1),
            "started_at": _clip_review_operations(next_job).get(str(shot_number), {}).get("started_at"),
            "updated_at": now,
            "finished_at": now,
            "reason": "AI review requested localized clip regeneration.",
        })
        media_studio_job_store.save(next_job)
        autopilot_operation_store.finish(job_id, operation_key, lease_id, status="COMPLETED")
        await regenerate_video_clip_for_job(
            job_id,
            shot_number,
            settings,
            review.corrective_instruction or review.summary,
        )
    except (AiReviewError, ValueError) as exc:
        if not _lease_is_current(job_id, operation_key, lease_id):
            return
        autopilot_operation_store.finish(job_id, operation_key, lease_id, status="FAILED", error=str(exc))
        try:
            job = media_studio_job_store.get(job_id)
            failures = dict(job.detail.get("ai_clip_review_failures") or {})
            failures[str(shot_number)] = int(failures.get(str(shot_number)) or 0) + 1
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": lease_id,
                "status": "FAILED",
                "attempt": failures[str(shot_number)],
                "started_at": _clip_review_operations(job).get(str(shot_number), {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": str(exc),
            })
            job.detail = {**job.detail, "ai_clip_review_failures": failures}
            if failures[str(shot_number)] >= MAX_CLIP_REVIEW_TIMEOUTS:
                media_studio_job_store.save(job)
                _mark_autonomous_clip_blocked(job_id, shot_number, "AI motion reviewer failed repeatedly")
                recovered = media_studio_job_store.get(job_id)
                _set_clip_review_operation(recovered, shot_number, {
                    "lease_id": lease_id,
                    "status": "BLOCKED",
                    "attempt": failures[str(shot_number)],
                    "started_at": None,
                    "updated_at": now,
                    "finished_at": now,
                    "reason": "AI reviewer failed repeatedly; shot blocked without substitute approval.",
                })
                recovered.message = f"Animated shot {shot_number} blocked after reviewer failure"
                media_studio_job_store.save(recovered)
            else:
                job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
                job.message = f"AI motion review for shot {shot_number} failed transiently; Autopilot will restart it automatically"
                job.error = None
                media_studio_job_store.save(job)
        except Exception:
            pass
    except Exception as exc:
        if not _lease_is_current(job_id, operation_key, lease_id):
            return
        autopilot_operation_store.finish(job_id, operation_key, lease_id, status="FAILED", error=str(exc))
        try:
            job = media_studio_job_store.get(job_id)
            now = datetime.now(timezone.utc).isoformat()
            _set_clip_review_operation(job, shot_number, {
                "lease_id": lease_id,
                "status": "FAILED",
                "attempt": int((autopilot_operation_store.get(job_id, operation_key) or {}).get("attempt") or 1),
                "started_at": _clip_review_operations(job).get(str(shot_number), {}).get("started_at"),
                "updated_at": now,
                "finished_at": now,
                "reason": f"Unexpected reviewer failure: {exc}",
            })
            job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
            job.message = f"AI motion review for shot {shot_number} stopped unexpectedly; Autopilot will recover it"
            job.error = None
            media_studio_job_store.save(job)
        except Exception:
            pass
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


@router.post("/media-jobs/{job_id}/clips/{shot_number}/ai-review", response_model=MediaStudioJob)
async def ai_review_clip(
    job_id: str,
    shot_number: int,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        return _schedule_clip_review(
            job_id=job_id,
            shot_number=shot_number,
            settings=settings,
            background_tasks=background_tasks,
        )
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/assembly-jobs/{job_id}/ai-review", response_model=FinalAssemblyJob)
async def ai_review_visual_master(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        job = final_assembly_job_store.get(job_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=404, detail="Final assembly job not found.")
    if job.stage not in {FinalAssemblyJobStage.COMPLETED, FinalAssemblyJobStage.DELIVERED} or not job.result:
        raise HTTPException(status_code=409, detail="The visual master is not ready for AI review.")
    if (
        job.stage == FinalAssemblyJobStage.DELIVERED
        and job.detail.get("approval_actor") == "AI"
        and _review_pass(job.detail.get("ai_visual_master_review"))
    ):
        return job

    if job.detail.get("ai_review_exhausted") and job.result:
        salvage = _salvaged_review_detail(
            job.detail.get("ai_visual_master_review"),
            recovery_mode="BEST_RENDER_FALLBACK",
            summary="AI_SALVAGED: repeated assembly review could not improve the existing render; deterministic delivery QC and final human review remain authoritative.",
        )
        if job.stage == FinalAssemblyJobStage.COMPLETED:
            job = final_assembly_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        else:
            job = final_assembly_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "approval_actor": "AI",
            "ai_visual_master_review": salvage,
            "ai_review_exhausted": False,
            "ai_salvaged_visual_master": True,
        }
        job.message = "Visual master AI-salvaged and continuing to audio finishing"
        final_assembly_job_store.save(job)
        return final_assembly_job_store.get(job_id)

    try:
        review = await AiReviewService(settings).review_visual_master(job_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    attempt = int(job.detail.get("ai_review_attempt") or 0) + 1
    job.detail = {
        **job.detail,
        "ai_review_attempt": attempt,
        "ai_visual_master_review": review_to_detail(review),
    }
    final_assembly_job_store.save(job)

    if review.decision == AiReviewDecision.PASS:
        if job.stage == FinalAssemblyJobStage.DELIVERED:
            adopted = final_assembly_job_store.get(job_id)
            adopted.detail = {
                **adopted.detail,
                "previous_approval_actor": adopted.detail.get("approval_actor"),
                "approval_actor": "AI",
                "approval_review_summary": review.summary,
                "ai_visual_master_review": review_to_detail(review),
            }
            adopted.message = "Existing visual master re-reviewed by AI and ready for audio finishing"
            final_assembly_job_store.save(adopted)
            return final_assembly_job_store.get(job_id)
        return final_assembly_job_store.approve(
            job_id,
            actor="AI",
            review_summary=review.summary,
        )

    if not settings.autopilot_allow_regeneration:
        job = final_assembly_job_store.get(job_id)
        salvage = _salvaged_review_detail(
            review_to_detail(review),
            recovery_mode="ACCEPT_CURRENT_NO_REGENERATION",
            summary=f"AI_SALVAGED: automatic regeneration is disabled; keeping the current visual master. Reviewer note: {review.summary}",
        )
        if job.stage == FinalAssemblyJobStage.COMPLETED:
            job = final_assembly_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        job = final_assembly_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "ai_visual_master_review": salvage,
            "approval_actor": "AI",
            "ai_salvaged_visual_master": True,
            "automatic_regeneration_disabled": True,
        }
        job.message = "Visual master kept; automatic regeneration is disabled"
        final_assembly_job_store.save(job)
        return final_assembly_job_store.get(job_id)

    if attempt >= MAX_ASSEMBLY_REVIEW_ATTEMPTS:
        job = final_assembly_job_store.get(job_id)
        salvage = _salvaged_review_detail(
            review_to_detail(review),
            recovery_mode="BEST_RENDER_FALLBACK",
            summary="AI_SALVAGED: the best completed assembly is continuing to delivery because repeated rerendering did not improve the AI review. Deterministic QC and final human approval remain authoritative.",
        )
        if job.stage == FinalAssemblyJobStage.COMPLETED:
            job = final_assembly_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        job = final_assembly_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "ai_visual_master_review": salvage,
            "ai_review_exhausted": False,
            "ai_salvaged_visual_master": True,
            "approval_actor": "AI",
        }
        job.message = "Visual master AI-salvaged and continuing to audio finishing"
        final_assembly_job_store.save(job)
        return final_assembly_job_store.get(job_id)

    next_job = final_assembly_job_store.create(job.media_job_id)
    next_job.detail = {
        **next_job.detail,
        "ai_review_attempt": attempt,
        "rerender_reason": review.corrective_instruction or review.summary,
    }
    final_assembly_job_store.save(next_job)
    background_tasks.add_task(tenant_bound(render_final_assembly), next_job.job_id, settings)
    return next_job


@router.post("/audio-jobs/{job_id}/ai-review", response_model=AudioFinishingJob)
async def ai_review_audio_master(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        job = audio_finishing_job_store.get(job_id)
    except AudioFinishingJobNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")
    if job.stage not in {AudioFinishingJobStage.COMPLETED, AudioFinishingJobStage.DELIVERED} or not job.result:
        raise HTTPException(status_code=409, detail="The audio master is not ready for AI review.")
    if (
        job.stage == AudioFinishingJobStage.DELIVERED
        and job.detail.get("approval_actor") == "AI"
        and _review_pass(job.detail.get("ai_audio_review"))
        and str((job.detail.get("ai_audio_review") or {}).get("original_decision") or "PASS").upper() == "PASS"
    ):
        return job

    # Do not repeatedly call the AI reviewer for an unchanged, salvaged mix.
    # The supervisor handles this as NEEDS_ATTENTION; a new audio version must
    # be created before another independent review is meaningful.
    saved_review = job.detail.get("ai_audio_review") or {}
    if isinstance(saved_review, dict) and (
        str(saved_review.get("outcome") or "").upper() == "AI_SALVAGED"
        and str(saved_review.get("original_decision") or "").upper() in {"REGENERATE", "FAIL", "REJECT"}
    ):
        return job

    if job.detail.get("ai_review_exhausted") and job.result:
        salvage = _salvaged_review_detail(
            job.detail.get("ai_audio_review"),
            recovery_mode="BEST_AUDIO_MIX_FALLBACK",
            summary="AI_SALVAGED: repeated remix attempts did not improve the listening review; the best rendered mix is continuing to deterministic delivery QC and final human review.",
        )
        if job.stage == AudioFinishingJobStage.COMPLETED:
            job = audio_finishing_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        else:
            job = audio_finishing_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "approval_actor": "AI",
            "ai_audio_review": salvage,
            "ai_review_exhausted": False,
            "ai_salvaged_audio_master": True,
            "human_final_approved": False,
        }
        job.message = f"Audio master v{job.version_number} AI-salvaged and continuing to delivery QC"
        audio_finishing_job_store.save(job)
        return audio_finishing_job_store.get(job_id)

    try:
        review = await AiReviewService(settings).review_audio_master(job_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    attempt = int(job.detail.get("ai_review_attempt") or 0) + 1
    job.detail = {
        **job.detail,
        "ai_review_attempt": attempt,
        "ai_audio_review": review_to_detail(review),
    }
    audio_finishing_job_store.save(job)

    if review.decision == AiReviewDecision.PASS:
        if job.stage == AudioFinishingJobStage.DELIVERED:
            adopted = audio_finishing_job_store.get(job_id)
            adopted.detail = {
                **adopted.detail,
                "previous_approval_actor": adopted.detail.get("approval_actor"),
                "approval_actor": "AI",
                "approval_review_summary": review.summary,
                "ai_audio_review": review_to_detail(review),
                "human_final_approved": False,
            }
            adopted.message = f"Audio master v{adopted.version_number} re-reviewed by AI and ready for delivery QC"
            audio_finishing_job_store.save(adopted)
            return audio_finishing_job_store.get(job_id)
        return audio_finishing_job_store.approve(
            job_id,
            actor="AI",
            review_summary=review.summary,
        )

    if not settings.autopilot_allow_regeneration:
        job = audio_finishing_job_store.get(job_id)
        salvage = _salvaged_review_detail(
            review_to_detail(review),
            recovery_mode="ACCEPT_CURRENT_NO_REGENERATION",
            summary=f"AI_SALVAGED: automatic regeneration is disabled; keeping the current audio master. Reviewer note: {review.summary}",
        )
        if job.stage == AudioFinishingJobStage.COMPLETED:
            job = audio_finishing_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        job = audio_finishing_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "ai_audio_review": salvage,
            "approval_actor": "AI",
            "ai_salvaged_audio_master": True,
            "automatic_regeneration_disabled": True,
            "human_final_approved": False,
        }
        job.message = f"Audio master v{job.version_number} kept; automatic regeneration is disabled"
        audio_finishing_job_store.save(job)
        return audio_finishing_job_store.get(job_id)

    if attempt >= MAX_AUDIO_REVIEW_ATTEMPTS:
        job = audio_finishing_job_store.get(job_id)
        salvage = _salvaged_review_detail(
            review_to_detail(review),
            recovery_mode="BEST_AUDIO_MIX_FALLBACK",
            summary="AI_SALVAGED: the best rendered mix is continuing after automatic remix attempts were exhausted. Deterministic QC and final human approval remain authoritative.",
        )
        if job.stage == AudioFinishingJobStage.COMPLETED:
            job = audio_finishing_job_store.approve(job_id, actor="AI", review_summary=salvage["summary"])
        job = audio_finishing_job_store.get(job_id)
        job.detail = {
            **job.detail,
            "ai_audio_review": salvage,
            "ai_review_exhausted": False,
            "ai_salvaged_audio_master": True,
            "approval_actor": "AI",
            "human_final_approved": False,
        }
        job.message = f"Audio master v{job.version_number} AI-salvaged and continuing to delivery QC"
        audio_finishing_job_store.save(job)
        return audio_finishing_job_store.get(job_id)

    options = job.options.model_copy(deep=True)
    suggestion = review.suggested_mix
    if suggestion:
        if suggestion.voice_volume is not None:
            options.voice_volume = suggestion.voice_volume
        if suggestion.music_volume is not None:
            options.music_volume = suggestion.music_volume
        if suggestion.ambience_volume is not None:
            options.ambience_volume = suggestion.ambience_volume
        if suggestion.duck_music_during_voiceover is not None:
            options.duck_music_during_voiceover = suggestion.duck_music_during_voiceover

    next_job = audio_finishing_job_store.create(job.assembly_job_id, options)
    next_job.detail = {
        **next_job.detail,
        "ai_review_attempt": attempt,
        "remix_reason": review.corrective_instruction or review.summary,
    }
    audio_finishing_job_store.save(next_job)
    background_tasks.add_task(tenant_bound(render_audio_finishing), next_job.job_id, settings)
    return next_job


@router.post("/audio-jobs/{job_id}/ai-review/qc", response_model=DeliveryQcReport)
async def ai_review_qc_warnings(
    job_id: str,
    settings: Settings = Depends(get_settings),
):
    try:
        report = delivery_qc_store.get(job_id)
    except DeliveryQcReportNotFoundError:
        raise HTTPException(status_code=404, detail="Delivery QC report not found.")
    if report.overall_status == DeliveryQcOverallStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Blocking deterministic QC failures cannot be overridden by AI.")
    if report.overall_status == DeliveryQcOverallStatus.READY:
        return report

    try:
        review = await AiReviewService(settings).review_delivery_warnings(job_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    report.metrics = {
        **report.metrics,
        "ai_warning_review": review_to_detail(review),
    }
    if review.decision == AiReviewDecision.PASS:
        report.overall_status = DeliveryQcOverallStatus.READY
        report.ready_for_delivery = True
        delivery_qc_store.save(report)
        return report

    delivery_qc_store.save(report)
    raise HTTPException(
        status_code=409,
        detail=f"AI delivery reviewer recommends regeneration before final review: {review.summary}",
    )


@router.post("/publishing-drafts/{draft_id}/ai-review", response_model=PublishingDraft)
async def ai_review_publishing_copy(
    draft_id: str,
    settings: Settings = Depends(get_settings),
):
    try:
        draft = publishing_draft_store.get(draft_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Publishing draft not found.")
    if draft.status == PublishingDraftStatus.APPROVED and "[AI_REVIEW_APPROVED]" in (draft.generation_note or ""):
        return draft

    try:
        review = await AiReviewService(settings).review_publishing_draft(draft_id)
    except AiReviewError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if review.decision == AiReviewDecision.PASS:
        return publishing_assistant_service.approve(
            draft_id,
            actor="AI",
            review_summary=review.summary,
        )

    if not settings.autopilot_allow_regeneration:
        approved = publishing_assistant_service.approve(
            draft_id,
            actor="AI",
            review_summary=f"AI_SALVAGED: automatic regeneration is disabled; keeping the current publishing copy. Reviewer note: {review.summary}",
        )
        approved.generation_note = (
            f"{approved.generation_note} [AI_SALVAGED] Automatic regeneration disabled; current copy retained."
        ).strip()
        publishing_draft_store.save(approved)
        return publishing_draft_store.get(approved.draft_id)

    if draft.version_number >= MAX_PUBLISHING_REVIEW_ATTEMPTS:
        approved = publishing_assistant_service.approve(
            draft_id,
            actor="AI",
            review_summary=f"AI_SALVAGED after targeted rewrite limit: {review.summary}",
        )
        approved.generation_note = (
            f"{approved.generation_note} [AI_SALVAGED] Publishing critic exhausted targeted rewrites; the best available copy was kept for final packaging."
        ).strip()
        publishing_draft_store.save(approved)
        return publishing_draft_store.get(approved.draft_id)

    try:
        next_draft = await publishing_assistant_service.regenerate(
            draft_id,
            review.fields_to_regenerate,
        )
    except PublishingAssistantError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    next_draft.generation_note = (
        f"{next_draft.generation_note} AI critic requested targeted rewrite: {review.summary}"
    ).strip()
    publishing_draft_store.save(next_draft)
    return next_draft


def _require_complete_creator_review_chain(*, audio_job, assembly_job, media_job, production_job) -> None:
    """Validate manually approved, current assets without substituting AI approval."""
    if (
        not production_job.result
        or str(production_job.result.review_status.value) != "APPROVED"
        or not media_job.result
        or not media_job.result.reference_asset
        or not media_job.result.reference_approved
        or media_job.result.reference_asset.review_status != MediaAssetReviewStatus.APPROVED
    ):
        raise HTTPException(status_code=409, detail="Approve the production plan and character reference first.")
    result = media_job.result
    if result.required_keyframes <= 0 or len(result.keyframes) != result.required_keyframes:
        raise HTTPException(status_code=409, detail="All storyboard keyframes must be present.")
    if any(
        frame.review_status != MediaAssetReviewStatus.APPROVED
        or not frame.fidelity_report
        or frame.fidelity_report.status not in (KeyframeFidelityStatus.PASS, KeyframeFidelityStatus.ADAPTATION_ACCEPTED)
        for frame in result.keyframes
    ):
        raise HTTPException(status_code=409, detail="All storyboard keyframes must pass review and human approval.")
    if result.required_clips <= 0 or len(result.video_clips) != result.required_clips or any(
        clip.review_status != MediaAssetReviewStatus.APPROVED for clip in result.video_clips
    ):
        raise HTTPException(status_code=409, detail="All animated clips must be approved.")
    if (
        not assembly_job.result
        or assembly_job.stage != FinalAssemblyJobStage.DELIVERED
        or assembly_job.result.review_status.value != "APPROVED"
        or assembly_job.media_job_id != media_job.job_id
        or assembly_job.production_brief_job_id != production_job.job_id
    ):
        raise HTTPException(status_code=409, detail="The current final visual master must be approved.")
    clips = {clip.shot_number: clip.asset_id for clip in result.video_clips}
    if len(assembly_job.result.timeline) != result.required_clips or any(
        clips.get(entry.shot_number) != entry.source_clip_asset_id for entry in assembly_job.result.timeline
    ):
        raise HTTPException(status_code=409, detail="Visual assembly references outdated animated clips.")
    if audio_job.assembly_job_id != assembly_job.job_id:
        raise HTTPException(status_code=409, detail="Audio does not match the approved visual master.")


class FinalHumanApprovalRequest(BaseModel):
    quality_override: bool = False
    override_reason: str | None = Field(default=None, max_length=1000)


def _require_human_override_asset_lineage(*, audio_job, assembly_job, media_job, production_job) -> None:
    """Do not require AI creative success, but never allow stale or absent source media."""
    if not production_job.result or not media_job.result or not media_job.result.reference_asset:
        raise HTTPException(status_code=409, detail="Production plan and character media must exist before human override.")
    media = media_job.result
    if media.required_keyframes <= 0 or len(media.keyframes) != media.required_keyframes or media.required_clips <= 0 or len(media.video_clips) != media.required_clips:
        raise HTTPException(status_code=409, detail="All required keyframes and animated clips must exist before human override.")
    if not assembly_job.result or assembly_job.stage != FinalAssemblyJobStage.DELIVERED:
        raise HTTPException(status_code=409, detail="Final visual master must be delivered before human override.")
    if assembly_job.media_job_id != media_job.job_id or assembly_job.production_brief_job_id != production_job.job_id:
        raise HTTPException(status_code=409, detail="Final visual master production lineage does not match.")
    current_clips = {clip.shot_number: clip.asset_id for clip in media.video_clips}
    if len(current_clips) != media.required_clips or len(assembly_job.result.timeline) != media.required_clips or any(current_clips.get(entry.shot_number) != entry.source_clip_asset_id for entry in assembly_job.result.timeline):
        raise HTTPException(status_code=409, detail="Final visual master contains outdated clips; rebuild before approval.")
    if audio_job.assembly_job_id != assembly_job.job_id:
        raise HTTPException(status_code=409, detail="Audio does not match the current visual master.")


@router.post("/audio-jobs/{job_id}/human-final-approve", response_model=AudioFinishingJob)
async def human_final_approve(job_id: str, request: FinalHumanApprovalRequest | None = None):
    try:
        job = audio_finishing_job_store.get(job_id)
    except AudioFinishingJobNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")

    if (
        job.stage != AudioFinishingJobStage.DELIVERED
        or not job.result
        or job.result.review_status != AudioFinishingReviewStatus.APPROVED
        or str(job.detail.get("approval_actor") or "").upper() not in ("AI", "HUMAN")
    ):
        raise HTTPException(status_code=409, detail="An approved audio master is required before final human approval.")

    try:
        assembly_job = final_assembly_job_store.get(job.assembly_job_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=409, detail="AI-reviewed visual master could not be verified.")
    try:
        media_job = media_studio_job_store.get(assembly_job.media_job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=409, detail="AI-reviewed media lineage could not be verified.")
    try:
        production_job = production_brief_job_store.get(assembly_job.production_brief_job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=409, detail="AI-reviewed production-plan lineage could not be verified.")

    ai_owned = str(job.detail.get("approval_actor") or "").upper() == "AI"
    overridden_ai_finding = None
    if ai_owned and request and request.quality_override:
        if not request.override_reason or not request.override_reason.strip():
            raise HTTPException(status_code=422, detail="Please provide a reason for overriding AI creative-quality findings.")
        _require_human_override_asset_lineage(
            audio_job=job, assembly_job=assembly_job,
            media_job=media_job, production_job=production_job,
        )
        try:
            _require_complete_ai_review_chain(
                audio_job=job, assembly_job=assembly_job,
                media_job=media_job, production_job=production_job,
            )
        except HTTPException as exc:
            # Only AI creative-review rejections may be overridden; structural and
            # lineage failures remain blocked by the independent check above.
            detail = str(exc.detail)
            eligible = (
                "AI review", "AI motion review", "AI-reviewed", "AI-salvaged",
                "AI review before", "fidelity gate", "AI plan review",
            )
            if not any(marker.lower() in detail.lower() for marker in eligible):
                raise
            overridden_ai_finding = detail
    elif ai_owned:
        _require_complete_ai_review_chain(
            audio_job=job, assembly_job=assembly_job,
            media_job=media_job, production_job=production_job,
        )
    else:
        # The mode is derived from the persisted approval actor, never request input.
        _require_complete_creator_review_chain(
            audio_job=job, assembly_job=assembly_job,
            media_job=media_job, production_job=production_job,
        )

    try:
        qc = delivery_qc_store.get(job_id)
    except DeliveryQcReportNotFoundError:
        raise HTTPException(status_code=409, detail="Final Delivery QC must complete before final human approval.")
    from app.services.delivery_qc_service import qc_allows_manual_delivery
    if not qc_allows_manual_delivery(qc):
        raise HTTPException(status_code=409, detail="Final Delivery QC must be READY before final human approval.")

    package = delivery_package_store.latest_for_audio_job(job_id)
    if package is None or not package.publishing_draft_id:
        raise HTTPException(status_code=409, detail="The final delivery package must include AI-reviewed publishing copy.")
    if (
        package.audio_job_id != job_id
        or package.qc_report_id != qc.report_id
        or package.assembly_job_id != assembly_job.job_id
        or package.audio_version != job.version_number
        or package.delivery_asset_id != qc.delivery_asset_id
    ):
        raise HTTPException(status_code=409, detail="The final delivery package does not match the current AI-reviewed audio/QC lineage.")

    try:
        draft = publishing_draft_store.get(package.publishing_draft_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=409, detail="Packaged publishing copy could not be verified.")
    if draft.status != PublishingDraftStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Publishing copy must be approved before final human approval.")
    if ai_owned and "[AI_REVIEW_APPROVED]" not in (draft.generation_note or ""):
        raise HTTPException(status_code=409, detail="Autopilot publishing copy must pass AI review before final human approval.")

    job.detail = {
        **job.detail,
        "human_final_approved": True,
        "human_final_approved_at": datetime.now(timezone.utc).isoformat(),
        "final_approval_actor": "HUMAN",
        "final_approval_method": "QUALITY_OVERRIDE" if overridden_ai_finding else "STANDARD",
        **({"human_quality_override": {
            "reason": request.override_reason.strip(),
            "original_ai_blocker": overridden_ai_finding,
            "production_job_id": production_job.job_id,
            "media_job_id": media_job.job_id,
            "assembly_job_id": assembly_job.job_id,
            "audio_job_id": job.job_id,
            "audio_version": job.version_number,
            "final_asset_id": qc.delivery_asset_id,
        }} if overridden_ai_finding and request else {}),
    }
    job.message = f"Final video v{job.version_number} human-approved"
    audio_finishing_job_store.save(job)
    return audio_finishing_job_store.get(job_id)
