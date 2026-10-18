
"""
Cloud soundtrack route adapter.

Use this adapter in existing API routes while removing
direct dependency on local catalog implementations.
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
