"""
Bootstrap runtime dependencies for soundtrack recovery scheduler.
"""


class SoundtrackRecoveryRuntimeBootstrap:

    def __init__(
        self,
        scheduler_loop,
        settings,
    ):
        self.scheduler_loop = scheduler_loop
        self.settings = settings

    async def start(self):
        if not self.settings.enabled:
            return

        await self.scheduler_loop.start()

    async def stop(self):
        await self.scheduler_loop.stop()
