from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import parse_qs, urlparse


class YouTubeReferenceKind(str, Enum):
    CHANNEL_ID = "CHANNEL_ID"
    HANDLE = "HANDLE"
    VIDEO_ID = "VIDEO_ID"


@dataclass(frozen=True)
class YouTubeReference:
    kind: YouTubeReferenceKind
    value: str


class YouTubeUrlError(ValueError):
    pass


def resolve_youtube_reference(raw: str) -> YouTubeReference:
    value = raw.strip()
    if not value:
        raise YouTubeUrlError("Paste a YouTube channel or video URL.")

    # Friendly support for a bare handle too.
    if value.startswith("@") and len(value) > 1:
        return YouTubeReference(YouTubeReferenceKind.HANDLE, value)

    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"

    parsed = urlparse(value)
    host = parsed.netloc.lower().split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]

    youtube_hosts = {
        "youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "studio.youtube.com",
    }

    path_parts = [part for part in parsed.path.split("/") if part]

    if host == "youtu.be":
        if not path_parts:
            raise YouTubeUrlError("The youtu.be link does not contain a video ID.")
        return YouTubeReference(YouTubeReferenceKind.VIDEO_ID, path_parts[0])

    if host not in youtube_hosts:
        raise YouTubeUrlError("This does not look like a YouTube URL.")

    if path_parts and path_parts[0].startswith("@"):
        return YouTubeReference(YouTubeReferenceKind.HANDLE, path_parts[0])

    if len(path_parts) >= 2 and path_parts[0] == "channel":
        return YouTubeReference(YouTubeReferenceKind.CHANNEL_ID, path_parts[1])

    if len(path_parts) >= 2 and path_parts[0] in {"shorts", "live", "embed"}:
        return YouTubeReference(YouTubeReferenceKind.VIDEO_ID, path_parts[1])

    if path_parts and path_parts[0] == "watch":
        video_id = parse_qs(parsed.query).get("v", [None])[0]
        if video_id:
            return YouTubeReference(YouTubeReferenceKind.VIDEO_ID, video_id)
        raise YouTubeUrlError("The watch URL is missing its video ID.")

    if path_parts and path_parts[0] in {"c", "user"}:
        raise YouTubeUrlError(
            "Legacy /c/ and /user/ URLs are not guessed in M1A. "
            "Paste the channel's @handle, channel-ID URL, or any video URL from that channel."
        )

    raise YouTubeUrlError(
        "Unsupported YouTube URL. Paste an @handle, /channel/ URL, YouTube Studio channel URL, "
        "or a video/Short URL."
    )
