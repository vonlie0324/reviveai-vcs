import logging

from app.startup.veo_runtime_lifespan import (
    veo_runtime_manager,
)

logger = logging.getLogger(__name__)


async def veo_startup():
    """
    Called from application startup/lifespan.
    """
    logger.info("Starting Veo runtime manager")
    await veo_runtime_manager.startup()


async def veo_shutdown():
    """
    Called from application shutdown/lifespan.
    """
    logger.info("Stopping Veo runtime manager")
    await veo_runtime_manager.shutdown()
