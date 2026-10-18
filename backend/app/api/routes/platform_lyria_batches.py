"""Platform administrator Lyria pilot batches. No creator-facing generation endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.routes.platform_admin import require_platform_admin
from app.services.platform_lyria_batch_service import create_batch, generate_next, get_batch, list_batches, skip_failed_track

router = APIRouter(prefix="/api/v1/admin/music-batches", tags=["platform-music-batches"])


class BatchRequest(BaseModel):
    count: int = Field(ge=3, le=30)


@router.post("", status_code=201)
def new_batch(request: BatchRequest, claims: dict = Depends(require_platform_admin)):
    return create_batch(request.count, claims["uid"])


@router.get("")
def batches(_: dict = Depends(require_platform_admin)):
    return list_batches()


@router.get("/{batch_id}")
def batch_detail(batch_id: str, _: dict = Depends(require_platform_admin)):
    return get_batch(batch_id)


@router.post("/{batch_id}/generate-next")
def generate_next_track(batch_id: str, _: dict = Depends(require_platform_admin)):
    return generate_next(batch_id)


class SkipFailedRequest(BaseModel):
    reason: str = Field(min_length=12, max_length=1000)


@router.post("/{batch_id}/tracks/{index}/skip")
def skip_failed_attempt(
    batch_id: str,
    index: int,
    request: SkipFailedRequest,
    claims: dict = Depends(require_platform_admin),
):
    return skip_failed_track(batch_id, index, claims["uid"], request.reason)
