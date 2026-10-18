from pathlib import Path


class SoundtrackMigrationService:

    def migrate_local_track(
        self,
        local_path: Path,
        track_id: str,
        storage_service,
        firestore_repository,
        metadata: dict,
    ):
        storage_path = storage_service.build_path(
            f"{track_id}{local_path.suffix}"
        )

        storage_service.upload_file(
            local_path,
            storage_path,
        )

        return firestore_repository.create(
            track_id,
            {
                **metadata,
                "storage_path": storage_path,
                "source": "YOUTUBE_AUDIO_LIBRARY",
            },
        )
