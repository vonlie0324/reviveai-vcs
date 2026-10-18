"""
Composable lifespan handler for FastAPI application.

Keeps soundtrack recovery lifecycle isolated from main app setup.
"""


class SoundtrackRecoveryMainLifespan:

    def __init__(
        self,
        recovery_lifespan,
        background_task=None,
    ):
        self.recovery_lifespan = recovery_lifespan
        self.background_task = background_task

    async def startup(self, app):
        await self.recovery_lifespan.startup(app)

        if self.background_task:
            await self.background_task.start()

    async def shutdown(self, app):
        if self.background_task:
            await self.background_task.stop()

        await self.recovery_lifespan.shutdown(app)
