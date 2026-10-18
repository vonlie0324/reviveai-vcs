from fastapi import APIRouter, Depends, HTTPException, status

from app.core.firebase_auth import require_tenant_context
from app.models.revival_program import RevivalCadenceUpdateRequest, RevivalProgram
from app.services.revival_program_service import RevivalProgramNotFoundError, revival_program_store

router = APIRouter(prefix="/api/v1/youtube", tags=["revival-program"], dependencies=[Depends(require_tenant_context)])


@router.get("/recovery-jobs/{recovery_job_id}/revival-program", response_model=RevivalProgram)
async def get_revival_program(recovery_job_id: str):
    try:
        return revival_program_store.get_for_recovery(recovery_job_id)
    except RevivalProgramNotFoundError:
        raise HTTPException(status_code=404, detail="Revival program not found.")


@router.post(
    "/recovery-jobs/{recovery_job_id}/revival-program",
    response_model=RevivalProgram,
    status_code=status.HTTP_201_CREATED,
)
async def create_revival_program(recovery_job_id: str):
    try:
        return revival_program_store.create_for_recovery(recovery_job_id)
    except RevivalProgramNotFoundError:
        raise HTTPException(status_code=404, detail="Recovery Intelligence job not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.patch(
    "/recovery-jobs/{recovery_job_id}/revival-program/cadence",
    response_model=RevivalProgram,
)
async def update_revival_program_cadence(recovery_job_id: str, request: RevivalCadenceUpdateRequest):
    try:
        return revival_program_store.update_cadence(recovery_job_id, request.intensity)
    except RevivalProgramNotFoundError:
        raise HTTPException(status_code=404, detail="Revival program not found.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
