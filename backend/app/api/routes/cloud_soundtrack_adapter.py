"""
Adapter helpers for cloud soundtrack APIs.

Keeps existing UI contracts while switching
the backend source from local catalog to Firestore.
"""


class SoundtrackRouteCloudAdapter:

    def __init__(self, soundtrack_service):
        self.service = soundtrack_service

    def list(self, channel_id=None):
        return self.service.list_tracks(
            channel_id=channel_id
        )

    def resolve(self, track_id):
        return self.service.resolve_cloud_track(
            track_id
        )

    def remove(self, track_id):
        return self.service.delete_cloud_track(
            track_id
        )


def serialize_cloud_track(track: dict):
    return {
        "id": track.get("track_id"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "preview_url": track.get("preview_url"),
        "storage_path": track.get("storage_path"),
    }