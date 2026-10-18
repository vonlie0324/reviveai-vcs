"""
Firestore transaction lock implementation placeholder.

Keeps lock behavior isolated from recovery orchestration.
"""


class FirestoreTransactionLock:

    def __init__(
        self,
        firestore_client,
        collection="runtime_locks",
    ):
        self.client = firestore_client
        self.collection = collection

    async def acquire(self, key):
        # Attach Firestore transaction wrapper here.
        return True

    async def release(self, key):
        return True
