"""
Discovery abstraction for interrupted soundtrack jobs.
"""


class SoundtrackRecoveryJobDiscovery:

    def __init__(
        self,
        checkpoint_store=None,
    ):
        self.checkpoint_store = checkpoint_store

    async def find_interrupted_jobs(self):
        if not self.checkpoint_store:
            return []

        return await self.checkpoint_store.find_by_status(
            "PROCESSING"
        )
