from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.content_dna import ContentDnaJobStage
from app.models.recovery import RecoveryJob
from app.models.youtube import JobStage
from app.services.content_dna_job_service import ContentDnaJobNotFoundError, content_dna_job_store
from app.services.job_service import JobNotFoundError, job_store
from app.services.recovery_job_service import RecoveryJobNotFoundError, recovery_job_store, run_recovery_job


router = APIRouter(prefix="/api/v1/youtube", tags=["recovery-intelligence"], dependencies=[Depends(require_tenant_context)])


@router.post(
    "/content-dna-jobs/{content_dna_job_id}/recovery-jobs",
    response_model=RecoveryJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_recovery_job(
    content_dna_job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        dna_job = content_dna_job_store.get(content_dna_job_id)
    except ContentDnaJobNotFoundError:
        raise HTTPException(status_code=404, detail="Content DNA job not found.")

    if dna_job.stage != ContentDnaJobStage.COMPLETED or dna_job.result is None:
        raise HTTPException(
            status_code=409,
            detail="Complete Content DNA before building Recovery Intelligence.",
        )

    try:
        analysis_job = job_store.get(dna_job.analysis_job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Channel analysis job not found.")

    if analysis_job.stage != JobStage.COMPLETED or analysis_job.result is None:
        raise HTTPException(status_code=409, detail="The deterministic channel analysis is no longer available.")

    if not settings.google_cloud_project:
        raise HTTPException(
            status_code=503,
            detail="Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with Application Default Credentials.",
        )

    job = recovery_job_store.create(content_dna_job_id, dna_job.analysis_job_id)
    background_tasks.add_task(
        tenant_bound(run_recovery_job),
        job.job_id,
        analysis_job.result,
        dna_job.result,
        settings,
    )
    return job


@router.get("/analysis-jobs/{analysis_job_id}/recovery-jobs/latest", response_model=RecoveryJob)
async def get_latest_recovery_job(analysis_job_id: str):
    job = recovery_job_store.latest_for_analysis(analysis_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No saved Recovery Intelligence job found for this channel analysis.")
    return job


@router.get("/recovery-jobs/{job_id}", response_model=RecoveryJob)
async def get_recovery_job(job_id: str):
    try:
        return recovery_job_store.get(job_id)
    except RecoveryJobNotFoundError:
        raise HTTPException(status_code=404, detail="Recovery Intelligence job not found.")
