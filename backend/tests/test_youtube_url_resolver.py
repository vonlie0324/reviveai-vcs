import pytest

from app.services.youtube_url_resolver import (
    YouTubeReferenceKind,
    YouTubeUrlError,
    resolve_youtube_reference,
)


@pytest.mark.parametrize(
    "raw,kind,value",
    [
        ("https://youtube.com/@pawshionista", YouTubeReferenceKind.HANDLE, "@pawshionista"),
        ("@pawshionista", YouTubeReferenceKind.HANDLE, "@pawshionista"),
        (
            "https://www.youtube.com/channel/UC1234567890/videos",
            YouTubeReferenceKind.CHANNEL_ID,
            "UC1234567890",
        ),
        (
            "https://studio.youtube.com/channel/UC1234567890/videos/short",
            YouTubeReferenceKind.CHANNEL_ID,
            "UC1234567890",
        ),
        (
            "https://www.youtube.com/watch?v=abcDEF12345",
            YouTubeReferenceKind.VIDEO_ID,
            "abcDEF12345",
        ),
        (
            "https://youtu.be/abcDEF12345",
            YouTubeReferenceKind.VIDEO_ID,
            "abcDEF12345",
        ),
        (
            "https://www.youtube.com/shorts/abcDEF12345",
            YouTubeReferenceKind.VIDEO_ID,
            "abcDEF12345",
        ),
    ],
)
def test_supported_urls(raw, kind, value):
    ref = resolve_youtube_reference(raw)
    assert ref.kind == kind
    assert ref.value == value


def test_legacy_custom_url_is_not_guessed():
    with pytest.raises(YouTubeUrlError):
        resolve_youtube_reference("https://youtube.com/c/some-old-name")


def test_non_youtube_url_rejected():
    with pytest.raises(YouTubeUrlError):
        resolve_youtube_reference("https://example.com/channel/test")
