from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.tenant import reset_current_tenant, set_current_tenant
from app.models.youtube import JobStage
from app.services.cloud_task_dispatcher import (
    CloudTaskDispatchError,
    cloud_task_dispatcher,
)
from app.services.event_driven_autonomy_service import event_driven_autonomy_service
from app.services.job_service import JobNotFoundError, job_store, run_analysis_job
from app.workers.autopilot_supervisor_worker import autopilot_supervisor_worker
from app.workers.youtube_autonomy_worker import youtube_autonomy_worker

router = APIRouter(prefix="/internal/tasks", tags=["internal-tasks"])


class TaskRequest(BaseModel):
    namespace: str = ""
    reason: str = ""


class AnalysisTaskRequest(TaskRequest):
    job_id: str = ""


def _authorize(authorization: str | None) -> None:
    if not get_settings().autopilot_event_driven_enabled:
        raise HTTPException(404, "Event-driven autonomy is disabled.")
    try:
        cloud_task_dispatcher.verify_oidc(authorization)
    except CloudTaskDispatchError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/autopilot")
async def autopilot_task(
    payload: TaskRequest,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    if not payload.namespace:
        raise HTTPException(400, "namespace is required")
    return await autopilot_supervisor_worker.run_namespace(payload.namespace)


@router.post("/youtube")
async def youtube_task(
    payload: TaskRequest,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    if not payload.namespace:
        raise HTTPException(400, "namespace is required")
    return await youtube_autonomy_worker.run_namespace(payload.namespace)


@router.post("/analysis")
async def analysis_task(
    payload: AnalysisTaskRequest,
    authorization: str | None = Header(default=None),
):
    """Run one durable channel-analysis job inside its authenticated tenant scope."""
    _authorize(authorization)

    namespace = payload.namespace.strip()
    job_id = payload.job_id.strip()

    if not namespace:
        raise HTTPException(400, "namespace is required")
    if not job_id:
        raise HTTPException(400, "job_id is required")

    tenant_token = set_current_tenant(namespace)
    try:
        try:
            job = job_store.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(404, "Analysis job not found.") from exc

        # Cloud Tasks is at-least-once. If the same delivery is retried after the
        # job already reached a terminal state, acknowledge it without repeating
        # external YouTube API work.
        if job.stage in {JobStage.COMPLETED, JobStage.FAILED}:
            return {
                "ok": True,
                "job_id": job.job_id,
                "stage": job.stage.value,
                "duplicate_delivery": True,
            }

        await run_analysis_job(job.job_id, job.url, get_settings())

        final_job = job_store.get(job.job_id)
        return {
            "ok": True,
            "job_id": final_job.job_id,
            "stage": final_job.stage.value,
            "duplicate_delivery": False,
        }
    finally:
        reset_current_tenant(tenant_token)


@router.post("/recovery-sweep")
async def recovery_sweep(
    payload: TaskRequest,
    authorization: str | None = Header(default=None),
):
    _authorize(authorization)
    return event_driven_autonomy_service.recovery_sweep()
