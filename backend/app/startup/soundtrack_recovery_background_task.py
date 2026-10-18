"""
Background task lifecycle wrapper.
"""


class SoundtrackRecoveryBackgroundTask:

    def __init__(
        self,
        scheduler_loop,
    ):
        self.scheduler_loop = scheduler_loop

    async def start(self):
        await self.scheduler_loop.start()

    async def stop(self):
        await self.scheduler_loop.stop()
