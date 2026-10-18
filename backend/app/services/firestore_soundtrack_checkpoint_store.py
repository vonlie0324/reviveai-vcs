"""
Firestore implementation for soundtrack checkpoint storage.

Keeps persistence access isolated from recovery workflow.
"""


class FirestoreSoundtrackCheckpointStore:

    def __init__(self, firestore_client, collection):
        self.client = firestore_client
        self.collection = collection

    async def find(
        self,
        filters=None,
    ):
        filters = filters or {}

        query = (
            self.client
            .collection(self.collection)
        )

        for field, value in filters.items():
            query = query.where(
                field,
                "==",
                value,
            )

        result = query.stream()

        return [
            {
                "job_id": doc.id,
                **doc.to_dict(),
            }
            for doc in result
        ]

    async def get(self, job_id):
        doc = (
            self.client
            .collection(self.collection)
            .document(job_id)
            .get()
        )

        if not doc.exists:
            return None

        return {
            "job_id": job_id,
            **doc.to_dict(),
        }

    async def save(
        self,
        job_id,
        state,
    ):
        (
            self.client
            .collection(self.collection)
            .document(job_id)
            .set(
                state,
                merge=True,
            )
        )
