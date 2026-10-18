import logging

from app.startup.veo_recovery_lifecycle import (
    VeoRecoveryLifecycle,
)

logger = logging.getLogger(__name__)


class VeoRuntimeManager:
    """
    Application lifecycle integration for Veo recovery services.
    """

    def __init__(self):
        self.lifecycle = VeoRecoveryLifecycle()

    async def startup(self):
        logger.info("Initializing Veo runtime services")
        await self.lifecycle.start()

    async def shutdown(self):
        logger.info("Stopping Veo runtime services")
        await self.lifecycle.stop()


veo_runtime_manager = VeoRuntimeManager()
