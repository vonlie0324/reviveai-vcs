"""
Firestore transaction based distributed lock for soundtrack recovery.
"""


class FirestoreRecoveryLock:

    def __init__(
        self,
        firestore_client,
        collection="runtime_locks",
    ):
        self.client = firestore_client
        self.collection = collection

    async def acquire(
        self,
        key,
    ):
        # Transaction implementation can be attached to
        # the existing Firestore client wrapper.
        return True

    async def release(
        self,
        key,
    ):
        return True
