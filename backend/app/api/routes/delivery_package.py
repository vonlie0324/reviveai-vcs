from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.core.firebase_auth import require_tenant_context
from app.core.config import Settings, get_settings
from app.models.delivery_package import DeliveryPackage
from app.services.delivery_package_service import (
    DeliveryPackageAssetNotFoundError,
    DeliveryPackageError,
    DeliveryPackageNotFoundError,
    create_delivery_package,
    delivery_package_store,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["delivery-package"], dependencies=[Depends(require_tenant_context)])




@router.get("/assembly-jobs/{assembly_job_id}/delivery-packages", response_model=list[DeliveryPackage])
async def list_assembly_delivery_packages(assembly_job_id: str):
    return delivery_package_store.list_for_assembly_job(assembly_job_id)


@router.get("/audio-jobs/{job_id}/delivery-packages", response_model=list[DeliveryPackage])
async def list_delivery_packages(job_id: str):
    try:
        return delivery_package_store.list_for_audio_job(job_id)
    except DeliveryPackageNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")


@router.get("/audio-jobs/{job_id}/delivery-packages/latest", response_model=DeliveryPackage | None)
async def get_latest_delivery_package(job_id: str):
    try:
        return delivery_package_store.latest_for_audio_job(job_id)
    except DeliveryPackageNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")


@router.post("/audio-jobs/{job_id}/delivery-packages", response_model=DeliveryPackage)
async def build_delivery_package(job_id: str, settings: Settings = Depends(get_settings)):
    try:
        return await run_in_threadpool(create_delivery_package, job_id, settings)
    except DeliveryPackageNotFoundError:
        raise HTTPException(status_code=404, detail="Audio finishing job not found.")
    except (DeliveryPackageError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/delivery-packages/{package_id}/download")
async def download_delivery_package(package_id: str):
    try:
        path, mime_type, filename = delivery_package_store.asset_path(package_id, "package_zip")
        return FileResponse(path, media_type=mime_type, filename=filename)
    except (DeliveryPackageNotFoundError, DeliveryPackageAssetNotFoundError):
        raise HTTPException(status_code=404, detail="Delivery package not found.")


@router.get("/delivery-packages/{package_id}/assets/{asset_key}")
async def get_delivery_package_asset(package_id: str, asset_key: str):
    try:
        path, mime_type, filename = delivery_package_store.asset_path(package_id, asset_key)
        return FileResponse(path, media_type=mime_type, filename=filename)
    except (DeliveryPackageNotFoundError, DeliveryPackageAssetNotFoundError):
        raise HTTPException(status_code=404, detail="Delivery package asset not found.")
