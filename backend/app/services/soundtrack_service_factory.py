from app.core.firebase_clients import (
    get_runtime_firestore_client,
    get_storage_client,
)
from app.services.cloud_storage_service import CloudStorageService
from app.services.soundtrack_firestore_repository import SoundtrackFirestoreRepository


def create_soundtrack_repository():
    # Use the same configured Firestore database as the durable ReviveAI runtime.
    # This is important when FIRESTORE_DATABASE_ID is a named database such as
    # reviveai-prod rather than the project default database.
    return SoundtrackFirestoreRepository(db=get_runtime_firestore_client())


def create_cloud_storage_service(gcs_uri):
    return CloudStorageService(gcs_uri=gcs_uri, client=get_storage_client())
