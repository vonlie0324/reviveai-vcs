from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status

from app.core.config import Settings, get_settings
from app.core.firebase_auth import require_tenant_context
from app.core.tenant import tenant_bound
from app.models.youtube import AnalysisJob, AnalyzeRequest
from app.services.cloud_task_dispatcher import cloud_task_dispatcher
from app.services.job_service import JobNotFoundError, job_store, run_analysis_job


router = APIRouter(
    prefix="/api/v1/youtube",
    tags=["youtube"],
    dependencies=[Depends(require_tenant_context)],
)


@router.post(
    "/analysis-jobs",
    response_model=AnalysisJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis_job(
    request: AnalyzeRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    """Create a durable channel-analysis job and dispatch its execution.

    Production/event-driven mode uses Cloud Tasks so execution is not tied to the
    lifetime of the browser request or the Cloud Run instance that created the job.

    Local/non-event-driven mode keeps the existing FastAPI BackgroundTasks behavior
    for developer convenience.
    """
    job = job_store.create(request.url)

    namespace = str(getattr(http_request.state, "tenant_id", "") or "").strip()
    if not namespace:
        job_store.fail(job.job_id, "Authenticated tenant context was not available for analysis dispatch.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not resolve the authenticated workspace for this analysis.",
        )

    if cloud_task_dispatcher.enabled:
        scheduled = cloud_task_dispatcher.schedule_analysis(
            namespace,
            job.job_id,
            reason="channel-analysis-created",
        )
        if not scheduled:
            message = "Channel analysis could not be dispatched to the background worker."
            job_store.fail(job.job_id, message)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"{message} Please try again.",
            )
    else:
        # Local/development fallback. In Cloud Run event-driven mode this branch is
        # intentionally avoided because BackgroundTasks is not a durable queue.
        background_tasks.add_task(
            tenant_bound(run_analysis_job),
            job.job_id,
            request.url,
            settings,
        )

    return job


@router.get("/analysis-jobs/index")
async def get_analysis_job_index():
    """Return the latest completed persisted analysis metadata for each channel.

    The payload is intentionally lightweight and tenant-scoped by the router's auth
    dependency. It lets a new browser/device rebuild the channel workspace without
    re-running YouTube analysis.
    """
    return job_store.completed_channel_index()


@router.get("/analysis-jobs/latest", response_model=AnalysisJob)
async def get_latest_analysis_job(channel_id: str = Query(..., min_length=1)):
    """Return the newest completed durable analysis for a channel."""
    try:
        return job_store.latest_completed_for_channel(channel_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="No completed channel analysis was found.")



@router.get("/analysis-jobs/{job_id}", response_model=AnalysisJob)
async def get_analysis_job(job_id: str):
    try:
        return job_store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
