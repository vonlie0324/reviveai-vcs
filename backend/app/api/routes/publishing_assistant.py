from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.models.delivery_package import DeliveryPackage
from app.models.publishing_assistant import (
    PublishingDraft,
    PublishingDraftRegenerateRequest,
    PublishingDraftUpdateRequest,
)
from app.services.delivery_package_service import DeliveryPackageError, create_delivery_package
from app.services.publishing_assistant_service import (
    PublishingAssistantError,
    PublishingDraftNotFoundError,
    publishing_assistant_service,
    publishing_draft_store,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["publishing-assistant"], dependencies=[Depends(require_tenant_context)])


@router.get("/audio-jobs/{audio_job_id}/publishing-drafts", response_model=list[PublishingDraft])
async def list_publishing_drafts(audio_job_id: str):
    try:
        return publishing_draft_store.list_for_audio_job(audio_job_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")


@router.get("/audio-jobs/{audio_job_id}/publishing-drafts/latest", response_model=PublishingDraft | None)
async def latest_publishing_draft(audio_job_id: str):
    try:
        return publishing_draft_store.latest_for_audio_job(audio_job_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")


@router.post("/audio-jobs/{audio_job_id}/publishing-drafts", response_model=PublishingDraft)
async def create_publishing_draft(audio_job_id: str, settings: Settings = Depends(get_settings)):
    # Use request-time settings so env changes made before startup are honored consistently.
    service = publishing_assistant_service.__class__(settings)
    try:
        return await service.create(audio_job_id)
    except (PublishingAssistantError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.put("/publishing-drafts/{draft_id}", response_model=PublishingDraft)
async def update_publishing_draft(draft_id: str, request: PublishingDraftUpdateRequest, settings: Settings = Depends(get_settings)):
    service = publishing_assistant_service.__class__(settings)
    try:
        return service.update(draft_id, request.content)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Publishing draft not found.")
    except (PublishingAssistantError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/publishing-drafts/{draft_id}/regenerate", response_model=PublishingDraft)
async def regenerate_publishing_draft(draft_id: str, request: PublishingDraftRegenerateRequest, settings: Settings = Depends(get_settings)):
    service = publishing_assistant_service.__class__(settings)
    try:
        return await service.regenerate(draft_id, request.fields)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Publishing draft not found.")
    except (PublishingAssistantError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/publishing-drafts/{draft_id}/approve", response_model=PublishingDraft)
async def approve_publishing_draft(draft_id: str, settings: Settings = Depends(get_settings)):
    service = publishing_assistant_service.__class__(settings)
    try:
        return service.approve(draft_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Publishing draft not found.")
    except (PublishingAssistantError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/publishing-drafts/{draft_id}/delivery-package", response_model=DeliveryPackage)
async def add_publishing_to_delivery_package(draft_id: str, settings: Settings = Depends(get_settings)):
    try:
        draft = publishing_draft_store.get(draft_id)
    except PublishingDraftNotFoundError:
        raise HTTPException(status_code=404, detail="Publishing draft not found.")
    if draft.status.value != "APPROVED":
        raise HTTPException(status_code=409, detail="Approve the publishing draft before adding it to the delivery package.")
    try:
        return await run_in_threadpool(create_delivery_package, draft.audio_job_id, settings, draft)
    except (DeliveryPackageError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
