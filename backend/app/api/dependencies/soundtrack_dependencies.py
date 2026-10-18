from app.services.youtube_audio_library_service import (
    YouTubeAudioLibraryService,
)

from app.api.routes.cloud_soundtrack_adapter import (
    SoundtrackRouteCloudAdapter,
)


def get_soundtrack_adapter():
    service = YouTubeAudioLibraryService()

    return SoundtrackRouteCloudAdapter(
        service
    )