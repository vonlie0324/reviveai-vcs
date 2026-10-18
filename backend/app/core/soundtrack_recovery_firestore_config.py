"""
Firestore recovery configuration.
"""


class SoundtrackRecoveryFirestoreConfig:

    def __init__(
        self,
        collection="soundtrack_job_checkpoints",
    ):
        self.collection = collection
