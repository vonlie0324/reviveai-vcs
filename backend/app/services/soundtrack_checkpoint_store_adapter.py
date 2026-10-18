"""
Checkpoint store adapter for soundtrack recovery.

Abstracts persistence implementation.
Can be backed by Firestore, Redis, SQL, or another store.
"""


class SoundtrackCheckpointStoreAdapter:

    def __init__(self, backend=None):
        self.backend = backend

    async def find_processing_jobs(self):
        if not self.backend:
            return []

        return await self.backend.find(
            {
                "soundtrack_execution.status": "PROCESSING"
            }
        )

    async def get_job_checkpoint(self, job_id):
        if not self.backend:
            return None

        return await self.backend.get(job_id)

    async def save_job_checkpoint(
        self,
        job_id,
        state,
    ):
        if not self.backend:
            return None

        return await self.backend.save(
            job_id,
            state,
        )
