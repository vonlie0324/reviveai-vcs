
from app.services.youtube_audio_library_service import (
    YouTubeAudioLibraryService,
)


class SoundtrackCloudMigrationService:
    """
    Adapter layer that switches API usage from legacy
    local catalog methods to cloud-backed methods.
    """

    def __init__(self, soundtrack_service=None):
        self.service = soundtrack_service or YouTubeAudioLibraryService()

    def list_soundtracks(self, channel_id=None):
        return self.service.list_tracks(
            channel_id=channel_id
        )

    def resolve_soundtrack(self, track_id):
        return self.service.resolve_cloud_track(
            track_id
        )

    def delete_soundtrack(self, track_id):
        return self.service.delete_cloud_track(
            track_id
        )
