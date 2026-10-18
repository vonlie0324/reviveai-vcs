import asyncio
import logging

from app.startup.veo_recovery_startup import (
    start_veo_recovery_worker,
)

logger = logging.getLogger(__name__)


class VeoRecoveryLifecycle:
    """
    Manages recovery worker startup and graceful shutdown.
    """

    def __init__(self):
        self.task = None
        self.shutdown_event = asyncio.Event()

    async def start(self):
        logger.info("Starting Veo recovery worker")

        self.task = asyncio.create_task(
            start_veo_recovery_worker()
        )

    async def stop(self):
        logger.info("Stopping Veo recovery worker")

        self.shutdown_event.set()

        if self.task:
            self.task.cancel()

            try:
                await self.task
            except asyncio.CancelledError:
                pass
