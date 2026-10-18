from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.content_dna import ContentDnaJobStage
from app.models.production_brief import (
    ProductionBriefHistoryEntry,
    ProductionBriefJob,
    ProductionBriefRequest,
    ProductionBriefRetryRequest,
)
from app.models.recovery import RecoveryJobStage
from app.models.youtube import JobStage
from app.services.content_dna_job_service import ContentDnaJobNotFoundError, content_dna_job_store
from app.services.job_service import JobNotFoundError, job_store
from app.services.production_brief_job_service import (
    ProductionBriefJobNotFoundError,
    production_brief_job_store,
    run_production_brief_job,
)
from app.services.recovery_job_service import RecoveryJobNotFoundError, recovery_job_store
from app.services.production_recommendation_eligibility import authoritative_history, is_eligible


router = APIRouter(prefix="/api/v1/youtube", tags=["production-brief"], dependencies=[Depends(require_tenant_context)])


def _require_vertex(settings: Settings) -> None:
    if not settings.google_cloud_project:
        raise HTTPException(
            status_code=503,
            detail="Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with Application Default Credentials.",
        )


@router.post(
    "/recovery-jobs/{recovery_job_id}/production-brief-jobs",
    response_model=ProductionBriefJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_production_brief_job(
    recovery_job_id: str,
    request: ProductionBriefRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        recovery_job = recovery_job_store.get(recovery_job_id)
    except RecoveryJobNotFoundError:
        raise HTTPException(status_code=404, detail="Recovery Intelligence job not found.")

    if recovery_job.stage != RecoveryJobStage.COMPLETED or recovery_job.result is None:
        raise HTTPException(status_code=409, detail="Complete Recovery Intelligence before creating a production brief.")

    recommendation = next(
        (item for item in recovery_job.result.recommendations if item.recommendation_id == request.recommendation_id),
        None,
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Selected recovery recommendation was not found.")

    try:
        dna_job = content_dna_job_store.get(recovery_job.content_dna_job_id)
    except ContentDnaJobNotFoundError:
        raise HTTPException(status_code=404, detail="Content DNA job not found.")
    if dna_job.stage != ContentDnaJobStage.COMPLETED or dna_job.result is None:
        raise HTTPException(status_code=409, detail="Completed Content DNA is required for production planning.")

    try:
        analysis_job = job_store.get(recovery_job.analysis_job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Channel analysis job not found.")
    if analysis_job.stage != JobStage.COMPLETED or analysis_job.result is None:
        raise HTTPException(status_code=409, detail="The deterministic channel analysis is no longer available.")

    # Validate again at creation time; stale browser lists must not create
    # duplicates. Includes all legacy, failed, paused, and completed briefs.
    channel_id = analysis_job.result.channel.channel_id
    try:
        existing = authoritative_history(channel_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to verify production history. New production is temporarily disabled to prevent duplicates.") from exc
    if not is_eligible(recommendation, recovery_job_id, existing):
        raise HTTPException(status_code=409, detail="This idea has already entered production. Open the existing production instead.")

    _require_vertex(settings)

    job = production_brief_job_store.create(
        recovery_job_id=recovery_job_id,
        content_dna_job_id=recovery_job.content_dna_job_id,
        analysis_job_id=recovery_job.analysis_job_id,
        channel_id=analysis_job.result.channel.channel_id,
        channel_title=analysis_job.result.channel.title,
        recommendation=recommendation,
        recovery_generated_at=recovery_job.result.generated_at,
        fidelity_mode=request.fidelity_mode,
    )
    background_tasks.add_task(
        tenant_bound(run_production_brief_job),
        job.job_id,
        analysis_job.result,
        dna_job.result,
        job.source_snapshot,
        settings,
        request.fidelity_mode,
    )
    return job


@router.post(
    "/production-brief-jobs/{job_id}/retry",
    response_model=ProductionBriefJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_production_brief_job(
    job_id: str,
    request: ProductionBriefRetryRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Retry from the immutable source snapshot, not the current M1D plan."""
    try:
        source_job = production_brief_job_store.get(job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")

    try:
        dna_job = content_dna_job_store.get(source_job.content_dna_job_id)
    except ContentDnaJobNotFoundError:
        raise HTTPException(status_code=404, detail="The source Content DNA job is no longer available.")
    if dna_job.stage != ContentDnaJobStage.COMPLETED or dna_job.result is None:
        raise HTTPException(status_code=409, detail="Completed source Content DNA is required to retry this brief.")

    try:
        analysis_job = job_store.get(source_job.analysis_job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="The source channel analysis job is no longer available.")
    if analysis_job.stage != JobStage.COMPLETED or analysis_job.result is None:
        raise HTTPException(status_code=409, detail="The source deterministic channel analysis is no longer available.")

    _require_vertex(settings)
    fidelity_mode = request.fidelity_mode or source_job.fidelity_mode
    job = production_brief_job_store.create_from_snapshot(source_job, fidelity_mode=fidelity_mode)
    background_tasks.add_task(
        tenant_bound(run_production_brief_job),
        job.job_id,
        analysis_job.result,
        dna_job.result,
        job.source_snapshot,
        settings,
        fidelity_mode,
    )
    return job


@router.get("/production-brief-jobs/{job_id}", response_model=ProductionBriefJob)
async def get_production_brief_job(job_id: str):
    try:
        return production_brief_job_store.get(job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")


@router.get("/production-brief-history", response_model=List[ProductionBriefHistoryEntry])
async def get_production_brief_history(
    channel_id: Optional[str] = Query(default=None),
    analysis_job_id: Optional[str] = Query(default=None),
):
    if not channel_id and not analysis_job_id:
        raise HTTPException(status_code=400, detail="Provide channel_id or analysis_job_id.")
    return production_brief_job_store.list_history(channel_id=channel_id, analysis_job_id=analysis_job_id)


@router.post("/production-brief-jobs/{job_id}/approve", response_model=ProductionBriefJob)
async def approve_production_brief(job_id: str):
    try:
        return production_brief_job_store.approve(job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/production-brief-jobs/{job_id}/accept-adaptation", response_model=ProductionBriefJob)
async def accept_production_brief_adaptation(job_id: str):
    try:
        return production_brief_job_store.accept_adaptation(job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
