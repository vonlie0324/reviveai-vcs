
"""
Production validation service for soundtrack cloud migration.

Connect real Firestore and Cloud Storage clients through dependency injection.
"""


class SoundtrackCloudValidationService:

    def __init__(
        self,
        firestore_repository,
        storage_service,
    ):
        self.firestore_repository = firestore_repository
        self.storage_service = storage_service

    def validate_track(self, track_id):
        record = self.firestore_repository.get(track_id)

        if not record:
            return {
                "track_id": track_id,
                "passed": False,
                "reason": "firestore_record_missing",
            }

        storage_path = record.get("storage_path")

        storage_exists = (
            self.storage_service.exists(storage_path)
            if storage_path
            else False
        )

        preview_url = (
            self.storage_service.generate_signed_url(
                storage_path
            )
            if storage_exists
            else None
        )

        return {
            "track_id": track_id,
            "firestore_metadata": True,
            "storage_object": storage_exists,
            "preview_url": bool(preview_url),
            "passed": bool(
                storage_exists and preview_url
            ),
        }
