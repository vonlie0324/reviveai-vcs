"""
FastAPI dependencies for runtime soundtrack services.
"""

from app.services.youtube_audio_library_runtime import (
    YouTubeAudioLibraryRuntime,
)


def get_runtime_soundtrack_service(request):
    return YouTubeAudioLibraryRuntime(
        repository=request.app.state.soundtrack_repository,
        storage=request.app.state.soundtrack_storage,
    )
