from fastapi import APIRouter, Depends

from app.core.firebase_auth import require_tenant_context
from app.services.resource_scheduler_service import global_resource_scheduler

router = APIRouter(prefix="/api/v1/youtube/resource-scheduler", tags=["resource-scheduler"], dependencies=[Depends(require_tenant_context)])


@router.get("")
async def get_resource_scheduler_status():
    """Return non-secret process-wide generation capacity for the command center."""
    return await global_resource_scheduler.snapshot()
