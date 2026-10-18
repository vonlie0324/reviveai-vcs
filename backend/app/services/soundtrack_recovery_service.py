"""
Service for restoring interrupted soundtrack execution state.
"""


class SoundtrackRecoveryService:

    def __init__(
        self,
        checkpoint_store=None,
    ):
        self.checkpoint_store = checkpoint_store

    def recover_job(self, job_id):
        if not self.checkpoint_store:
            return None

        checkpoint = self.checkpoint_store.get(job_id)

        if not checkpoint:
            return None

        return checkpoint.get(
            "soundtrack_execution"
        )
