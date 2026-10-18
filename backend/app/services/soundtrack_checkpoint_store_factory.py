"""
Factory for creating soundtrack checkpoint storage.
"""


from app.services.firestore_soundtrack_checkpoint_store import (
    FirestoreSoundtrackCheckpointStore,
)


def create_soundtrack_checkpoint_store(
    firestore_client,
    collection,
):
    return FirestoreSoundtrackCheckpointStore(
        firestore_client,
        collection,
    )
