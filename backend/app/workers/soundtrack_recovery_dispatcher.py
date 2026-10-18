"""
Dispatches discovered interrupted soundtrack jobs
into the recovery workflow.
"""


class SoundtrackRecoveryDispatcher:

    def __init__(
        self,
        recovery_worker,
    ):
        self.recovery_worker = recovery_worker

    async def dispatch(
        self,
        jobs,
    ):
        job_ids = []

        for job in jobs:
            if isinstance(job, dict):
                job_ids.append(
                    job.get("job_id")
                )

        return self.recovery_worker.recover(
            job_ids
        )
