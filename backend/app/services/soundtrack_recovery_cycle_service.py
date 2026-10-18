"""
End-to-end soundtrack recovery cycle service.
"""


class SoundtrackRecoveryCycleService:

    def __init__(
        self,
        checkpoint_store,
        dispatcher,
        lock,
    ):
        self.checkpoint_store = checkpoint_store
        self.dispatcher = dispatcher
        self.lock = lock

    async def run_cycle(self):
        lock_key = "soundtrack_recovery_cycle"

        acquired = await self.lock.acquire(
            lock_key
        )

        if not acquired:
            return []

        try:
            jobs = await self.checkpoint_store.find(
                {
                    "soundtrack_execution.status": "PROCESSING"
                }
            )

            return await self.dispatcher.dispatch(
                jobs
            )

        finally:
            await self.lock.release(
                lock_key
            )
