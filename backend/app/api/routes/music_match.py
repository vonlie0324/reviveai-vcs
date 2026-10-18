from fastapi import APIRouter, Depends, HTTPException

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.models.music_match import MusicMatchResult
from app.services.music_match_service import MusicMatchError, MusicMatchService, music_match_store

router = APIRouter(prefix="/api/v1/youtube", tags=["music-match"], dependencies=[Depends(require_tenant_context)])


@router.get("/assembly-jobs/{assembly_job_id}/music-match", response_model=MusicMatchResult | None)
async def get_latest_music_match(assembly_job_id: str):
    return music_match_store.get_latest(assembly_job_id)


@router.post("/assembly-jobs/{assembly_job_id}/music-match", response_model=MusicMatchResult)
async def generate_music_match(assembly_job_id: str, settings: Settings = Depends(get_settings)):
    service = MusicMatchService(settings)
    try:
        return await service.generate(assembly_job_id)
    except MusicMatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
