from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.final_assembly import FinalAssemblyJob
from app.services.final_assembly_job_service import (
    FinalAssemblyJobNotFoundError,
    final_assembly_job_store,
    render_final_assembly,
)
from app.services.media_studio_job_service import MediaStudioJobNotFoundError, media_studio_job_store

router = APIRouter(prefix="/api/v1/youtube", tags=["final-assembly"], dependencies=[Depends(require_tenant_context)])


@router.post(
    "/media-jobs/{media_job_id}/assembly-jobs",
    response_model=FinalAssemblyJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_assembly_job(
    media_job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        media_studio_job_store.get(media_job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    try:
        job = final_assembly_job_store.create(media_job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(render_final_assembly), job.job_id, settings)
    return job


@router.get("/media-jobs/{media_job_id}/assembly-jobs/latest", response_model=FinalAssemblyJob | None)
async def get_latest_assembly_job(media_job_id: str):
    return final_assembly_job_store.latest_for_media_job(media_job_id)


@router.get("/assembly-jobs/{job_id}", response_model=FinalAssemblyJob)
async def get_assembly_job(job_id: str):
    try:
        return final_assembly_job_store.get(job_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=404, detail="Final assembly job not found.")


@router.post("/assembly-jobs/{job_id}/approve", response_model=FinalAssemblyJob)
async def approve_assembly(job_id: str):
    try:
        return final_assembly_job_store.approve(job_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=404, detail="Final assembly job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/assembly-jobs/{job_id}/assets/{asset_id}")
async def get_assembly_asset(job_id: str, asset_id: str):
    try:
        path, mime = final_assembly_job_store.asset_path(job_id, asset_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=404, detail="Final assembly asset not found.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Final assembly file is unavailable.")
    return FileResponse(path, media_type=mime, filename=path.name)
