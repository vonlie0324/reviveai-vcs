"""
Runtime service that connects scheduler, storage, and recovery.
"""


class SoundtrackRecoveryRuntimeService:

    def __init__(
        self,
        checkpoint_store,
        dispatcher,
    ):
        self.checkpoint_store = checkpoint_store
        self.dispatcher = dispatcher

    async def execute_recovery_cycle(self):
        jobs = await self.checkpoint_store.find(
            {
                "soundtrack_execution.status": "PROCESSING"
            }
        )

        return await self.dispatcher.dispatch(
            jobs
        )
