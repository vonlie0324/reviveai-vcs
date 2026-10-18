"""
Processes recovered soundtrack jobs.
"""


class SoundtrackRecoveryJobProcessor:

    def __init__(
        self,
        execution_worker,
    ):
        self.execution_worker = execution_worker

    async def process(self, jobs):
        return await self.execution_worker.execute(jobs)
