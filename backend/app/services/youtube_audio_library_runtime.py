"""
Runtime-aware soundtrack library wrapper.

Uses initialized Firestore repository and Cloud Storage service
instead of creating storage dependencies directly.
"""


class YouTubeAudioLibraryRuntime:

    def __init__(
        self,
        repository,
        storage,
    ):
        self.repository = repository
        self.storage = storage

    def list_tracks(self, channel_id=None):
        tracks = self.repository.list(
            channel_id=channel_id
        )

        return [
            self.repository.with_preview_url(
                track,
                self.storage,
            )
            for track in tracks
        ]

    def resolve_track(self, track_id):
        track = self.repository.get(track_id)

        if not track:
            return None

        return self.repository.with_preview_url(
            track,
            self.storage,
        )

    def delete_track(self, track_id):
        return self.repository.delete(
            track_id
        )
