from __future__ import annotations

import asyncio
import logging
import os
import socket
from uuid import uuid4

from app.core.config import get_settings
from app.core.task_execution import internal_task_context
from app.core.tenant import tenant_namespace_context
from app.services.youtube_autonomy_queue import youtube_autonomy_queue
from app.services.youtube_publishing_service import youtube_publishing_service

logger = logging.getLogger(__name__)


class YouTubeAutonomyWorker:
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
            logger.info("YouTube autonomy uses Cloud Tasks; in-process loop not started")
            return
        if not self.settings.autopilot_autonomous_publish_enabled:
            logger.info("Autonomous YouTube worker is disabled")
            return
        if self._task and not self._task.done(): return
        self._stopping.clear()
        try:
            restored = youtube_autonomy_queue.bootstrap()
            logger.info("Autonomous YouTube queue bootstrap discovered %s tenant(s)", restored)
        except Exception:
            logger.exception("Autonomous YouTube queue bootstrap failed")
        self._task = asyncio.create_task(self._run_loop(), name="reviveai-youtube-autonomy")

    async def stop(self) -> None:
        self._stopping.set()
        if not self._task: return
        self._task.cancel()
        try: await self._task
        except asyncio.CancelledError: pass
        self._task = None

    async def _run_loop(self) -> None:
        while not self._stopping.is_set():
            try: await self.run_once()
            except asyncio.CancelledError: raise
            except Exception: logger.exception("Autonomous YouTube worker loop failed")
            try: await asyncio.wait_for(self._stopping.wait(), timeout=30.0)
            except asyncio.TimeoutError: pass

    async def run_namespace(self, namespace: str) -> dict:
        item = youtube_autonomy_queue.get_due(namespace)
        if item is None: return {"namespace": namespace, "result": "not_due"}
        acquired = False
        try:
            acquired = youtube_autonomy_queue.acquire_lease(namespace=namespace, owner=self._owner, lease_seconds=int(self.settings.youtube_autonomy_lease_seconds))
            if not acquired: return {"namespace": namespace, "result": "leased_elsewhere"}
            with internal_task_context():
                with tenant_namespace_context(namespace):
                    active, delay = await youtube_publishing_service.autonomy_tick()
            if active:
                youtube_autonomy_queue.defer(namespace, delay, reason="youtube-next-event")
            else:
                youtube_autonomy_queue.deactivate(namespace)
            return {"namespace": namespace, "result": "processed", "active": active, "next_delay_seconds": delay if active else None}
        except Exception:
            logger.exception("Autonomous YouTube task failed for tenant namespace %s", namespace)
            try: youtube_autonomy_queue.defer(namespace, 300.0, reason="error-retry")
            except Exception: pass
            return {"namespace": namespace, "result": "error"}
        finally:
            if acquired:
                try: youtube_autonomy_queue.release_lease(namespace=namespace, owner=self._owner)
                except Exception: logger.exception("Could not release YouTube autonomy lease")

    async def run_once(self) -> None:
        items = youtube_autonomy_queue.list_due(limit=int(self.settings.youtube_autonomy_max_tenants_per_tick))
        for item in items:
            if self._stopping.is_set(): return
            await self.run_namespace(item.namespace)


youtube_autonomy_worker = YouTubeAutonomyWorker()
