"""
Recovery worker for interrupted soundtrack jobs.
"""


class SoundtrackRecoveryWorker:

    def __init__(
        self,
        recovery_service,
    ):
        self.recovery_service = recovery_service

    def recover(self, job_ids):
        recovered = []

        for job_id in job_ids:
            state = self.recovery_service.recover_job(
                job_id
            )

            if state:
                recovered.append(
                    {
                        "job_id": job_id,
                        "soundtrack_execution": state,
                    }
                )

        return recovered
