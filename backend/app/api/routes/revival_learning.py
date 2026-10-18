from fastapi import APIRouter, Depends, HTTPException

from app.core.firebase_auth import require_tenant_context
from app.services.revival_learning_service import (
    BootstrapRequest,
    LearningWorkspace,
    ObservationRequest,
    revival_learning_store,
)

router = APIRouter(prefix="/api/v1/youtube", tags=["revival-learning"], dependencies=[Depends(require_tenant_context)])


@router.post("/revival-learning/bootstrap", response_model=LearningWorkspace)
async def bootstrap_learning(request: BootstrapRequest):
    return revival_learning_store.bootstrap(request)


@router.get("/revival-learning/{program_id}", response_model=LearningWorkspace)
async def get_learning(program_id: str):
    result = revival_learning_store.get(program_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No learning workspace exists for this revival program.")
    return result


@router.post("/revival-learning/{program_id}/observations", response_model=LearningWorkspace)
async def add_observation(program_id: str, request: ObservationRequest):
    try:
        return revival_learning_store.add_observation(program_id, request.observation)
    except KeyError:
        raise HTTPException(status_code=404, detail="Bootstrap the revival learning workspace first.")
