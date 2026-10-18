from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.media_studio import AssetReviewRequest, MediaStudioJob, RegenerateAssetRequest
from app.models.production_brief import ProductionReviewStatus
from app.services.media_studio_job_service import (
    MediaStudioJobNotFoundError,
    generate_keyframes_for_job,
    generate_reference_for_job,
    media_studio_job_store,
    regenerate_keyframe_for_job,
    generate_video_clips_for_job,
    regenerate_video_clip_for_job,
    review_all_keyframe_fidelity_for_job,
    review_keyframe_fidelity_for_job,
)
from app.services.production_brief_job_service import ProductionBriefJobNotFoundError, production_brief_job_store

router = APIRouter(prefix="/api/v1/youtube", tags=["media-studio"], dependencies=[Depends(require_tenant_context)])


def _require_media_config(settings: Settings) -> None:
    if not settings.google_cloud_project:
        raise HTTPException(status_code=503, detail="Vertex AI is not configured. Set GOOGLE_CLOUD_PROJECT and authenticate with Application Default Credentials.")
    if not settings.image_generation_model:
        raise HTTPException(status_code=503, detail="IMAGE_GENERATION_MODEL is not configured.")


def _require_video_config(settings: Settings) -> None:
    _require_media_config(settings)
    if not settings.video_generation_model:
        raise HTTPException(status_code=503, detail="VIDEO_GENERATION_MODEL is not configured.")
    if settings.video_generation_model.startswith("veo-3.1") and settings.video_generation_location != "us-central1":
        raise HTTPException(
            status_code=503,
            detail=(
                "Veo 3.1 is available from the us-central1 Vertex AI endpoint. "
                f"ReviveAI is currently configured with VIDEO_GENERATION_LOCATION={settings.video_generation_location!r}. "
                "Set VIDEO_GENERATION_LOCATION=us-central1, restart the backend, and retry the failed shots. "
                "The Cloud Storage bucket location is a separate setting and does not determine the Veo model endpoint."
            ),
        )
    if not settings.video_output_gcs_uri:
        raise HTTPException(
            status_code=503,
            detail="M2B.2 requires VIDEO_OUTPUT_GCS_URI, for example gs://your-bucket/reviveai/videos. The authenticated account must be able to write to and read from that prefix.",
        )
    if not settings.video_output_gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=503, detail="VIDEO_OUTPUT_GCS_URI must start with gs://, for example gs://reviveai/videos.")


@router.post(
    "/production-brief-jobs/{production_job_id}/media-jobs",
    response_model=MediaStudioJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_media_job(
    production_job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        production_job = production_brief_job_store.get(production_job_id)
    except ProductionBriefJobNotFoundError:
        raise HTTPException(status_code=404, detail="Production brief job not found.")
    if production_job.result is None or production_job.result.review_status != ProductionReviewStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Approve the production brief before starting M2B media generation.")
    _require_media_config(settings)
    try:
        job = media_studio_job_store.create(production_job, settings)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(generate_reference_for_job), job.job_id, settings)
    return job


@router.get("/production-brief-jobs/{production_job_id}/media-jobs/latest", response_model=MediaStudioJob | None)
async def get_latest_media_job(production_job_id: str):
    return media_studio_job_store.latest_for_production_brief(production_job_id)


@router.get("/media-jobs/{job_id}", response_model=MediaStudioJob)
async def get_media_job(job_id: str):
    try:
        return media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")


@router.get("/media-jobs/{job_id}/assets/{asset_id}")
async def get_media_asset(job_id: str, asset_id: str):
    try:
        path, mime = media_studio_job_store.asset_path(job_id, asset_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Generated media asset not found.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Generated media file is unavailable.")
    return FileResponse(path, media_type=mime)


@router.post("/media-jobs/{job_id}/reference/approve", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def approve_reference(
    job_id: str,
    request: AssetReviewRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_media_config(settings)
    try:
        job = media_studio_job_store.approve_reference(job_id, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(generate_keyframes_for_job), job_id, settings)
    return job


@router.post("/media-jobs/{job_id}/reference/regenerate", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_reference(
    job_id: str,
    request: RegenerateAssetRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_media_config(settings)
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if job.result and job.result.reference_asset:
        job.result.reference_asset.review_note = request.note
        job.result.reference_approved = False
        job.result.keyframes = []
        job.result.approved_keyframes = 0
        job.result.fidelity_reviewed_keyframes = 0
        job.result.fidelity_passed_keyframes = 0
        job.result.animation_ready = False
    from app.models.media_studio import MediaStudioJobStage
    job.stage = MediaStudioJobStage.GENERATING_REFERENCE
    job.message = "Regenerating canonical character reference"
    media_studio_job_store.save(job)
    background_tasks.add_task(tenant_bound(generate_reference_for_job), job_id, settings)
    return media_studio_job_store.get(job_id)


@router.post("/media-jobs/{job_id}/keyframes/fidelity-review", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def review_all_keyframes(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_media_config(settings)
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if not job.result or not job.result.keyframes:
        raise HTTPException(status_code=409, detail="Generate storyboard keyframes before running fidelity review.")
    from app.models.media_studio import MediaStudioJobStage
    job.stage = MediaStudioJobStage.REVIEWING_KEYFRAME_FIDELITY
    job.message = "Reviewing storyboard fidelity for generated keyframes"
    media_studio_job_store.save(job)
    background_tasks.add_task(tenant_bound(review_all_keyframe_fidelity_for_job), job_id, settings)
    return media_studio_job_store.get(job_id)


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/fidelity-review", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def review_keyframe(
    job_id: str,
    shot_number: int,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_media_config(settings)
    try:
        job = media_studio_job_store.get(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    if not job.result or not any(a.shot_number == shot_number for a in job.result.keyframes):
        raise HTTPException(status_code=404, detail=f"Storyboard keyframe {shot_number} not found.")
    from app.models.media_studio import MediaStudioJobStage
    job.stage = MediaStudioJobStage.REVIEWING_KEYFRAME_FIDELITY
    job.message = f"Reviewing storyboard fidelity for shot {shot_number}"
    media_studio_job_store.save(job)
    background_tasks.add_task(tenant_bound(review_keyframe_fidelity_for_job), job_id, shot_number, settings)
    return media_studio_job_store.get(job_id)


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/accept-adaptation", response_model=MediaStudioJob)
async def accept_keyframe_adaptation(job_id: str, shot_number: int, request: AssetReviewRequest):
    try:
        return media_studio_job_store.accept_keyframe_adaptation(job_id, shot_number, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/approve", response_model=MediaStudioJob)
async def approve_keyframe(job_id: str, shot_number: int, request: AssetReviewRequest):
    try:
        return media_studio_job_store.approve_keyframe(job_id, shot_number, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/media-jobs/{job_id}/keyframes/{shot_number}/regenerate", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_keyframe(
    job_id: str,
    shot_number: int,
    request: RegenerateAssetRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_media_config(settings)
    try:
        job = media_studio_job_store.begin_keyframe_regeneration(job_id, shot_number, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(regenerate_keyframe_for_job), job_id, shot_number, settings, request.note)
    return job


@router.post("/media-jobs/{job_id}/animation/start", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def start_animation(
    job_id: str,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_video_config(settings)
    try:
        job = media_studio_job_store.begin_clip_generation(job_id)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(generate_video_clips_for_job), job_id, settings)
    return job


@router.post("/media-jobs/{job_id}/clips/{shot_number}/approve", response_model=MediaStudioJob)
async def approve_clip(job_id: str, shot_number: int, request: AssetReviewRequest):
    try:
        return media_studio_job_store.approve_clip(job_id, shot_number, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/media-jobs/{job_id}/clips/{shot_number}/regenerate", response_model=MediaStudioJob, status_code=status.HTTP_202_ACCEPTED)
async def regenerate_clip(
    job_id: str,
    shot_number: int,
    request: RegenerateAssetRequest,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    _require_video_config(settings)
    try:
        job = media_studio_job_store.begin_clip_regeneration(job_id, shot_number, request.note)
    except MediaStudioJobNotFoundError:
        raise HTTPException(status_code=404, detail="Media Studio job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(regenerate_video_clip_for_job), job_id, shot_number, settings, request.note)
    return job
