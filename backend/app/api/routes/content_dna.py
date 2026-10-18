from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.content_dna import ContentDnaJob
from app.models.youtube import JobStage
from app.services.content_dna_job_service import (
    ContentDnaJobNotFoundError,
    content_dna_job_store,
    run_content_dna_job,
)
from app.services.job_service import JobNotFoundError, job_store


router = APIRouter(prefix="/api/v1/youtube", tags=["content-dna"], dependencies=[Depends(require_tenant_context)])


@router.post(
    "/analysis-jobs/{analysis_job_id}/content-dna-jobs",
    response_model=ContentDnaJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_content_dna_job(
    analysis_job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        analysis_job = job_store.get(analysis_job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Channel analysis job not found.")

    if analysis_job.stage != JobStage.COMPLETED or analysis_job.result is None:
        raise HTTPException(
            status_code=409,
            detail="Complete the deterministic channel analysis before building Content DNA.",
        )

    if not settings.google_cloud_project:
        raise HTTPException(
            status_code=503,
            detail=(
                "Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT in backend/.env, enable Vertex AI, "
                "and authenticate with Application Default Credentials."
            ),
        )

    total_videos = len(analysis_job.result.videos)
    if settings.content_dna_max_videos:
        total_videos = min(total_videos, settings.content_dna_max_videos)

    job = content_dna_job_store.create(analysis_job_id, total_videos)
    background_tasks.add_task(
        tenant_bound(run_content_dna_job),
        job.job_id,
        analysis_job.result,
        settings,
    )
    return job


@router.get("/analysis-jobs/{analysis_job_id}/content-dna-jobs/latest", response_model=ContentDnaJob)
async def get_latest_content_dna_job(analysis_job_id: str):
    job = content_dna_job_store.latest_for_analysis(analysis_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No saved Content DNA job found for this channel analysis.")
    return job


@router.get("/content-dna-jobs/{job_id}", response_model=ContentDnaJob)
async def get_content_dna_job(job_id: str):
    try:
        return content_dna_job_store.get(job_id)
    except ContentDnaJobNotFoundError:
        raise HTTPException(status_code=404, detail="Content DNA job not found.")
