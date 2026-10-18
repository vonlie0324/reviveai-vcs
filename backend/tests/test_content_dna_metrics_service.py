from datetime import datetime, timezone

from app.models.youtube import AnalysisResult, ChannelSnapshot, IngestionSummary, ThumbnailSet, VideoSnapshot
from app.services.channel_metrics_service import ChannelMetricsService
from app.services.content_dna_metrics_service import build_evidence_metrics, performance_tier


def make_video(video_id: str, views: int) -> VideoSnapshot:
    return VideoSnapshot(
        video_id=video_id,
        title=f"Video {video_id}",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        thumbnails=ThumbnailSet(medium=f"https://example.com/{video_id}.jpg"),
        duration_seconds=15,
        view_count=views,
        like_count=1,
        comment_count=0,
        watch_url=f"https://youtube.com/watch?v={video_id}",
    )


def make_analysis() -> AnalysisResult:
    videos = [
        make_video("v1", 10),
        make_video("v2", 20),
        make_video("v3", 30),
        make_video("v4", 40),
        make_video("v5", 50),
        make_video("v6", 60),
        make_video("v7", 70),
        make_video("v8", 80),
        make_video("v9", 90),
        make_video("v10", 100),
    ]
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    metrics = ChannelMetricsService().build(videos, now=now)
    channel = ChannelSnapshot(
        channel_id="UCtest",
        title="Test Channel",
        thumbnails=ThumbnailSet(),
        uploads_playlist_id="UUtest",
        channel_url="https://youtube.com/channel/UCtest",
    )
    summary = IngestionSummary(retrieved_videos=len(videos), analysis_snapshot_at=now)
    return AnalysisResult(channel=channel, summary=summary, metrics=metrics, videos=videos)


def test_performance_tier_uses_m1b_thresholds():
    analysis = make_analysis()
    assert performance_tier(analysis.videos[0], analysis) == "low"
    assert performance_tier(analysis.videos[-1], analysis) == "exceptional"


def test_group_metrics_are_computed_from_video_ids_not_ai_numbers():
    analysis = make_analysis()
    evidence = build_evidence_metrics(["v8", "v9", "v10", "missing"], analysis)

    assert evidence.video_count == 3
    assert evidence.median_views == 90.0
    assert evidence.relative_to_channel_median is not None
    assert evidence.sample_videos[0].video_id == "v10"
    assert evidence.performance_signal in {
        "Above channel baseline",
        "Near channel baseline",
        "Below channel baseline",
        "Limited sample",
    }


def test_group_metrics_deduplicate_video_ids():
    analysis = make_analysis()
    evidence = build_evidence_metrics(["v1", "v1", "v2"], analysis)
    assert evidence.video_count == 2


def test_sample_strength_is_deterministic_from_support_count():
    analysis = make_analysis()

    assert build_evidence_metrics(["v1", "v2"], analysis).sample_strength == "Limited sample"
    assert build_evidence_metrics(["v1", "v2", "v3"], analysis).sample_strength == "Emerging signal"
    assert build_evidence_metrics(["v1", "v2", "v3", "v4", "v5", "v6"], analysis).sample_strength == "Developing signal"
    assert build_evidence_metrics([f"v{i}" for i in range(1, 11)], analysis).sample_strength == "Broad historical support"
