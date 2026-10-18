from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.audio_finishing import (
    AudioFinishingJob,
    AudioMixOptions,
    BackgroundMusicPreset,
    MusicSource,
    TrendingMusicCatalogResponse,
    YouTubeAudioLibraryCatalogResponse,
    YouTubeAudioLibraryLicenseType,
    YouTubeAudioLibraryTrack,
)
from app.services.audio_finishing_job_service import (
    AudioFinishingError,
    AudioFinishingJobNotFoundError,
    audio_finishing_job_store,
    build_music_preview,
    render_audio_finishing,
)
from app.services.final_assembly_job_service import FinalAssemblyJobNotFoundError, final_assembly_job_store
from app.services.production_brief_job_service import ProductionBriefJobNotFoundError
from app.services.trending_music_service import (
    TrendingMusicCatalogError,
    TrendingMusicTrackNotFoundError,
    trending_music_catalog,
)
from app.services.youtube_audio_library_service import (
    YouTubeAudioLibraryError,
    YouTubeAudioLibraryTrackNotFoundError,
    youtube_audio_library,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["audio-finishing"], dependencies=[Depends(require_tenant_context)])


@router.get("/music-catalog/youtube-audio-library", response_model=YouTubeAudioLibraryCatalogResponse)
async def get_youtube_audio_library(settings: Settings = Depends(get_settings)):
    try:
        return youtube_audio_library.list(settings)
    except YouTubeAudioLibraryError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post(
    "/music-catalog/youtube-audio-library/import",
    response_model=YouTubeAudioLibraryTrack,
    status_code=status.HTTP_201_CREATED,
)
async def import_youtube_audio_library_track(
    file: UploadFile = File(...),
    title: str = Form(...),
    artist: str = Form(""),
    genre: str = Form(""),
    mood: str = Form(""),
    license_type: YouTubeAudioLibraryLicenseType = Form(YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY),
    attribution_required: bool = Form(False),
    attribution_text: str = Form(""),
    source_url: str = Form(""),
    confirm_rights: bool = Form(...),
    settings: Settings = Depends(get_settings),
):
    if not confirm_rights:
        raise HTTPException(
            status_code=400,
            detail="Confirm that the file was downloaded from YouTube Audio Library and that you may use it for this video.",
        )
    try:
        max_bytes = settings.audio_youtube_library_max_upload_mb * 1024 * 1024
        file_bytes = await file.read(max_bytes + 1)
        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"Audio file exceeds the {settings.audio_youtube_library_max_upload_mb} MB import limit.",
            )
        return youtube_audio_library.import_track(
            settings,
            file_bytes=file_bytes,
            original_filename=file.filename or "track.mp3",
            title=title,
            artist=artist,
            genre=genre,
            mood=mood,
            license_type=license_type,
            attribution_required=attribution_required,
            attribution_text=attribution_text,
            source_url=source_url,
        )
    except YouTubeAudioLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    finally:
        await file.close()


@router.get("/music-catalog/youtube-audio-library/{track_id}/preview")
async def get_youtube_audio_library_preview(track_id: str, settings: Settings = Depends(get_settings)):
    try:
        path, mime = youtube_audio_library.preview_path(track_id, settings)
    except YouTubeAudioLibraryTrackNotFoundError:
        raise HTTPException(status_code=404, detail="YouTube Audio Library track not found.")
    except YouTubeAudioLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.delete("/music-catalog/youtube-audio-library/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_youtube_audio_library_track(track_id: str, settings: Settings = Depends(get_settings)):
    try:
        youtube_audio_library.delete(track_id, settings)
    except YouTubeAudioLibraryTrackNotFoundError:
        raise HTTPException(status_code=404, detail="YouTube Audio Library track not found.")
    except YouTubeAudioLibraryError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return None


@router.get("/music-catalog/trending", response_model=TrendingMusicCatalogResponse)
async def get_trending_music_catalog(settings: Settings = Depends(get_settings)):
    try:
        return trending_music_catalog.list(settings)
    except TrendingMusicCatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/music-catalog/trending/{track_id}/preview")
async def get_trending_music_preview(track_id: str, settings: Settings = Depends(get_settings)):
    try:
        path, mime = trending_music_catalog.preview_path(track_id, settings)
    except TrendingMusicTrackNotFoundError:
        raise HTTPException(status_code=404, detail="Trending music track not found.")
    except TrendingMusicCatalogError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post(
    "/assembly-jobs/{assembly_job_id}/audio-jobs",
    response_model=AudioFinishingJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_audio_job(
    assembly_job_id: str,
    options: AudioMixOptions,
    background_tasks: BackgroundTasks,
    settings: Settings = Depends(get_settings),
):
    try:
        final_assembly_job_store.get(assembly_job_id)
    except FinalAssemblyJobNotFoundError:
        raise HTTPException(status_code=404, detail="Final assembly job not found.")
    if options.music_enabled and options.music_source == MusicSource.TRENDING_LICENSED:
        try:
            trending_music_catalog.resolve(options.trending_track_id or "", settings)
        except TrendingMusicTrackNotFoundError:
            raise HTTPException(status_code=404, detail="Selected trending music track was not found.")
        except TrendingMusicCatalogError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    if (
        options.music_enabled
        and options.music_source == MusicSource.YOUTUBE_AUDIO_LIBRARY
        and options.youtube_audio_library_track_id
    ):
        # An explicit selection must resolve now. A missing id intentionally means
        # "auto-select a render-ready saved soundtrack"; render_audio_finishing()
        # owns that selection so the API does not reject a valid AUTO request.
        try:
            youtube_audio_library.resolve(options.youtube_audio_library_track_id, settings)
        except YouTubeAudioLibraryTrackNotFoundError:
            raise HTTPException(status_code=404, detail="Selected YouTube Audio Library track was not found.")
        except YouTubeAudioLibraryError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
    try:
        job = audio_finishing_job_store.create(assembly_job_id, options)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    background_tasks.add_task(tenant_bound(render_audio_finishing), job.job_id, settings)
    return job


@router.get("/assembly-jobs/{assembly_job_id}/music-previews/{preset}")
async def get_background_music_preview(
    assembly_job_id: str,
    preset: BackgroundMusicPreset,
    settings: Settings = Depends(get_settings),
):
    """Audition a music preset without creating or changing an audio master."""
    try:
        path, effective = build_music_preview(assembly_job_id, preset, settings)
    except (FinalAssemblyJobNotFoundError, ProductionBriefJobNotFoundError):
        raise HTTPException(status_code=404, detail="The approved visual or production brief is unavailable.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except AudioFinishingError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    filename = f"reviveai-{effective.value.lower()}-preview.wav"
    return FileResponse(
        path,
        media_type="audio/wav",
        filename=filename,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-ReviveAI-Music-Preset": effective.value,
        },
    )


@router.get("/assembly-jobs/{assembly_job_id}/audio-jobs", response_model=list[AudioFinishingJob])
async def list_audio_jobs(assembly_job_id: str):
    return audio_finishing_job_store.list_for_assembly_job(assembly_job_id)


@router.get("/assembly-jobs/{assembly_job_id}/audio-jobs/latest", response_model=AudioFinishingJob | None)
async def get_latest_audio_job(assembly_job_id: str):
    return audio_finishing_job_store.latest_for_assembly_job(assembly_job_id)


@router.get("/audio-jobs/{job_id}", response_model=AudioFinishingJob)
async def get_audio_job(job_id: str):
    try:
        return audio_finishing_job_store.get(job_id)
    except AudioFinishingJobNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")


@router.post("/audio-jobs/{job_id}/approve", response_model=AudioFinishingJob)
async def approve_audio_job(job_id: str):
    try:
        return audio_finishing_job_store.approve(job_id)
    except AudioFinishingJobNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/audio-jobs/{job_id}/assets/{asset_id}")
async def get_audio_asset(job_id: str, asset_id: str):
    try:
        path, mime = audio_finishing_job_store.asset_path(job_id, asset_id)
    except AudioFinishingJobNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing asset not found.")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio finishing file is unavailable.")
    return FileResponse(path, media_type=mime, filename=path.name)
