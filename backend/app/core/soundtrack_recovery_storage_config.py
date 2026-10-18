"""
Storage configuration for soundtrack recovery.
"""


class SoundtrackRecoveryStorageConfig:

    def __init__(
        self,
        collection="soundtrack_job_checkpoints",
    ):
        self.collection = collection
