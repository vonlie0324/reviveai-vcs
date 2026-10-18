from datetime import datetime, timezone

from app.models.youtube import ThumbnailSet, VideoSnapshot
from app.services.channel_metrics_service import ChannelMetricsService
from app.services.time_utils import utc_calendar_day_gap


def test_calendar_day_gap_is_stable_across_partial_utc_days():
    latest = datetime(2026, 8, 12, 23, 30, tzinfo=timezone.utc)
    snapshot = datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)

    assert utc_calendar_day_gap(latest, snapshot) == 40


def test_cadence_uses_the_shared_calendar_day_gap():
    latest = datetime(2026, 8, 12, 23, 30, tzinfo=timezone.utc)
    snapshot = datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc)
    videos = [
        VideoSnapshot(
            video_id="v1",
            title="Video 1",
            published_at=latest,
            thumbnails=ThumbnailSet(),
            duration_seconds=30,
            view_count=100,
            watch_url="https://youtube.com/watch?v=v1",
        )
    ]

    metrics = ChannelMetricsService().build(videos, now=snapshot)
    assert metrics.cadence.current_gap_days == utc_calendar_day_gap(latest, snapshot)
