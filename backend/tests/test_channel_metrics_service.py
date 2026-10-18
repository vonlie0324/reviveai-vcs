from datetime import datetime, timezone

from app.models.youtube import ThumbnailSet, VideoSnapshot
from app.services.channel_metrics_service import ChannelMetricsService


def make_video(index: int, *, views: int, day: int, duration: int = 30, likes: int | None = None, comments: int | None = None):
    return VideoSnapshot(
        video_id=f"v{index}",
        title=f"Video {index}",
        published_at=datetime(2026, 1, day, tzinfo=timezone.utc),
        thumbnails=ThumbnailSet(default=f"https://example.com/{index}.jpg"),
        duration_seconds=duration,
        view_count=views,
        like_count=likes,
        comment_count=comments,
        watch_url=f"https://youtube.com/watch?v=v{index}",
    )


def test_distribution_and_rankings_are_deterministic():
    videos = [
        make_video(1, views=10, day=1),
        make_video(2, views=20, day=3),
        make_video(3, views=30, day=5),
        make_video(4, views=40, day=7),
        make_video(5, views=100, day=9),
    ]
    metrics = ChannelMetricsService().build(
        videos,
        now=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )

    assert metrics.views.count == 5
    assert metrics.views.median == 30.0
    assert metrics.views.p25 == 20.0
    assert metrics.views.p75 == 40.0
    assert metrics.top_videos[0].views == 100
    assert metrics.top_videos[0].relative_to_median == 3.33
    assert metrics.bottom_videos[0].views == 10


def test_cadence_flags_large_current_gap_as_dormant():
    videos = [
        make_video(1, views=10, day=1),
        make_video(2, views=20, day=3),
        make_video(3, views=30, day=5),
        make_video(4, views=40, day=7),
    ]
    metrics = ChannelMetricsService().build(
        videos,
        now=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )

    assert metrics.cadence.median_active_day_gap_days == 2.0
    assert metrics.cadence.current_gap_days == 103
    assert metrics.cadence.current_gap_vs_median_active_day_gap == 51.5
    assert metrics.cadence.status == "dormant"


def test_engagement_rates_use_only_videos_with_available_counts():
    videos = [
        make_video(1, views=100, day=1, likes=10, comments=2),
        make_video(2, views=100, day=2, likes=None, comments=1),
    ]
    metrics = ChannelMetricsService().build(
        videos,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert metrics.engagement.likes_per_1000_views == 100.0
    assert metrics.engagement.comments_per_1000_views == 15.0
    assert metrics.engagement.like_coverage_videos == 1
    assert metrics.engagement.comment_coverage_videos == 2


def test_duration_bands_separate_short_and_brief_content():
    videos = [
        make_video(1, views=100, day=1, duration=30),
        make_video(2, views=200, day=2, duration=120),
        make_video(3, views=300, day=3, duration=500),
        make_video(4, views=400, day=4, duration=900),
    ]
    metrics = ChannelMetricsService().build(
        videos,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert [band.video_count for band in metrics.duration_bands] == [1, 1, 1, 1]
    assert [band.median_views for band in metrics.duration_bands] == [100.0, 200.0, 300.0, 400.0]


def test_cadence_collapses_same_day_bursts_into_active_publishing_days():
    videos = [
        VideoSnapshot(
            video_id="v1",
            title="Video 1",
            published_at=datetime(2026, 1, 1, 8, tzinfo=timezone.utc),
            thumbnails=ThumbnailSet(),
            duration_seconds=30,
            view_count=100,
            watch_url="https://youtube.com/watch?v=v1",
        ),
        VideoSnapshot(
            video_id="v2",
            title="Video 2",
            published_at=datetime(2026, 1, 1, 13, tzinfo=timezone.utc),
            thumbnails=ThumbnailSet(),
            duration_seconds=30,
            view_count=100,
            watch_url="https://youtube.com/watch?v=v2",
        ),
        VideoSnapshot(
            video_id="v3",
            title="Video 3",
            published_at=datetime(2026, 1, 3, 9, tzinfo=timezone.utc),
            thumbnails=ThumbnailSet(),
            duration_seconds=30,
            view_count=100,
            watch_url="https://youtube.com/watch?v=v3",
        ),
        VideoSnapshot(
            video_id="v4",
            title="Video 4",
            published_at=datetime(2026, 1, 5, 10, tzinfo=timezone.utc),
            thumbnails=ThumbnailSet(),
            duration_seconds=30,
            view_count=100,
            watch_url="https://youtube.com/watch?v=v4",
        ),
    ]
    metrics = ChannelMetricsService().build(
        videos,
        now=datetime(2026, 1, 10, tzinfo=timezone.utc),
    )

    assert metrics.cadence.active_publishing_days == 3
    assert metrics.cadence.median_active_day_gap_days == 2.0
    assert metrics.cadence.longest_historical_active_day_gap_days == 2
    assert metrics.cadence.typical_uploads_per_active_day == 1.0


def test_burst_style_uses_median_uploads_per_active_day():
    videos = []
    index = 1
    for day in (1, 3, 5):
        for hour in (8, 12):
            videos.append(
                VideoSnapshot(
                    video_id=f"v{index}",
                    title=f"Video {index}",
                    published_at=datetime(2026, 1, day, hour, tzinfo=timezone.utc),
                    thumbnails=ThumbnailSet(),
                    duration_seconds=30,
                    view_count=100,
                    watch_url=f"https://youtube.com/watch?v=v{index}",
                )
            )
            index += 1

    metrics = ChannelMetricsService().build(videos, now=datetime(2026, 1, 10, tzinfo=timezone.utc))

    assert metrics.cadence.publishing_style == "Burst publishing"
    assert metrics.cadence.typical_uploads_per_active_day == 2.0
    assert metrics.cadence.median_active_day_gap_days == 2.0
