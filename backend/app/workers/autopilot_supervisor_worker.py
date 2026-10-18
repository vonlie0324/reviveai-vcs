from __future__ import annotations

import asyncio
import logging
import os
import socket
from uuid import uuid4

from app.core.config import get_settings
from app.core.task_execution import internal_task_context
from app.core.tenant import tenant_namespace_context
from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue
from app.services.autopilot_side_effect_fence import supervisor_lease_scope
from app.services.autopilot_supervisor_service import autopilot_supervisor_service

logger = logging.getLogger(__name__)


class AutopilotSupervisorWorker:
    """Autopilot executor.

    v3.5 keeps the old loop as a safe fallback. In event-driven mode the loop is not
    started; Cloud Tasks calls run_namespace() for one due tenant at a time.
    """

    def __init__(self):
        self.settings = get_settings()
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()
        self._owner = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:10]}"

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    async def start(self) -> None:
        if self.settings.autopilot_event_driven_enabled:
            logger.info("Headless Autopilot uses Cloud Tasks; in-process loop not started")
            return
        if not self.settings.autopilot_backend_supervisor_enabled:
            logger.info("Headless Autopilot supervisor is disabled")
            return
        if self._task and not self._task.done(): return
        self._stopping.clear()
        try:
            restored = autopilot_supervisor_queue.bootstrap_from_persisted_states()
            logger.info("Headless Autopilot queue bootstrap discovered %s persisted session(s)", restored)
        except Exception:
            logger.exception("Headless Autopilot queue bootstrap failed")
        self._task = asyncio.create_task(self._run_loop(), name="reviveai-autopilot-supervisor")
        logger.info("Headless Autopilot supervisor started")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task:
            self._task.cancel()
            try: await self._task
            except asyncio.CancelledError: pass
            self._task = None
        await autopilot_supervisor_service.shutdown()

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try: await self.run_once()
            except asyncio.CancelledError: raise
            except Exception: logger.exception("Headless Autopilot supervisor loop failed")
            try: await asyncio.wait_for(self._stopping.wait(), timeout=float(self.settings.autopilot_supervisor_interval_seconds))
            except asyncio.TimeoutError: pass

    async def _renew_until_stopped(self, namespace: str, owner: str, stop: asyncio.Event, lost: asyncio.Event) -> None:
        """Maintain supervisor lease while awaited background jobs are active."""
        lease_seconds = max(10, int(self.settings.autopilot_supervisor_lease_seconds))
        interval = max(2, min(30, lease_seconds // 3))
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                renewed = await asyncio.to_thread(
                    autopilot_supervisor_queue.renew_lease,
                    namespace=namespace, owner=owner, lease_seconds=lease_seconds,
                )
            except Exception:
                logger.exception("Could not renew Autopilot supervisor lease: %s", namespace)
                renewed = False
            if not renewed:
                lost.set()
                logger.error("Autopilot supervisor lease lost: %s", namespace)
                return

    async def run_namespace(self, namespace: str) -> dict:
        item = autopilot_supervisor_queue.get_due(namespace)
        if item is None:
            return {"namespace": namespace, "result": "not_due"}
        include_waiting_final = bool(self.settings.autopilot_autonomous_final_approval_enabled)
        include_continuous = bool(self.settings.autopilot_continuous_campaign_enabled)
        invocation_owner = f"{self._owner}:{uuid4().hex}"
        acquired = False
        lease_stop = asyncio.Event()
        lease_lost = asyncio.Event()
        renewal_task = None
        try:
            acquired = autopilot_supervisor_queue.acquire_lease(
                namespace=namespace, owner=invocation_owner,
                lease_seconds=int(self.settings.autopilot_supervisor_lease_seconds),
                include_waiting_final_approval=include_waiting_final,
                include_waiting_learning=include_continuous,
                include_completed=include_continuous,
            )
            if not acquired: return {"namespace": namespace, "result": "leased_elsewhere"}
            if self.settings.autopilot_event_driven_enabled:
                renewal_task = asyncio.create_task(
                    self._renew_until_stopped(namespace, invocation_owner, lease_stop, lease_lost))
            # Fail closed if maintenance arrived between acquisition and the first step.
            if not await asyncio.to_thread(autopilot_supervisor_queue.assert_supervisor_lease,
                                           namespace=namespace, owner=invocation_owner):
                raise RuntimeError("Supervisor lease invalid before advance")
            with internal_task_context():
                with supervisor_lease_scope(namespace, invocation_owner):
                  with tenant_namespace_context(namespace):
                      record = await autopilot_supervisor_service.advance_current_tenant()
                      if self.settings.autopilot_event_driven_enabled:
                          await autopilot_supervisor_service.drain_spawned()
            # Do not schedule follow-up work using an expired or superseded lease.
            if not await asyncio.to_thread(autopilot_supervisor_queue.assert_supervisor_lease,
                                           namespace=namespace, owner=invocation_owner):
                lease_lost.set()
            if lease_lost.is_set():
                raise RuntimeError("Supervisor lease lost during execution")
            if record is None:
                scheduled = autopilot_supervisor_queue.defer(namespace, 30, reason="state-unavailable")
                if self.settings.autopilot_event_driven_enabled and not scheduled:
                    raise RuntimeError("Could not dispatch state-unavailable retry")
                return {"namespace": namespace, "result": "state-unavailable"}
            if autopilot_supervisor_service._status_is_actionable(record.session):
                # Wake calculation reads tenant-scoped publication records. Keep
                # the namespace active after advance_current_tenant() returns.
                with tenant_namespace_context(namespace):
                    delay = autopilot_supervisor_service.next_wake_delay(record)
                logger.info(
                    "Autopilot next wake namespace=%s revision=%s status=%s delay_seconds=%.1f",
                    namespace,
                    record.revision,
                    record.session.status,
                    delay,
                )
                scheduled = autopilot_supervisor_queue.defer(
                    namespace,
                    delay,
                    reason=f"status:{record.session.status}",
                )
                if self.settings.autopilot_event_driven_enabled and not scheduled:
                    raise RuntimeError("Could not dispatch next Autopilot wake-up")
            logger.info("Autopilot task revision=%s status=%s", record.revision, record.session.status)
            return {"namespace": namespace, "result": "advanced", "revision": record.revision, "status": record.session.status}
        except Exception:
            logger.exception("Headless Autopilot task failed for tenant namespace %s", namespace)
            try:
                deferred = autopilot_supervisor_queue.defer(namespace, 60, reason="error-retry")
            except Exception:
                logger.exception("Could not schedule durable Autopilot retry: %s", namespace)
                raise
            if not deferred:
                raise RuntimeError("Cloud Tasks retry scheduling did not confirm dispatch")
            return {"namespace": namespace, "result": "retry_scheduled"}
        finally:
            lease_stop.set()
            if renewal_task is not None:
                await renewal_task
            if acquired:
                try: autopilot_supervisor_queue.release_lease(namespace=namespace, owner=invocation_owner)
                except Exception: logger.exception("Could not release Autopilot supervisor lease")

    async def run_once(self) -> None:
        include_waiting_final = bool(self.settings.autopilot_autonomous_final_approval_enabled)
        include_continuous = bool(self.settings.autopilot_continuous_campaign_enabled)
        items = autopilot_supervisor_queue.list_running(
            limit=int(self.settings.autopilot_supervisor_max_sessions_per_tick),
            include_waiting_final_approval=include_waiting_final,
            include_waiting_learning=include_continuous,
            include_completed=include_continuous,
        )
        for item in items:
            if self._stopping.is_set(): return
            await self.run_namespace(item.namespace)


autopilot_supervisor_worker = AutopilotSupervisorWorker()
