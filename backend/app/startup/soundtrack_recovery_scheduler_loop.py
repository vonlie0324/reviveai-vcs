"""
Managed background scheduler loop for soundtrack recovery.
"""

import asyncio


class SoundtrackRecoverySchedulerLoop:

    def __init__(
        self,
        runner,
        interval_seconds=300,
    ):
        self.runner = runner
        self.interval_seconds = interval_seconds
        self.task = None
        self.running = False

    async def start(self):
        self.running = True
        self.task = asyncio.create_task(
            self._loop()
        )

    async def stop(self):
        self.running = False

        if self.task:
            self.task.cancel()

    async def _loop(self):
        while self.running:
            try:
                await self.runner.run([])
            except Exception:
                pass

            await asyncio.sleep(
                self.interval_seconds
            )
