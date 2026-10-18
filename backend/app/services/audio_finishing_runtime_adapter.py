"""
Runtime adapter for audio finishing.

Converts Firestore soundtrack metadata into
processing-ready assets.
"""


class AudioFinishingRuntimeAdapter:

    def __init__(
        self,
        soundtrack_service,
        storage_service,
    ):
        self.soundtrack_service = soundtrack_service
        self.storage_service = storage_service

    def get_local_processing_file(self, track_id):
        track = self.soundtrack_service.resolve_track(
            track_id
        )

        if not track:
            raise ValueError(
                f"Missing soundtrack: {track_id}"
            )

        return self.storage_service.download_temp(
            track["storage_path"]
        )
