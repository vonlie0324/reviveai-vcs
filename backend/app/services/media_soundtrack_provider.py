"""
Media generation soundtrack provider.

Provides cloud-backed soundtrack resolution for
video generation and finishing workflows.
"""


class MediaSoundtrackProvider:

    def __init__(self, soundtrack_service):
        self.soundtrack_service = soundtrack_service

    def resolve_for_generation(self, track_id):
        track = self.soundtrack_service.resolve_track(
            track_id
        )

        if not track:
            raise ValueError(
                f"Soundtrack not found: {track_id}"
            )

        return {
            "track_id": track.get("track_id"),
            "storage_path": track.get("storage_path"),
            "preview_url": track.get("preview_url"),
        }
