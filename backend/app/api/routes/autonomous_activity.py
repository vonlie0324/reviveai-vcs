from fastapi import APIRouter, Depends, Query

from app.core.firebase_auth import require_tenant_context
from app.models.autonomous_activity import AutonomousActivityEvent
from app.services.autonomous_activity_service import autonomous_activity_store

router = APIRouter(prefix="/api/v1/youtube", tags=["autonomous-activity"])


@router.get(
    "/autonomous-activity",
    response_model=list[AutonomousActivityEvent],
    dependencies=[Depends(require_tenant_context)],
)
async def autonomous_activity(limit: int = Query(default=200, ge=1, le=1000)):
    return autonomous_activity_store.list(limit=limit)
