"""
Scheduler wrapper for soundtrack recovery execution.
"""


class SoundtrackRecoveryScheduler:

    def __init__(
        self,
        recovery_worker,
    ):
        self.recovery_worker = recovery_worker

    def run_once(
        self,
        interrupted_job_ids,
    ):
        return self.recovery_worker.recover(
            interrupted_job_ids
        )
