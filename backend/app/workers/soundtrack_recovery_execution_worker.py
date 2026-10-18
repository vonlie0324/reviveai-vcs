"""
Execution worker wrapper for recovered soundtrack jobs.
"""


class SoundtrackRecoveryExecutionWorker:

    def __init__(
        self,
        recovery_service,
    ):
        self.recovery_service = recovery_service

    async def execute(
        self,
        jobs,
    ):
        results = []

        for job in jobs:
            results.append(
                await self.recovery_service.recover_job(
                    job["job_id"]
                )
            )

        return results
