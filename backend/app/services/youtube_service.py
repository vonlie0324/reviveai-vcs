from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Dict, Iterable, List, Optional

import httpx
import isodate

from app.core.config import Settings
from app.models.youtube import (
    AnalysisResult,
    ChannelSnapshot,
    IngestionSummary,
    JobStage,
    ThumbnailSet,
    VideoSnapshot,
)
from app.services.channel_metrics_service import ChannelMetricsService
from app.services.time_utils import utc_calendar_day_gap
from app.services.youtube_url_resolver import (
    YouTubeReferenceKind,
    YouTubeUrlError,
    resolve_youtube_reference,
)


class YouTubeApiError(RuntimeError):
    pass


StageCallback = Callable[[JobStage, str, Dict], None]


class YouTubeService:
    BASE_URL = "https://www.googleapis.com/youtube/v3"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.request_count = 0

    async def analyze(self, url: str, on_stage: StageCallback) -> AnalysisResult:
        if not self.settings.youtube_api_key:
            raise YouTubeApiError(
                "YOUTUBE_API_KEY is not configured. Enable YouTube Data API v3 and add the key "
                "to backend/.env or the YOUTUBE_API_KEY environment variable."
            )

        on_stage(JobStage.RESOLVING_CHANNEL, "Resolving the YouTube channel", {})
        reference = resolve_youtube_reference(url)

        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            channel_id = await self._resolve_channel_id(client, reference)
            channel_resource = await self._get_channel(client, channel_id)
            channel = self._parse_channel(channel_resource)

            on_stage(
                JobStage.READING_UPLOADS,
                "Reading the channel's public upload history",
                {"videos_discovered": 0, "pages_read": 0},
            )
            video_ids = await self._get_upload_video_ids(
                client,
                channel.uploads_playlist_id,
                on_stage,
            )

            on_stage(
                JobStage.FETCHING_VIDEO_DETAILS,
                "Fetching public video metadata and statistics",
                {"videos_discovered": len(video_ids), "videos_loaded": 0},
            )
            videos = await self._get_video_details(client, video_ids, on_stage)

        on_stage(
            JobStage.COMPUTING_METRICS,
            "Computing evidence-backed channel metrics",
            {"videos_loaded": len(videos)},
        )

        videos.sort(
            key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        # M1B.2: take one canonical UTC snapshot time and reuse it for every
        # time-relative metric. This prevents Channel Overview and Channel Health
        # from disagreeing around UTC day boundaries.
        analysis_snapshot_at = datetime.now(timezone.utc)
        summary = self._build_summary(videos, len(video_ids), analysis_snapshot_at)
        summary.youtube_api_requests = self.request_count
        metrics = ChannelMetricsService().build(videos, now=analysis_snapshot_at)

        on_stage(
            JobStage.PREPARING_SNAPSHOT,
            "Preparing the channel intelligence dashboard",
            {"videos_loaded": len(videos)},
        )

        return AnalysisResult(channel=channel, summary=summary, metrics=metrics, videos=videos)

    async def _api_get(self, client: httpx.AsyncClient, resource: str, params: Dict) -> Dict:
        request_params = {**params, "key": self.settings.youtube_api_key}
        self.request_count += 1
        try:
            response = await client.get(f"{self.BASE_URL}/{resource}", params=request_params)
        except httpx.RequestError as exc:
            raise YouTubeApiError(f"Could not reach YouTube Data API: {exc}") from exc

        if response.status_code >= 400:
            message = "YouTube Data API request failed."
            try:
                payload = response.json()
                message = payload.get("error", {}).get("message", message)
            except Exception:
                pass
            raise YouTubeApiError(message)
        return response.json()

    async def _resolve_channel_id(self, client: httpx.AsyncClient, reference) -> str:
        if reference.kind == YouTubeReferenceKind.CHANNEL_ID:
            return reference.value

        if reference.kind == YouTubeReferenceKind.HANDLE:
            payload = await self._api_get(
                client,
                "channels",
                {
                    "part": "id",
                    "forHandle": reference.value,
                    "maxResults": 1,
                },
            )
            items = payload.get("items", [])
            if not items:
                raise YouTubeApiError(f"No channel was found for handle {reference.value}.")
            return items[0]["id"]

        if reference.kind == YouTubeReferenceKind.VIDEO_ID:
            payload = await self._api_get(
                client,
                "videos",
                {"part": "snippet", "id": reference.value},
            )
            items = payload.get("items", [])
            if not items:
                raise YouTubeApiError("The video could not be found or is not publicly accessible.")
            return items[0]["snippet"]["channelId"]

        raise YouTubeUrlError("Unsupported YouTube reference.")

    async def _get_channel(self, client: httpx.AsyncClient, channel_id: str) -> Dict:
        payload = await self._api_get(
            client,
            "channels",
            {
                "part": "snippet,statistics,contentDetails",
                "id": channel_id,
                "maxResults": 1,
            },
        )
        items = payload.get("items", [])
        if not items:
            raise YouTubeApiError("The channel could not be found or is not publicly accessible.")
        return items[0]

    async def _get_upload_video_ids(
        self,
        client: httpx.AsyncClient,
        uploads_playlist_id: str,
        on_stage: StageCallback,
    ) -> List[str]:
        ids: List[str] = []
        page_token: Optional[str] = None
        pages_read = 0
        max_videos = self.settings.youtube_max_videos

        while True:
            params = {
                "part": "contentDetails",
                "playlistId": uploads_playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token

            payload = await self._api_get(client, "playlistItems", params)
            pages_read += 1
            for item in payload.get("items", []):
                video_id = item.get("contentDetails", {}).get("videoId")
                if video_id:
                    ids.append(video_id)
                    if max_videos and len(ids) >= max_videos:
                        on_stage(
                            JobStage.READING_UPLOADS,
                            "Reading the channel's public upload history",
                            {
                                "videos_discovered": len(ids),
                                "pages_read": pages_read,
                                "limit_reached": True,
                            },
                        )
                        return ids

            on_stage(
                JobStage.READING_UPLOADS,
                "Reading the channel's public upload history",
                {"videos_discovered": len(ids), "pages_read": pages_read},
            )

            page_token = payload.get("nextPageToken")
            if not page_token:
                return ids

    async def _get_video_details(
        self,
        client: httpx.AsyncClient,
        video_ids: List[str],
        on_stage: StageCallback,
    ) -> List[VideoSnapshot]:
        videos: List[VideoSnapshot] = []
        total = len(video_ids)

        for batch in _chunks(video_ids, 50):
            payload = await self._api_get(
                client,
                "videos",
                {
                    "part": "snippet,statistics,contentDetails",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            for item in payload.get("items", []):
                videos.append(self._parse_video(item))

            on_stage(
                JobStage.FETCHING_VIDEO_DETAILS,
                "Fetching public video metadata and statistics",
                {"videos_discovered": total, "videos_loaded": len(videos)},
            )

        return videos

    @staticmethod
    def _parse_channel(item: Dict) -> ChannelSnapshot:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        uploads = content_details.get("relatedPlaylists", {}).get("uploads")
        if not uploads:
            raise YouTubeApiError("YouTube did not return an uploads playlist for this channel.")

        hidden = bool(statistics.get("hiddenSubscriberCount", False))
        subscriber_count = None if hidden else _int_or_none(statistics.get("subscriberCount"))

        return ChannelSnapshot(
            channel_id=item["id"],
            title=snippet.get("title", "Untitled channel"),
            description=snippet.get("description", ""),
            custom_url=snippet.get("customUrl"),
            published_at=_datetime_or_none(snippet.get("publishedAt")),
            country=snippet.get("country"),
            thumbnails=_parse_thumbnails(snippet.get("thumbnails", {})),
            subscriber_count=subscriber_count,
            subscriber_count_hidden=hidden,
            lifetime_view_count=_int_or_none(statistics.get("viewCount")),
            public_video_count_reported=_int_or_none(statistics.get("videoCount")),
            uploads_playlist_id=uploads,
            channel_url=f"https://www.youtube.com/channel/{item['id']}",
        )

    @staticmethod
    def _parse_video(item: Dict) -> VideoSnapshot:
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        duration = content_details.get("duration", "PT0S")
        try:
            duration_seconds = int(isodate.parse_duration(duration).total_seconds())
        except Exception:
            duration_seconds = 0

        return VideoSnapshot(
            video_id=item["id"],
            title=snippet.get("title", "Untitled video"),
            description=snippet.get("description", ""),
            published_at=_datetime_or_none(snippet.get("publishedAt")),
            thumbnails=_parse_thumbnails(snippet.get("thumbnails", {})),
            duration_seconds=duration_seconds,
            view_count=_int_or_none(statistics.get("viewCount")),
            like_count=_int_or_none(statistics.get("likeCount")),
            comment_count=_int_or_none(statistics.get("commentCount")),
            tags=snippet.get("tags", []) or [],
            category_id=snippet.get("categoryId"),
            default_language=snippet.get("defaultLanguage"),
            default_audio_language=snippet.get("defaultAudioLanguage"),
            captions_available=str(content_details.get("caption", "false")).lower() == "true",
            definition=content_details.get("definition"),
            live_broadcast_content=snippet.get("liveBroadcastContent"),
            watch_url=f"https://www.youtube.com/watch?v={item['id']}",
        )

    def _build_summary(
        self,
        videos: List[VideoSnapshot],
        discovered_count: int,
        analysis_snapshot_at: datetime,
    ) -> IngestionSummary:
        latest = max(
            (video.published_at for video in videos if video.published_at),
            default=None,
        )
        snapshot_utc = analysis_snapshot_at.astimezone(timezone.utc)
        days_since = None
        if latest:
            latest_utc = latest.astimezone(timezone.utc)
            # Same shared helper used by cadence.current_gap_days.
            days_since = utc_calendar_day_gap(latest_utc, snapshot_utc)

        return IngestionSummary(
            retrieved_videos=len(videos),
            analysis_snapshot_at=snapshot_utc,
            latest_upload_at=latest,
            days_since_latest_upload=days_since,
            videos_le_60_seconds=sum(1 for video in videos if 0 < video.duration_seconds <= 60),
            videos_le_180_seconds=sum(1 for video in videos if 0 < video.duration_seconds <= 180),
            total_retrieved_views=sum(video.view_count or 0 for video in videos),
            total_retrieved_likes=sum(video.like_count or 0 for video in videos),
            total_retrieved_comments=sum(video.comment_count or 0 for video in videos),
            retrieval_limit_applied=bool(
                self.settings.youtube_max_videos
                and discovered_count >= self.settings.youtube_max_videos
            ),
        )


def _chunks(values: List[str], size: int) -> Iterable[List[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _int_or_none(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_thumbnails(payload: Dict) -> ThumbnailSet:
    def url_for(name: str) -> Optional[str]:
        item = payload.get(name) or {}
        return item.get("url")

    return ThumbnailSet(
        default=url_for("default"),
        medium=url_for("medium"),
        high=url_for("high"),
        standard=url_for("standard"),
        maxres=url_for("maxres"),
    )
