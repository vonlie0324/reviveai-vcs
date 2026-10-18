from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.models.delivery_qc import DeliveryQcReport
from app.services.delivery_qc_service import (
    DeliveryQcError,
    DeliveryQcReportNotFoundError,
    delivery_qc_store,
    acknowledge_delivery_qc_warnings,
    run_delivery_qc,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["delivery-qc"], dependencies=[Depends(require_tenant_context)])


@router.get("/audio-jobs/{job_id}/delivery-qc", response_model=DeliveryQcReport | None)
async def get_delivery_qc(job_id: str):
    try:
        return delivery_qc_store.get(job_id)
    except DeliveryQcReportNotFoundError:
        return None
    except DeliveryQcError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/audio-jobs/{job_id}/delivery-qc", response_model=DeliveryQcReport)
async def create_delivery_qc(job_id: str, settings: Settings = Depends(get_settings)):
    try:
        return run_delivery_qc(job_id, settings)
    except DeliveryQcReportNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")
    except (DeliveryQcError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


class QcAcknowledgmentRequest(BaseModel):
    report_id: str
    confirm_reviewed: bool


@router.post("/audio-jobs/{job_id}/delivery-qc/acknowledge", response_model=DeliveryQcReport)
async def acknowledge_delivery_qc(job_id: str, payload: QcAcknowledgmentRequest, request: Request):
    if not payload.confirm_reviewed:
        raise HTTPException(status_code=422, detail="Explicit creator confirmation is required.")
    claims = getattr(request.state, "user", None) or {}
    actor = str(claims.get("uid") or claims.get("user_id") or claims.get("sub") or "")
    try:
        return acknowledge_delivery_qc_warnings(job_id, payload.report_id, actor)
    except DeliveryQcReportNotFoundError:
        raise HTTPException(status_code=404, detail="QC report not found.")
    except (DeliveryQcError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
