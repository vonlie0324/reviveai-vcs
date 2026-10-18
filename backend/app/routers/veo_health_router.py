from fastapi import APIRouter

from app.services.veo_operations_health_service import (
    VeoOperationsHealthService,
)

router = APIRouter(
    prefix="/health",
    tags=["health"],
)

service = VeoOperationsHealthService()


@router.get("/veo-worker")
def veo_worker_health():
    return service.get_status()
