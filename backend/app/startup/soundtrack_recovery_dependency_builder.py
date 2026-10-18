"""
Builds runtime dependencies for soundtrack recovery.
"""


class SoundtrackRecoveryDependencyBuilder:

    def __init__(
        self,
        checkpoint_store,
        recovery_worker,
        scheduler_loop,
    ):
        self.checkpoint_store = checkpoint_store
        self.recovery_worker = recovery_worker
        self.scheduler_loop = scheduler_loop

    def build(self):
        return {
            "checkpoint_store": self.checkpoint_store,
            "recovery_worker": self.recovery_worker,
            "scheduler_loop": self.scheduler_loop,
        }
