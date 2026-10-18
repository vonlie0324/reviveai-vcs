from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel
from PIL import ImageFont

from app.core.firebase_auth import require_tenant_context
from app.api.routes.platform_admin import require_platform_admin
from app.models.final_assembly import FinalAssemblyJobStage, FinalAssemblyReviewStatus
from app.models.audio_finishing import AudioFinishingJobStage
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.production_brief_job_service import production_brief_job_store
from app.services.final_assembly_job_service import final_assembly_job_store
from app.services.media_studio_job_service import media_studio_job_store

from app.services.autopilot_state_service import (
    AutopilotSessionPayload,
    AutopilotStateConflictError,
    AutopilotStateRecord,
    autopilot_state_store,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["autopilot-state"])


class AutopilotStateWriteRequest(BaseModel):
    session: AutopilotSessionPayload
    expected_revision: Optional[int] = None


class AutopilotStateDeleteRequest(BaseModel):
    expected_revision: Optional[int] = None


@router.get("/autopilot-state", response_model=AutopilotStateRecord)
async def get_autopilot_state():
    try:
        record = autopilot_state_store.get()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Autopilot state storage is unavailable or requires reconciliation. No session was reset.") from exc
    if record is None:
        raise HTTPException(status_code=404, detail="No persisted Autopilot session exists for this workspace.")
    return record


@router.put("/autopilot-state", response_model=AutopilotStateRecord)
async def put_autopilot_state(request: AutopilotStateWriteRequest):
    try:
        return autopilot_state_store.save(
            request.session,
            expected_revision=request.expected_revision,
        )
    except AutopilotStateConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Autopilot state changed on another client.",
                "current": exc.current.model_dump(mode="json") if exc.current else None,
            },
        )


class SingleTrialRequest(BaseModel):
    expected_revision: int
    recommendation_id: str
    recovery_job_id: str
    title: str


@router.get("/autopilot-state/production-readiness", dependencies=[Depends(require_tenant_context)])
async def get_production_readiness():
    """Validate launch configuration without generating anything or changing state."""
    from app.services.autopilot_readiness import production_readiness
    return production_readiness()


class SwitchProductionRequest(BaseModel):
    expected_revision: int
    production_job_id: str
    confirm: str


@router.post("/autopilot-state/switch-production", response_model=AutopilotStateRecord,
             dependencies=[Depends(require_tenant_context)])
async def switch_autopilot_production(request: SwitchProductionRequest):
    try:
        return autopilot_state_store.switch_to_production(**request.model_dump())
    except AutopilotStateConflictError as exc:
        raise HTTPException(status_code=409, detail={
            "message": "Autopilot state changed. Refresh before switching productions.",
            "current": exc.current.model_dump(mode="json") if exc.current else None,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class BriefConfigurationRecoveryRequest(BaseModel):
    expected_revision: int
    production_job_id: str
    confirm: str


@router.post(
    "/autopilot-state/recover-brief-configuration",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def recover_brief_configuration(
    request: BriefConfigurationRecoveryRequest,
    background_tasks: BackgroundTasks,
):
    """Authorize exactly one config-only brief retry; never clear historical attempts.

    A durable CLAIMED marker is committed before creating another queued brief.
    If an intermediate step fails, stop instead of creating a second paid job.
    """
    import math
    import os
    from datetime import datetime, timezone

    from app.core.config import get_settings
    from app.api.routes.production_brief import retry_production_brief_job
    from app.models.production_brief import ProductionBriefRetryRequest
    from app.services.production_brief_job_service import production_brief_job_store

    if request.confirm != "RETRY_BRIEF_AFTER_CONFIG_FIX":
        raise HTTPException(422, "Explicit brief recovery confirmation is required")

    raw = os.environ.get("REVIVEAI_GEMINI_BRIEF_RESERVATION_USD", "")
    try:
        reservation = float(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(409, "Brief reservation environment setting is still invalid") from exc
    if not math.isfinite(reservation) or reservation <= 0:
        raise HTTPException(409, "Brief reservation must be finite and positive")

    record = autopilot_state_store.get()
    if record is None or record.revision != request.expected_revision:
        raise HTTPException(409, "Autopilot changed; refresh state before authorizing recovery")
    previous = record.session
    if (previous.scope != "PRODUCTION" or previous.executionOwner != "BACKEND"
            or previous.status != "NEEDS_ATTENTION" or previous.attentionStage != "FAILURE"
            or previous.currentProductionJobId != request.production_job_id):
        raise HTTPException(409, "Current Autopilot state is not the specified failed production")
    if any((previous.currentMediaJobId, previous.currentAssemblyJobId,
            previous.currentAudioJobId, previous.currentDeliveryPackageId,
            previous.currentPublishingDraftId, previous.currentPublicationId)):
        raise HTTPException(409, "Downstream assets already exist; this recovery only supports a failed brief")
    if previous.currentRecommendationId is None or previous.recoveryJobId is None:
        raise HTTPException(409, "Saved production direction is missing")

    try:
        job = production_brief_job_store.get(request.production_job_id)
    except Exception as exc:
        raise HTTPException(409, "Failed production brief cannot be loaded") from exc
    if (job.recommendation_id != previous.currentRecommendationId
            or job.recovery_job_id != previous.recoveryJobId
            or str(getattr(job.stage, "value", job.stage)) != "FAILED"
            or (job.error or "") != "Configure REVIVEAI_GEMINI_BRIEF_RESERVATION_USD"):
        raise HTTPException(409, "Brief lineage or failure reason differs; refusing recovery")

    repair_key = f"brief-config-repair:{job.job_id}"
    if previous.attempts.get(repair_key, 0):
        raise HTTPException(409, "A configuration repair has already been claimed for this brief")
    if previous.attempts.get(f"brief:{job.recommendation_id}", 0) < 2:
        raise HTTPException(409, "Automatic retries are not exhausted; use normal recovery")

    # First commit an exclusive, durable claim without allowing supervisor progress.
    claimed = previous.model_copy(deep=True)
    claimed.attempts = {**previous.attempts, repair_key: 1}
    claimed.message = "One-time configuration recovery claimed; preparing a fresh brief from the immutable source snapshot."
    claimed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        claim_record = autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot changed before recovery claim") from exc

    # The existing retry route validates Content DNA and analysis lineage and queues
    # one replacement brief; it does not regenerate the previous failed job in place.
    try:
        new_job = await retry_production_brief_job(
            job.job_id,
            ProductionBriefRetryRequest(fidelity_mode=job.fidelity_mode),
            background_tasks,
            get_settings(),
        )
    except Exception:
        # Leave the claim intact: no duplicate billable retry on a second click.
        raise HTTPException(409, "Brief retry could not be queued; repair claim retained for reconciliation")

    current = autopilot_state_store.get()
    if (current is None or current.revision != claim_record.revision
            or current.session.currentProductionJobId != job.job_id
            or current.session.attempts.get(repair_key) != 1):
        raise HTTPException(409, {
            "message": "Replacement brief created but Autopilot changed; reconcile before retrying",
            "created_production_job_id": new_job.job_id,
        })
    resumed = current.session.model_copy(deep=True)
    resumed.status = "RUNNING"
    resumed.attentionStage = None
    resumed.currentProductionJobId = new_job.job_id
    resumed.attempts = {**resumed.attempts, repair_key: 2}
    resumed.message = "Configuration repaired. AI Autopilot is rebuilding the brief from its saved source direction."
    resumed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(resumed, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, {
            "message": "Replacement brief exists but Autopilot activation conflicted; reconcile before retrying",
            "created_production_job_id": new_job.job_id,
        }) from exc


class ReconcileExistingBriefRequest(BaseModel):
    expected_revision: int
    failed_production_job_id: str
    replacement_production_job_id: str
    confirm: str


@router.post(
    "/autopilot-state/reconcile-brief-configuration",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def reconcile_existing_brief_configuration(request: ReconcileExistingBriefRequest):
    """Activate an already-created brief; never call Gemini or create a job."""
    try:
        return autopilot_state_store.reconcile_brief_config_replacement(**request.model_dump())
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, detail={
            "message": "Autopilot revision changed; refresh before reconciliation.",
            "current": exc.current.model_dump(mode="json") if exc.current else None,
        }) from exc
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc


class RestoreTrialRequest(BaseModel):
    expected_revision: int


@router.post("/autopilot-state/start-single-trial", response_model=AutopilotStateRecord)
async def start_single_trial(request: SingleTrialRequest):
    try:
        return autopilot_state_store.start_single_trial(**request.model_dump())
    except AutopilotStateConflictError:
        raise HTTPException(status_code=409, detail="Autopilot state changed. Refresh before starting the trial")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/autopilot-state/restore-trial-campaign", response_model=AutopilotStateRecord)
async def restore_trial_campaign(request: RestoreTrialRequest):
    try:
        return autopilot_state_store.restore_trial_campaign(expected_revision=request.expected_revision)
    except AutopilotStateConflictError:
        raise HTTPException(status_code=409, detail="Autopilot state changed. Refresh before restoring")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/autopilot-state", status_code=status.HTTP_204_NO_CONTENT)
async def delete_autopilot_state(request: AutopilotStateDeleteRequest):
    try:
        autopilot_state_store.clear(expected_revision=request.expected_revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Autopilot state changed on another client.",
                "current": exc.current.model_dump(mode="json") if exc.current else None,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/autopilot-state/repair-caption-renderer",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def authorize_caption_renderer_repair():
    """Authorize one infrastructure-only assembly retry; the supervisor owns execution.

    This does NOT reset general retry counts, create media, or bypass AI review.
    Repeated HTTP requests are safe: an already granted authorization is not
    granted again. The queue starts once the state becomes RUNNING.
    """
    font_file = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        ImageFont.truetype(font_file, 48)
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "Caption renderer font is still unavailable on this server.") from exc

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, "Autopilot state was not found.")
    session = record.session
    if session.status != "NEEDS_ATTENTION" or session.attentionStage != "VISUAL_MASTER":
        raise HTTPException(409, "Autopilot is not paused for visual-master recovery.")
    if not session.currentAssemblyJobId or not session.currentMediaJobId:
        raise HTTPException(409, "Saved media or assembly lineage is missing.")

    try:
        assembly = final_assembly_job_store.get(session.currentAssemblyJobId)
        media = media_studio_job_store.get(session.currentMediaJobId)
    except Exception as exc:
        raise HTTPException(409, "Current saved production lineage cannot be verified.") from exc
    if assembly.media_job_id != media.job_id or assembly.stage != FinalAssemblyJobStage.FAILED:
        raise HTTPException(409, "The saved assembly is not the failed assembly for this media job.")
    error = (assembly.error or "").lower()
    if "scalable bold caption font" not in error and "dejavu sans" not in error:
        raise HTTPException(409, "This repair action only supports missing-caption-font failures.")
    latest = final_assembly_job_store.latest_for_media_job(media.job_id)
    if latest and latest.job_id != assembly.job_id:
        raise HTTPException(409, "A newer assembly already exists. Reconcile it before repair.")

    repair_key = f"assembly-infra-repair:{assembly.job_id}"
    if session.attempts.get(repair_key, 0):
        raise HTTPException(409, "Caption infrastructure repair was already authorized for this failed assembly.")
    new_session = session.model_copy(deep=True)
    new_session.attempts = dict(session.attempts)
    new_session.attempts[repair_key] = 1
    new_session.status = "RUNNING"
    new_session.attentionStage = None
    new_session.message = "Caption renderer verified. Resuming failed assembly using approved clips; no new Veo generation requested."
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    new_session.updatedAt = now
    new_session.lastSupervisorHeartbeatAt = now
    try:
        return autopilot_state_store.save(new_session, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot state changed during repair. Refresh and inspect before retrying.") from exc


@router.post(
    "/autopilot-state/repair-tts-audio",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def authorize_tts_audio_repair():
    """Restore one archived TTS SDK failure when no production is in progress.

    This only repairs deterministic lineage, never bypasses visual AI approval,
    never retries unrelated audio errors, and never creates a new Veo job.
    """
    from datetime import datetime, timezone
    from app.services.final_assembly_job_service import final_assembly_job_store
    from app.services.media_studio_job_service import media_studio_job_store
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, "Autopilot state was not found.")
    session = record.session
    if session.executionOwner != "BACKEND" or session.scope != "CAMPAIGN":
        raise HTTPException(409, "This repair requires backend-owned campaign Autopilot.")
    # A completed campaign is inactive and may contain an archived production
    # that needs a strictly scoped infrastructure repair. Never interrupt
    # another active production or a campaign awaiting a different action.
    if session.status not in {"RUNNING", "COMPLETED"}:
        raise HTTPException(409, "Campaign is not in a repairable idle state.")
    if any((
        session.currentRecommendationId, session.currentProductionJobId,
        session.currentMediaJobId, session.currentAssemblyJobId,
        session.currentAudioJobId, session.currentDeliveryPackageId,
        session.currentPublishingDraftId, session.currentPublicationId,
    )):
        raise HTTPException(409, "A production is currently active. Do not interrupt it for audio repair.")

    recommendation_id = "replenished_f3813bcedc92b4913c7e"
    target = next((item for item in session.blockedProductions
                   if item.recommendationId == recommendation_id), None)
    if not target or target.attentionStage != "AUDIO_MASTER" or target.resolutionStatus != "ARCHIVED":
        raise HTTPException(409, "The expected archived audio failure is no longer present.")
    supported_tts_failures = (
        "SynthesizeSpeechRequest' has no attribute 'TimepointType'",
        "unexpected keyword argument 'enable_time_pointing'",
    )
    if not any(signature in target.message for signature in supported_tts_failures):
        raise HTTPException(409, "The archived failure is not a recognized Google TTS SDK compatibility issue.")
    if not target.productionJobId or not target.recoveryJobId or target.recoveryJobId != session.recoveryJobId:
        raise HTTPException(409, "Production lineage is incomplete or belongs to another recovery campaign.")

    try:
        production = production_brief_job_store.get(target.productionJobId)
        if production.recommendation_id != recommendation_id:
            raise ValueError("Production recommendation mismatch")
        # Retrieve already-produced media through its known production lineage.
        media = media_studio_job_store.latest_for_production_brief(production.job_id)
        if not media:
            raise ValueError("No durable media job for archived production")
        assembly = final_assembly_job_store.latest_for_media_job(media.job_id)
        if not assembly or not _visual_master_ai_passed(assembly, media):
            raise ValueError("Latest visual master is not AI-approved and delivered")
        latest_audio = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
        if not latest_audio or latest_audio.stage != AudioFinishingJobStage.FAILED:
            raise ValueError("The latest audio is not the failed job")
        if not any(signature in (latest_audio.error or "") for signature in supported_tts_failures):
            raise ValueError("Audio job has a different error")
    except Exception as exc:
        raise HTTPException(409, f"Unable to verify archived production assets: {exc}") from exc

    repair_key = f"audio-infra-repair:{latest_audio.job_id}"
    if session.attempts.get(repair_key, 0):
        raise HTTPException(409, "This failed audio job has already received its one-time repair authorization.")
    new_session = session.model_copy(deep=True)
    new_session.attempts = {**session.attempts, repair_key: 1}
    new_session.blockedProductions = [item for item in session.blockedProductions
                                      if item.recommendationId != recommendation_id]
    # Reactivate the backend supervisor for this one archived production.
    # All existing completion history and unrelated archived exceptions stay
    # intact. When this production completes, normal campaign rules apply.
    new_session.status = "RUNNING"
    new_session.currentRecommendationId = recommendation_id
    new_session.currentTitle = target.title
    new_session.currentStartedAt = datetime.now(timezone.utc).isoformat()
    new_session.currentProductionJobId = production.job_id
    new_session.currentMediaJobId = media.job_id
    new_session.currentAssemblyJobId = assembly.job_id
    new_session.currentAudioJobId = latest_audio.job_id
    new_session.currentDeliveryPackageId = None
    new_session.currentPublishingDraftId = None
    new_session.currentPublicationId = None
    new_session.attentionStage = None
    new_session.message = "Authorized one TTS infrastructure repair; resuming from the AI-approved visual master."
    new_session.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(new_session, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot changed during repair. Refresh state before retrying.") from exc


@router.post(
    "/autopilot-state/repair-audio-quality",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def authorize_audio_quality_repair():
    """One strictly scoped audio-only retry for an AI delivery-review failure.

    The supervisor remains the sole job creator. This authorization cannot alter
    another production, skip AI review, or regenerate an approved visual master.
    """
    from datetime import datetime, timezone
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, "Autopilot session not found")
    session = record.session
    if session.executionOwner != "BACKEND" or session.scope != "CAMPAIGN":
        raise HTTPException(409, "Backend campaign ownership required")
    if session.status != "NEEDS_ATTENTION" or session.attentionStage != "FAILURE":
        raise HTTPException(409, "Campaign is not paused at delivery review")
    expected_recommendation = "replenished_f3813bcedc92b4913c7e"
    expected_assembly = "assembly_945578767b4d47d89cf657657efa850c"
    expected_audio = "audio_de77f1bbccbd4244a39afd0a3a5696ac"
    if session.currentRecommendationId != expected_recommendation or session.currentAssemblyJobId != expected_assembly or session.currentAudioJobId != expected_audio:
        raise HTTPException(409, "Production lineage differs; refusing to recover a different job")
    if any((session.currentDeliveryPackageId, session.currentPublishingDraftId, session.currentPublicationId)):
        raise HTTPException(409, "Delivery or publication already exists; inspect before retry")
    if "AI delivery reviewer recommends regeneration" not in (session.message or ""):
        raise HTTPException(409, "The failure is not the expected AI delivery review")
    try:
        assembly = final_assembly_job_store.get(expected_assembly)
        media = media_studio_job_store.get(session.currentMediaJobId)
        audio = audio_finishing_job_store.get(expected_audio)
        if not _visual_master_ai_passed(assembly, media):
            raise ValueError("Visual master has not passed verified AI approval")
        if audio.assembly_job_id != assembly.job_id or audio.stage != AudioFinishingJobStage.DELIVERED or not audio.result:
            raise ValueError("The source audio job is not a delivered master of this assembly")
        review = (audio.detail or {}).get("ai_audio_review") or {}
        if str(review.get("original_decision") or "").upper() != "REGENERATE":
            raise ValueError("Audio review is not an unresolved regeneration recommendation")
        latest = audio_finishing_job_store.latest_for_assembly_job(expected_assembly)
        if not latest or latest.job_id != audio.job_id:
            raise ValueError("A newer audio job already exists")
    except Exception as exc:
        raise HTTPException(409, f"Audio recovery eligibility check failed: {exc}") from exc
    key = f"audio-quality-repair:{expected_audio}"
    if session.attempts.get(key, 0):
        raise HTTPException(409, "This audio-quality repair was already authorized")
    new = session.model_copy(deep=True)
    new.attempts = {**session.attempts, key: 1}
    new.status = "RUNNING"
    new.attentionStage = None
    new.message = "Authorized one audio-only quality retry using the approved visual master; AI and QC gates remain enforced."
    now = datetime.now(timezone.utc).isoformat()
    new.updatedAt = now
    try:
        return autopilot_state_store.save(new, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot changed during repair; inspect before retrying") from exc


@router.post(
    "/autopilot-state/repair-soundtrack-mix",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def authorize_soundtrack_mix_repair():
    """Authorize one review-driven remix, never a new visual render."""
    from datetime import datetime, timezone
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, "Autopilot session not found")
    session = record.session
    if (session.executionOwner != "BACKEND" or session.scope != "CAMPAIGN"
            or session.status != "NEEDS_ATTENTION"
            or session.attentionStage not in {"FAILURE", "AUDIO_MASTER"}):
        raise HTTPException(409, "An eligible paused backend campaign is required")
    if any((session.currentDeliveryPackageId, session.currentPublishingDraftId,
            session.currentPublicationId)):
        raise HTTPException(409, "Delivery or publication already exists")
    if not all((session.currentRecommendationId, session.currentProductionJobId,
                session.currentMediaJobId, session.currentAssemblyJobId, session.currentAudioJobId)):
        raise HTTPException(409, "Current production lineage is incomplete")
    if not any(marker in (session.message or "") for marker in (
        "AI delivery reviewer recommends regeneration", "Audio review did not pass"
    )):
        raise HTTPException(409, "Current attention is not an unresolved audio-review failure")
    try:
        assembly = final_assembly_job_store.get(session.currentAssemblyJobId)
        media = media_studio_job_store.get(session.currentMediaJobId)
        audio = audio_finishing_job_store.get(session.currentAudioJobId)
        latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
        if not _visual_master_ai_passed(assembly, media):
            raise ValueError("Approved visual master could not be verified")
        if (not latest or latest.job_id != audio.job_id or audio.assembly_job_id != assembly.job_id
                or audio.stage != AudioFinishingJobStage.DELIVERED or not audio.result):
            raise ValueError("Audio master is not the latest delivered revision")
        review = (audio.detail or {}).get("ai_audio_review") or {}
        if str(review.get("original_decision") or "").upper() != "REGENERATE":
            raise ValueError("No unresolved audio regeneration recommendation")
        review_text = " ".join(map(str, review.get("issues") or [])) + " " + str(review.get("corrective_instruction") or "")
        if not any(term in review_text.lower() for term in ("music", "soundtrack", "genre", "acoustic", "vocal")):
            raise ValueError("Review does not identify a soundtrack or mix defect")
    except Exception as exc:
        raise HTTPException(409, f"Soundtrack repair eligibility failed: {exc}") from exc
    key = f"soundtrack-mix-repair:{audio.job_id}"
    if session.attempts.get(key, 0):
        raise HTTPException(409, "A soundtrack mix repair was already authorized for this audio version")
    new = session.model_copy(deep=True)
    # The existing supervisor quality-retry mechanism remains the sole job creator.
    quality_key = f"audio-quality-repair:{audio.job_id}"
    if session.attempts.get(quality_key, 0):
        raise HTTPException(409, "This audio version already consumed a quality retry")
    new.attempts = {**session.attempts, key: 1, quality_key: 1}
    new.status = "RUNNING"
    new.attentionStage = None
    new.message = "Authorized a soundtrack corrective remix; approved visual master preserved."
    new.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(new, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot changed during remix authorization") from exc


@router.post(
    "/autopilot-state/repair-speech-captions",
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def authorize_speech_caption_repair():
    """Authorize exactly one new audio master to regenerate voice and align captions.

    Keeps the visual master and uses normal supervisor ownership; never mutates
    an existing audio artifact or bypasses delivery review.
    """
    from datetime import datetime, timezone
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, "Autopilot session not found")
    session = record.session
    if (session.executionOwner != "BACKEND" or session.scope != "CAMPAIGN"
            or session.status != "NEEDS_ATTENTION" or session.attentionStage != "FAILURE"):
        raise HTTPException(409, "Caption repair requires a paused backend-owned campaign")
    if any((session.currentDeliveryPackageId, session.currentPublishingDraftId, session.currentPublicationId)):
        raise HTTPException(409, "Delivery or publishing already exists")
    if not all((session.currentRecommendationId, session.currentProductionJobId,
                session.currentMediaJobId, session.currentAssemblyJobId, session.currentAudioJobId)):
        raise HTTPException(409, "Current production lineage incomplete")
    if "audio-aligned captions" not in (session.message or "").lower() and "speech-verified" not in (session.message or "").lower():
        raise HTTPException(409, "Current failure is not an audio caption-alignment defect")
    try:
        media = media_studio_job_store.get(session.currentMediaJobId)
        assembly = final_assembly_job_store.get(session.currentAssemblyJobId)
        audio = audio_finishing_job_store.get(session.currentAudioJobId)
        latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
        if not _visual_master_ai_passed(assembly, media):
            raise ValueError("Visual master is not AI-approved")
        if not latest or latest.job_id != audio.job_id or audio.stage != AudioFinishingJobStage.DELIVERED:
            raise ValueError("Audio is not the latest delivered version")
        if audio.assembly_job_id != assembly.job_id or audio.production_brief_job_id != session.currentProductionJobId:
            raise ValueError("Audio lineage mismatch")
        if (audio.detail or {}).get("subtitle_alignment") in {"SPEECH_VERIFIED", "TTS_SSML_MARK", "SPEECH_VERIFIED_MIXED_METHODS"}:
            raise ValueError("Audio already has provider/speech-aligned captions")
    except Exception as exc:
        raise HTTPException(409, f"Caption repair verification failed: {exc}") from exc
    key = f"speech-caption-repair:{audio.job_id}"
    if session.attempts.get(key, 0):
        raise HTTPException(409, "Caption repair already authorized for this audio version")
    new = session.model_copy(deep=True)
    new.attempts = {**session.attempts, key: 1}
    new.status = "RUNNING"
    new.attentionStage = None
    new.message = "Authorized one voiceover-only regeneration with verified speech alignment; visual master preserved."
    new.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(new, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, "Autopilot changed during caption repair") from exc

@router.post(
    '/autopilot-state/realign-existing-narration',
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def realign_existing_narration():
    """One guarded repair using persisted narration stems, with no TTS or Veo calls.

    Runs recognition synchronously; caller should allow for STT latency.
    """
    from datetime import datetime, timezone
    from app.services.targeted_caption_recovery import (
        TargetedCaptionRecoveryError, build_caption_only_version,
    )
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, 'Autopilot session not found')
    s = record.session
    if (s.executionOwner != 'BACKEND' or s.scope != 'CAMPAIGN'
            or s.status != 'NEEDS_ATTENTION' or s.attentionStage != 'FAILURE'):
        raise HTTPException(409, 'Targeted caption realignment requires paused backend-owned campaign')
    if any((s.currentDeliveryPackageId, s.currentPublishingDraftId, s.currentPublicationId)):
        raise HTTPException(409, 'Delivery or publishing already exists')
    if not all((s.currentAudioJobId, s.currentAssemblyJobId, s.currentMediaJobId)):
        raise HTTPException(409, 'Production lineage incomplete')
    msg = (s.message or '').lower()
    if not any(x in msg for x in ('caption', 'subtitle', 'speech-verified', 'speech alignment')):
        raise HTTPException(409, 'Current failure is not caption related')
    assembly = final_assembly_job_store.get(s.currentAssemblyJobId)
    media = media_studio_job_store.get(s.currentMediaJobId)
    audio = audio_finishing_job_store.get(s.currentAudioJobId)
    if not _visual_master_ai_passed(assembly, media):
        raise HTTPException(409, 'Visual master must be AI approved')
    if (audio.assembly_job_id != assembly.job_id
            or audio.stage != AudioFinishingJobStage.DELIVERED):
        raise HTTPException(409, 'Audio lineage is not a delivered master')
    latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
    if not latest or latest.job_id != audio.job_id:
        raise HTTPException(409, 'The current audio is no longer the latest version')
    key = f'targeted-caption-realign:{audio.job_id}'
    if s.attempts.get(key, 0):
        raise HTTPException(409, 'Targeted caption repair already consumed or in progress')
    # Lock the grant under optimistic Firestore revision BEFORE any external STT call.
    claimed = s.model_copy(deep=True)
    claimed.attempts = {**s.attempts, key: 1}
    claimed.message = 'Targeted caption alignment in progress using persisted voice stems.'
    claimed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        reserved = autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed before caption repair') from exc
    try:
        corrected = build_caption_only_version(audio.job_id)
    except TargetedCaptionRecoveryError as exc:
        # Fail closed: retain original audio and paused session. One-time grant
        # stays consumed to avoid repeated billable recognition on double-click.
        raise HTTPException(409, detail={
            'message': str(exc), 'alignment_reports': exc.reports,
            'retry_consumed': True,
        }) from exc
    # Supervisor must review the newly versioned, still-unapproved audio master.
    current = autopilot_state_store.get()
    if (current is None or current.revision != reserved.revision
            or current.session.currentAudioJobId != audio.job_id):
        raise HTTPException(409, 'Audio version created but Autopilot changed; manual reconciliation required')
    resumed = current.session.model_copy(deep=True)
    resumed.status = 'RUNNING'
    resumed.attentionStage = None
    resumed.currentAudioJobId = corrected.job_id
    resumed.message = 'Speech-verified subtitles created from persisted stems; fresh AI audio and delivery reviews required.'
    resumed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(resumed, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed; corrected audio saved but not activated') from exc

@router.post(
    '/autopilot-state/realign-existing-narration-v2',
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def realign_existing_narration_v2():
    """One guarded repair using persisted narration stems, with no TTS or Veo calls.

    Runs recognition synchronously; caller should allow for STT latency.
    """
    from datetime import datetime, timezone
    from app.services.targeted_caption_recovery import (
        TargetedCaptionRecoveryError, build_caption_only_version,
    )
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, 'Autopilot session not found')
    s = record.session
    if (s.executionOwner != 'BACKEND' or s.scope != 'CAMPAIGN'
            or s.status != 'NEEDS_ATTENTION' or s.attentionStage != 'FAILURE'):
        raise HTTPException(409, 'Targeted caption realignment requires paused backend-owned campaign')
    if any((s.currentDeliveryPackageId, s.currentPublishingDraftId, s.currentPublicationId)):
        raise HTTPException(409, 'Delivery or publishing already exists')
    if not all((s.currentAudioJobId, s.currentAssemblyJobId, s.currentMediaJobId)):
        raise HTTPException(409, 'Production lineage incomplete')
    msg = (s.message or '').lower()
    if not any(x in msg for x in ('caption', 'subtitle', 'speech-verified', 'speech alignment')):
        raise HTTPException(409, 'Current failure is not caption related')
    assembly = final_assembly_job_store.get(s.currentAssemblyJobId)
    media = media_studio_job_store.get(s.currentMediaJobId)
    audio = audio_finishing_job_store.get(s.currentAudioJobId)
    if not _visual_master_ai_passed(assembly, media):
        raise HTTPException(409, 'Visual master must be AI approved')
    if (audio.assembly_job_id != assembly.job_id
            or audio.stage != AudioFinishingJobStage.DELIVERED):
        raise HTTPException(409, 'Audio lineage is not a delivered master')
    latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
    if not latest or latest.job_id != audio.job_id:
        raise HTTPException(409, 'The current audio is no longer the latest version')
    key = f'targeted-caption-realign-v2:{audio.job_id}'
    if s.attempts.get(key, 0):
        raise HTTPException(409, 'Targeted caption repair already consumed or in progress')
    # Lock the grant under optimistic Firestore revision BEFORE any external STT call.
    claimed = s.model_copy(deep=True)
    claimed.attempts = {**s.attempts, key: 1}
    claimed.message = 'Targeted caption alignment in progress using persisted voice stems.'
    claimed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        reserved = autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed before caption repair') from exc
    try:
        corrected = build_caption_only_version(audio.job_id)
    except TargetedCaptionRecoveryError as exc:
        # Fail closed: retain original audio and paused session. One-time grant
        # stays consumed to avoid repeated billable recognition on double-click.
        raise HTTPException(409, detail={
            'message': str(exc), 'alignment_reports': exc.reports,
            'retry_consumed': True,
        }) from exc
    # Supervisor must review the newly versioned, still-unapproved audio master.
    current = autopilot_state_store.get()
    if (current is None or current.revision != reserved.revision
            or current.session.currentAudioJobId != audio.job_id):
        raise HTTPException(409, 'Audio version created but Autopilot changed; manual reconciliation required')
    resumed = current.session.model_copy(deep=True)
    resumed.status = 'RUNNING'
    resumed.attentionStage = None
    resumed.currentAudioJobId = corrected.job_id
    resumed.message = 'Speech-verified subtitles created from persisted stems; fresh AI audio and delivery reviews required.'
    resumed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(resumed, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed; corrected audio saved but not activated') from exc


@router.post(
    '/autopilot-state/realign-existing-narration-v3',
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def realign_existing_narration_v3():
    """One guarded repair using persisted narration stems, with no TTS or Veo calls.

    Runs recognition synchronously; caller should allow for STT latency.
    """
    from datetime import datetime, timezone
    from app.services.targeted_caption_recovery import (
        TargetedCaptionRecoveryError, build_caption_only_version,
    )
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, 'Autopilot session not found')
    s = record.session
    if (s.executionOwner != 'BACKEND' or s.scope != 'CAMPAIGN'
            or s.status != 'NEEDS_ATTENTION' or s.attentionStage != 'FAILURE'):
        raise HTTPException(409, 'Targeted caption realignment requires paused backend-owned campaign')
    if any((s.currentDeliveryPackageId, s.currentPublishingDraftId, s.currentPublicationId)):
        raise HTTPException(409, 'Delivery or publishing already exists')
    if not all((s.currentAudioJobId, s.currentAssemblyJobId, s.currentMediaJobId)):
        raise HTTPException(409, 'Production lineage incomplete')
    msg = (s.message or '').lower()
    if not any(x in msg for x in ('caption', 'subtitle', 'speech-verified', 'speech alignment')):
        raise HTTPException(409, 'Current failure is not caption related')
    assembly = final_assembly_job_store.get(s.currentAssemblyJobId)
    media = media_studio_job_store.get(s.currentMediaJobId)
    audio = audio_finishing_job_store.get(s.currentAudioJobId)
    if not _visual_master_ai_passed(assembly, media):
        raise HTTPException(409, 'Visual master must be AI approved')
    if (audio.assembly_job_id != assembly.job_id
            or audio.stage != AudioFinishingJobStage.DELIVERED):
        raise HTTPException(409, 'Audio lineage is not a delivered master')
    latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
    if not latest or latest.job_id != audio.job_id:
        raise HTTPException(409, 'The current audio is no longer the latest version')
    key = f'targeted-caption-realign-v3:{audio.job_id}'
    if s.attempts.get(key, 0):
        raise HTTPException(409, 'Targeted caption repair already consumed or in progress')
    # Lock the grant under optimistic Firestore revision BEFORE any external STT call.
    claimed = s.model_copy(deep=True)
    claimed.attempts = {**s.attempts, key: 1}
    claimed.message = 'Targeted caption alignment in progress using persisted voice stems.'
    claimed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        reserved = autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed before caption repair') from exc
    try:
        corrected = build_caption_only_version(audio.job_id)
    except TargetedCaptionRecoveryError as exc:
        # Fail closed: retain original audio and paused session. One-time grant
        # stays consumed to avoid repeated billable recognition on double-click.
        raise HTTPException(409, detail={
            'message': str(exc), 'alignment_reports': exc.reports,
            'retry_consumed': True,
        }) from exc
    # Supervisor must review the newly versioned, still-unapproved audio master.
    current = autopilot_state_store.get()
    if (current is None or current.revision != reserved.revision
            or current.session.currentAudioJobId != audio.job_id):
        raise HTTPException(409, 'Audio version created but Autopilot changed; manual reconciliation required')
    resumed = current.session.model_copy(deep=True)
    resumed.status = 'RUNNING'
    resumed.attentionStage = None
    resumed.currentAudioJobId = corrected.job_id
    resumed.message = 'Speech-verified subtitles created from persisted stems; fresh AI audio and delivery reviews required.'
    resumed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(resumed, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed; corrected audio saved but not activated') from exc


@router.get(
    '/autopilot-state/caption-recovery-operation',
    dependencies=[Depends(require_tenant_context)],
)
async def caption_recovery_operation_status():
    """Read-only recovery status; never consumes retries or invokes STT."""
    record = autopilot_state_store.get()
    if not record:
        raise HTTPException(404, 'Autopilot session not found')
    s = record.session
    return {
        'revision': record.revision,
        'audio_job_id': s.currentAudioJobId,
        'operation': getattr(s, 'captionRecoveryOperation', None),
        'legacy_v3_claimed': bool(s.currentAudioJobId and s.attempts.get(f'targeted-caption-realign-v3:{s.currentAudioJobId}', 0)),
    }


@router.post(
    '/autopilot-state/resume-caption-recovery',
    response_model=AutopilotStateRecord,
    dependencies=[Depends(require_tenant_context)],
)
async def resume_caption_recovery():
    """Reconcile a stale v3 claim and retry once using immutable narration stems.

    A persisted lease prevents double submissions. No historical retry counters
    are cleared. No assets are regenerated unless all word offsets verify.
    """
    import logging
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from app.services.targeted_caption_recovery import (
        TargetedCaptionRecoveryError, build_caption_only_version,
    )
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed

    log = logging.getLogger(__name__)
    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, 'Autopilot session not found')
    s = record.session
    if (s.executionOwner != 'BACKEND' or s.scope != 'CAMPAIGN'
            or s.status != 'NEEDS_ATTENTION' or s.attentionStage != 'FAILURE'):
        raise HTTPException(409, 'Caption recovery requires paused backend-owned campaign')
    if any((s.currentDeliveryPackageId, s.currentPublishingDraftId, s.currentPublicationId)):
        raise HTTPException(409, 'Cannot repair after delivery or publication')
    if not all((s.currentAudioJobId, s.currentAssemblyJobId, s.currentMediaJobId)):
        raise HTTPException(409, 'Incomplete saved production lineage')
    if not any(x in (s.message or '').lower() for x in ('caption', 'subtitle', 'speech')):
        raise HTTPException(409, 'Current attention is unrelated to caption alignment')
    assembly = final_assembly_job_store.get(s.currentAssemblyJobId)
    media = media_studio_job_store.get(s.currentMediaJobId)
    audio = audio_finishing_job_store.get(s.currentAudioJobId)
    if not _visual_master_ai_passed(assembly, media):
        raise HTTPException(409, 'Visual master AI approval missing')
    if audio.assembly_job_id != assembly.job_id or audio.stage != AudioFinishingJobStage.DELIVERED:
        raise HTTPException(409, 'Current audio is not the approved delivery lineage')
    latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
    if latest is None or latest.job_id != audio.job_id:
        raise HTTPException(409, 'A newer audio version already exists; reconcile that version first')
    if not s.attempts.get(f'targeted-caption-realign-v3:{audio.job_id}', 0):
        raise HTTPException(409, 'No v3 attempt exists to reconcile')

    now = datetime.now(timezone.utc)
    old = getattr(s, 'captionRecoveryOperation', None) or {}
    if not isinstance(old, dict):
        old = {}
    if old.get('source_audio_job_id') == audio.job_id and old.get('status') == 'SUCCEEDED':
        raise HTTPException(409, 'Caption recovery already succeeded; reconcile existing assets')
    if old.get('source_audio_job_id') == audio.job_id and old.get('status') == 'RUNNING':
        try:
            expiry = datetime.fromisoformat(str(old['lease_expires_at']).replace('Z', '+00:00'))
        except (ValueError, KeyError, TypeError):
            raise HTTPException(409, 'Recovery lease is malformed; operator review required')
        if now < expiry:
            raise HTTPException(409, {'message': 'Caption recovery already running', 'operation': old})

    # Do not take over a v3 attempt until there has been ample time for the
    # original HTTP request and its persistence to complete.
    if (now - record.saved_at).total_seconds() < 300 and not old:
        raise HTTPException(409, 'Prior v3 claim is too recent; wait for reconciliation window')

    attempt_key = f'caption-recovery-managed:{audio.job_id}'
    attempt_no = s.attempts.get(attempt_key, 0)
    if attempt_no >= 2:
        raise HTTPException(409, 'Managed recovery attempts exhausted; inspect recorded failure')
    operation_id = f'caption_recovery_{uuid4().hex}'
    lease = now + timedelta(minutes=5)
    claimed = s.model_copy(deep=True)
    claimed.attempts = {**s.attempts, attempt_key: attempt_no + 1}
    claimed.captionRecoveryOperation = {
        'operation_id': operation_id,
        'source_audio_job_id': audio.job_id,
        'status': 'RUNNING',
        'attempt_number': attempt_no + 1,
        'started_at': now.isoformat(),
        'lease_expires_at': lease.isoformat(),
    }
    claimed.message = 'Caption recovery active under a five-minute lease; source media remains unchanged.'
    claimed.updatedAt = now.isoformat()
    try:
        reserved = autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Autopilot changed before caption recovery could be claimed') from exc

    try:
        corrected = build_caption_only_version(audio.job_id)
    except Exception as exc:
        failure = str(exc)[:450]
        reports = exc.reports if isinstance(exc, TargetedCaptionRecoveryError) else {}
        log.exception('Caption recovery %s failed', operation_id)
        current = autopilot_state_store.get()
        if (current and getattr(current.session, 'captionRecoveryOperation', None)
                and current.session.captionRecoveryOperation.get('operation_id') == operation_id):
            failed = current.session.model_copy(deep=True)
            failed.captionRecoveryOperation = {
                **failed.captionRecoveryOperation,
                'status': 'FAILED',
                'finished_at': datetime.now(timezone.utc).isoformat(),
                'error': failure,
                'alignment_reports': reports,
            }
            failed.message = 'Caption recovery failed; approved media untouched. Inspect operation diagnostics.'
            failed.updatedAt = datetime.now(timezone.utc).isoformat()
            try:
                autopilot_state_store.save(failed, expected_revision=current.revision)
            except Exception:
                log.exception('Unable to persist failed caption operation %s', operation_id)
        raise HTTPException(409 if isinstance(exc, TargetedCaptionRecoveryError) else 500,
                            {'message': failure, 'operation_id': operation_id,
                             'alignment_reports': reports, 'retry_consumed': True}) from exc

    current = autopilot_state_store.get()
    if (current is None or getattr(current.session, 'captionRecoveryOperation', None) is None
            or current.session.captionRecoveryOperation.get('operation_id') != operation_id
            or current.session.currentAudioJobId != audio.job_id):
        log.error('Caption recovery %s created %s but state changed', operation_id, corrected.job_id)
        raise HTTPException(409, {'message': 'Caption asset created; state changed. Reconcile before any retry',
                                  'created_audio_job_id': corrected.job_id})
    resumed = current.session.model_copy(deep=True)
    resumed.status = 'RUNNING'
    resumed.attentionStage = None
    resumed.currentAudioJobId = corrected.job_id
    resumed.captionRecoveryOperation = {
        **resumed.captionRecoveryOperation,
        'status': 'SUCCEEDED',
        'finished_at': datetime.now(timezone.utc).isoformat(),
        'created_audio_job_id': corrected.job_id,
    }
    resumed.message = 'Speech-verified captions created from saved stems; fresh AI reviews required.'
    resumed.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        return autopilot_state_store.save(resumed, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        log.error('Caption %s created audio %s but activation conflicted', operation_id, corrected.job_id)
        raise HTTPException(409, {'message': 'Corrected audio saved but state activation conflicted',
                                  'created_audio_job_id': corrected.job_id}) from exc


@router.post("/autopilot-state/diagnostics/forced-alignment")
async def diagnostic_forced_alignment(
    shot_number: int = 1,
    _: dict = Depends(require_platform_admin),
):
    """Platform-admin only; current tenant's paused production; zero persistent writes."""
    import asyncio
    from app.services.caption_alignment_observability import diagnose_active_caption_alignment
    # Blocking GCS, FFmpeg and WhisperX calls must not block the event loop.
    return await asyncio.to_thread(diagnose_active_caption_alignment, shot_number)


class AdminCaptionRepairRequest(BaseModel):
    reason: str
    expected_revision: int
    expected_audio_job_id: str
    confirm: str


def _admin_caption_repair_preflight(record, expected_audio_job_id: str):
    from app.services.autopilot_supervisor_service import _visual_master_ai_passed
    s = record.session
    if (s.executionOwner != 'BACKEND' or s.scope != 'CAMPAIGN'
            or s.status != 'NEEDS_ATTENTION' or s.attentionStage != 'FAILURE'):
        raise HTTPException(409, 'Requires paused backend-owned campaign with failure attention')
    if any((s.currentDeliveryPackageId, s.currentPublishingDraftId, s.currentPublicationId)):
        raise HTTPException(409, 'Delivery or publication exists; manual reconciliation required')
    if not all((s.currentAudioJobId, s.currentAssemblyJobId, s.currentMediaJobId)):
        raise HTTPException(409, 'Incomplete saved production lineage')
    if s.currentAudioJobId != expected_audio_job_id:
        raise HTTPException(409, 'Audio job differs from explicitly approved target')
    if not any(x in (s.message or '').lower() for x in ('caption', 'subtitle', 'speech')):
        raise HTTPException(409, 'Attention is unrelated to captions')
    old = getattr(s, 'captionRecoveryOperation', None) or {}
    if not isinstance(old, dict) or old.get('status') != 'FAILED' or old.get('source_audio_job_id') != expected_audio_job_id:
        raise HTTPException(409, 'Requires an existing failed managed recovery for this audio job')
    if s.attempts.get(f'caption-recovery-managed:{expected_audio_job_id}', 0) < 2:
        raise HTTPException(409, 'Managed recovery is not exhausted; admin repair is inappropriate')
    history = getattr(s, 'adminCaptionRepairHistory', None) or []
    if history:
        # A second repair for the same source is never implicitly allowed.
        if any(isinstance(h, dict) and h.get('source_audio_job_id') == expected_audio_job_id for h in history):
            raise HTTPException(409, 'An admin repair already exists for this audio job; reconcile it')
    assembly = final_assembly_job_store.get(s.currentAssemblyJobId)
    media = media_studio_job_store.get(s.currentMediaJobId)
    audio = audio_finishing_job_store.get(expected_audio_job_id)
    if not _visual_master_ai_passed(assembly, media):
        raise HTTPException(409, 'Visual master AI approval missing')
    if audio.assembly_job_id != assembly.job_id or audio.stage != AudioFinishingJobStage.DELIVERED:
        raise HTTPException(409, 'Audio is not delivered from the approved assembly')
    latest = audio_finishing_job_store.latest_for_assembly_job(assembly.job_id)
    if latest is None or latest.job_id != audio.job_id:
        raise HTTPException(409, 'A newer audio job exists; reconcile before repair')
    return audio


@router.get('/autopilot-state/admin-caption-repair', dependencies=[Depends(require_platform_admin)])
async def admin_caption_repair_status():
    """Read-only operation and historical managed retry information."""
    record = autopilot_state_store.get()
    if not record:
        raise HTTPException(404, 'Autopilot session missing')
    s = record.session
    return {
        'revision': record.revision,
        'status': s.status,
        'audio_job_id': s.currentAudioJobId,
        'managed_operation': getattr(s, 'captionRecoveryOperation', None),
        'managed_attempts': s.attempts.get(f'caption-recovery-managed:{s.currentAudioJobId}', 0),
        'admin_repair_history': getattr(s, 'adminCaptionRepairHistory', None) or [],
    }


@router.post('/autopilot-state/admin-caption-repair', dependencies=[Depends(require_platform_admin)])
async def admin_caption_repair(request: AdminCaptionRepairRequest,
                               claims: dict = Depends(require_platform_admin)):
    """A separate one-shot, auditable repair; never resets historical retries.

    CAS reservation precedes asset creation. On activation conflict, retain the
    created asset ID for operator reconciliation; never automatically try again.
    """
    import asyncio
    import logging
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4
    from app.services.targeted_caption_recovery import TargetedCaptionRecoveryError, build_caption_only_version

    log = logging.getLogger(__name__)
    reason = request.reason.strip()
    if not 20 <= len(reason) <= 500:
        raise HTTPException(422, 'Repair reason must be 20-500 characters')
    if request.confirm != 'AUTHORIZE_CAPTION_ONLY_REPAIR':
        raise HTTPException(422, 'Explicit repair confirmation required')
    record = autopilot_state_store.get()
    if not record:
        raise HTTPException(404, 'Autopilot session missing')
    if record.revision != request.expected_revision:
        raise HTTPException(409, 'Autopilot revision changed; fetch status again')
    audio = _admin_caption_repair_preflight(record, request.expected_audio_job_id)
    now = datetime.now(timezone.utc)
    repair_id = f'admin_caption_repair_{uuid4().hex}'
    history = list(getattr(record.session, 'adminCaptionRepairHistory', None) or [])
    operation = {
        'repair_id': repair_id,
        'source_audio_job_id': audio.job_id,
        'managed_recovery_operation_id': (record.session.captionRecoveryOperation or {}).get('operation_id'),
        'managed_attempts_at_authorization': record.session.attempts.get(f'caption-recovery-managed:{audio.job_id}', 0),
        'actor_uid': claims.get('uid'),
        'reason': reason,
        'status': 'RUNNING',
        'started_at': now.isoformat(),
        'lease_expires_at': (now + timedelta(minutes=5)).isoformat(),
    }
    claimed = record.session.model_copy(deep=True)
    claimed.adminCaptionRepairHistory = history + [operation]
    claimed.message = 'Administrator-authorized caption-only repair running; approved media preserved.'
    claimed.updatedAt = now.isoformat()
    try:
        autopilot_state_store.save(claimed, expected_revision=record.revision)
    except AutopilotStateConflictError as exc:
        raise HTTPException(409, 'Concurrent Autopilot update; no repair executed') from exc

    # Deliberately never retry after reservation. A stale RUNNING record requires
    # operator reconciliation, not automatic lease takeover.
    try:
        corrected = await asyncio.to_thread(build_caption_only_version, audio.job_id)
    except Exception as exc:
        reports = exc.reports if isinstance(exc, TargetedCaptionRecoveryError) else {}
        log.exception('Admin caption repair %s failed', repair_id)
        current = autopilot_state_store.get()
        if current and getattr(current.session, 'adminCaptionRepairHistory', None):
            updated = current.session.model_copy(deep=True)
            items = list(updated.adminCaptionRepairHistory)
            if items[-1].get('repair_id') == repair_id and items[-1].get('status') == 'RUNNING':
                items[-1] = {**items[-1], 'status': 'FAILED',
                             'finished_at': datetime.now(timezone.utc).isoformat(),
                             'error_code': 'CAPTION_VALIDATION_FAILED' if reports else 'REPAIR_EXECUTION_FAILED',
                             'alignment_reports': reports}
                updated.adminCaptionRepairHistory = items
                updated.message = 'Admin caption repair failed; existing approved assets retained.'
                updated.updatedAt = datetime.now(timezone.utc).isoformat()
                try:
                    autopilot_state_store.save(updated, expected_revision=current.revision)
                except AutopilotStateConflictError:
                    log.exception('Admin repair %s failure audit CAS conflict', repair_id)
        raise HTTPException(409 if reports else 500, {'repair_id': repair_id, 'status': 'FAILED',
                              'message': 'Repair failed; check admin repair status and backend logs',
                              'alignment_reports': reports}) from exc

    current = autopilot_state_store.get()
    if (current is None or current.session.currentAudioJobId != audio.job_id
            or current.session.status != 'NEEDS_ATTENTION'
            or current.session.attentionStage != 'FAILURE'
            or any((current.session.currentDeliveryPackageId, current.session.currentPublishingDraftId,
                    current.session.currentPublicationId))):
        log.error('Admin caption repair %s saved asset %s but lineage changed', repair_id, corrected.job_id)
        raise HTTPException(409, {'repair_id': repair_id, 'created_audio_job_id': corrected.job_id,
                                 'message': 'New caption asset exists; lineage changed. Reconcile manually.'})
    updated = current.session.model_copy(deep=True)
    items = list(getattr(updated, 'adminCaptionRepairHistory', None) or [])
    if not items or items[-1].get('repair_id') != repair_id or items[-1].get('status') != 'RUNNING':
        raise HTTPException(409, {'repair_id': repair_id, 'created_audio_job_id': corrected.job_id,
                                 'message': 'Repair record changed; reconcile saved asset manually'})
    items[-1] = {**items[-1], 'status': 'SUCCEEDED',
                 'created_audio_job_id': corrected.job_id,
                 'finished_at': datetime.now(timezone.utc).isoformat(),
                 'fresh_ai_review_required': True}
    updated.adminCaptionRepairHistory = items
    updated.currentAudioJobId = corrected.job_id
    updated.status = 'RUNNING'
    updated.attentionStage = None
    updated.message = 'Admin caption repair created verified SRT; fresh AI reviews required before delivery.'
    updated.updatedAt = datetime.now(timezone.utc).isoformat()
    try:
        saved = autopilot_state_store.save(updated, expected_revision=current.revision)
    except AutopilotStateConflictError as exc:
        log.error('Admin caption repair %s activation conflicted; asset %s', repair_id, corrected.job_id)
        raise HTTPException(409, {'repair_id': repair_id, 'created_audio_job_id': corrected.job_id,
                                 'message': 'Caption asset saved but activation conflicted; reconcile manually'}) from exc
    return {'repair_id': repair_id, 'status': 'SUCCEEDED', 'created_audio_job_id': corrected.job_id,
            'revision': saved.revision, 'fresh_ai_review_required': True,
            'historical_recovery_attempts_preserved': True}


class AdminVisualLineageReconcileRequest(BaseModel):
    expected_revision: int
    source_audio_job_id: str
    repaired_audio_job_id: str
    expected_visual_asset_id: str
    reason: str
    confirm: str


def _visual_lineage_reconcile_preflight(source_id: str, repaired_id: str, expected_id: str):
    """Check provenance against persisted jobs and immutable asset references."""
    from app.models.final_assembly import FinalAssemblyReviewStatus
    from app.models.audio_finishing import AudioFinishingReviewStatus
    try:
        source = audio_finishing_job_store.get(source_id)
        repaired = audio_finishing_job_store.get(repaired_id)
        assembly = final_assembly_job_store.get(repaired.assembly_job_id)
    except Exception as exc:
        raise HTTPException(409, 'Saved audio or assembly lineage unavailable') from exc
    if not assembly.result or assembly.result.review_status != FinalAssemblyReviewStatus.APPROVED:
        raise HTTPException(409, 'Visual assembly has not passed final approval')
    approved_id = assembly.result.final_video.asset_id
    if approved_id != expected_id or (source.detail or {}).get('source_visual_asset_id') != expected_id:
        raise HTTPException(409, 'Expected visual ID does not match approved source and assembly')
    if (source.assembly_job_id != repaired.assembly_job_id
            or repaired.detail.get('source_audio_job_id') != source.job_id
            or not repaired.detail.get('caption_only_recovery')
            or not repaired.detail.get('visual_master_preserved')):
        raise HTTPException(409, 'Repaired job does not have valid caption-only source lineage')
    if (source.result is None or repaired.result is None
            or source.result.delivery_video is None or repaired.result.delivery_video is None
            or source.result.delivery_video.asset_id != repaired.result.delivery_video.asset_id
            or source.result.delivery_video.gcs_uri != repaired.result.delivery_video.gcs_uri
            or not source.result.delivery_video.gcs_uri):
        raise HTTPException(409, 'Original and repaired delivery video artifact references differ')
    if (source.stage != AudioFinishingJobStage.DELIVERED
            or repaired.stage != AudioFinishingJobStage.DELIVERED
            or repaired.result.review_status != AudioFinishingReviewStatus.APPROVED
            or repaired.detail.get('subtitle_alignment') != 'SPEECH_VERIFIED'):
        raise HTTPException(409, 'Repaired version is not speech-verified and approved')
    if repaired.detail.get('source_visual_asset_id') not in (None, '', expected_id):
        raise HTTPException(409, 'Conflicting visual lineage already recorded')
    return source, repaired, assembly


@router.get('/autopilot-state/admin-visual-lineage-reconcile', dependencies=[Depends(require_platform_admin)])
async def admin_visual_lineage_reconcile_status(
    source_audio_job_id: str,
    repaired_audio_job_id: str,
    expected_visual_asset_id: str,
):
    """Read-only provenance and archive diagnostics; does not rerun QC."""
    record = autopilot_state_store.get()
    if record is None:
        raise HTTPException(404, 'Autopilot state unavailable')
    source, repaired, _ = _visual_lineage_reconcile_preflight(
        source_audio_job_id, repaired_audio_job_id, expected_visual_asset_id)
    blockers = [item.model_dump(mode='json') for item in record.session.blockedProductions
                if item.productionJobId == repaired.production_brief_job_id]
    return {
        'revision': record.revision,
        'autopilot_status': record.session.status,
        'source_audio_job_id': source.job_id,
        'repaired_audio_job_id': repaired.job_id,
        'approved_visual_asset_id': expected_visual_asset_id,
        'current_visual_asset_id': repaired.detail.get('source_visual_asset_id'),
        'already_reconciled': bool(repaired.detail.get('admin_visual_lineage_reconciliation')),
        'reconciliation': repaired.detail.get('admin_visual_lineage_reconciliation'),
        'blocked_productions': blockers,
        'autopilot_mutation_planned': False,
    }


@router.post('/autopilot-state/admin-visual-lineage-reconcile', dependencies=[Depends(require_platform_admin)])
async def admin_visual_lineage_reconcile(
    request: AdminVisualLineageReconcileRequest,
    claims: dict = Depends(require_platform_admin),
):
    """One-time metadata-only reconciliation; QC is rerun but archive is NOT reopened."""
    import asyncio
    from datetime import datetime, timezone
    from app.core.config import get_settings
    from app.services.delivery_qc_service import run_delivery_qc

    if request.confirm != 'AUTHORIZE_VISUAL_LINEAGE_RECONCILIATION':
        raise HTTPException(422, 'Explicit reconciliation confirmation required')
    if not 20 <= len(request.reason.strip()) <= 500:
        raise HTTPException(422, 'Reason must contain 20-500 characters')
    record = autopilot_state_store.get()
    if record is None or record.revision != request.expected_revision:
        raise HTTPException(409, 'Autopilot revision changed; refresh diagnostics')
    source, repaired, assembly = _visual_lineage_reconcile_preflight(
        request.source_audio_job_id, request.repaired_audio_job_id, request.expected_visual_asset_id)
    # Only the known archived technical QC failure can be reconciled here.
    matching = [x for x in record.session.blockedProductions
                if x.productionJobId == repaired.production_brief_job_id
                and x.attentionStage == 'DELIVERY_QC'
                and x.resolutionStatus == 'ARCHIVED'
                and x.resolutionReason == 'PRODUCTION_RETRIES_EXHAUSTED']
    history = getattr(record.session, 'adminCaptionRepairHistory', None) or []
    if not matching or not any(
        item.get('created_audio_job_id') == repaired.job_id and item.get('status') == 'SUCCEEDED'
        for item in history if isinstance(item, dict)
    ):
        raise HTTPException(409, 'Expected archived technical QC failure and authorized caption repair not found')
    # The campaign can resume on a different production after archival. Do not
    # prevent historical, metadata-only reconciliation in that case, but fail
    # closed if the target is part of the currently executing production.
    session = record.session
    if session.status not in ('COMPLETED', 'RUNNING'):
        raise HTTPException(409, 'Autopilot state is not safe for historical reconciliation')
    if (session.currentProductionJobId == repaired.production_brief_job_id
            or session.currentAudioJobId in (source.job_id, repaired.job_id)):
        raise HTTPException(409, 'Cannot reconcile an active production or audio job')
    if repaired.detail.get('admin_visual_lineage_reconciliation'):
        raise HTTPException(409, 'Lineage was already reconciled; inspect existing audit and QC')
    # Re-read before saving; no edits to the master media, subtitle, or Autopilot state.
    repaired.detail = {
        **(repaired.detail or {}),
        'source_visual_asset_id': request.expected_visual_asset_id,
        'admin_visual_lineage_reconciliation': {
            'source_audio_job_id': source.job_id,
            'visual_asset_id': request.expected_visual_asset_id,
            'assembly_job_id': assembly.job_id,
            'actor_uid': claims.get('uid'),
            'reason': request.reason.strip(),
            'performed_at': datetime.now(timezone.utc).isoformat(),
            'previous_visual_asset_id': None,
            'autopilot_reactivated': False,
        },
    }
    audio_finishing_job_store.save(repaired)
    try:
        report = await asyncio.to_thread(run_delivery_qc, repaired.job_id, get_settings())
    except Exception as exc:
        # Keep audited corrected provenance even if QC cannot complete. Operator can inspect/retry QC separately.
        raise HTTPException(409, {'message': 'Lineage saved; QC execution failed. Inspect saved job and retry QC using its normal endpoint.',
                                  'error': str(exc)[:400], 'repaired_audio_job_id': repaired.job_id}) from exc
    return {
        'reconciled': True,
        'audio_job_id': repaired.job_id,
        'source_visual_asset_id': request.expected_visual_asset_id,
        'qc_status': report.overall_status,
        'qc_ready_for_delivery': report.ready_for_delivery,
        'qc_failed_checks': [check.model_dump(mode='json') for check in report.checks if check.status == 'FAIL'],
        'autopilot_reactivated': False,
        'archive_preserved': True,
    }
