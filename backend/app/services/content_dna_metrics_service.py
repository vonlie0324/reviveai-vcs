from __future__ import annotations

from statistics import median
from typing import Iterable, List, Sequence

from app.models.content_dna import EvidenceMetrics, EvidenceVideoRef
from app.models.youtube import AnalysisResult, VideoSnapshot


def performance_tier(video: VideoSnapshot, analysis: AnalysisResult) -> str:
    views = video.view_count
    dist = analysis.metrics.views
    if views is None or dist.p25 is None or dist.p75 is None or dist.p90 is None:
        return "unknown"
    if views >= dist.p90:
        return "exceptional"
    if views >= dist.p75:
        return "strong"
    if views >= dist.p25:
        return "typical"
    return "low"


def build_evidence_metrics(video_ids: Iterable[str], analysis: AnalysisResult) -> EvidenceMetrics:
    video_map = {video.video_id: video for video in analysis.videos}
    ids = list(dict.fromkeys(video_id for video_id in video_ids if video_id in video_map))
    videos = [video_map[video_id] for video_id in ids]
    measurable = [video for video in videos if video.view_count is not None]

    tier_counts = {"low": 0, "typical": 0, "strong": 0, "exceptional": 0}
    for video in measurable:
        tier = performance_tier(video, analysis)
        if tier in tier_counts:
            tier_counts[tier] += 1

    view_values = [video.view_count or 0 for video in measurable]
    median_views = float(median(view_values)) if view_values else None
    channel_median = analysis.metrics.views.median
    relative = None
    if median_views is not None and channel_median and channel_median > 0:
        relative = median_views / channel_median

    global_tier_counts = {
        tier.key: tier.count for tier in analysis.metrics.performance_tiers
    }
    total_exceptional = global_tier_counts.get("exceptional", 0)
    total_typical = global_tier_counts.get("typical", 0)

    exceptional_share = (
        (tier_counts["exceptional"] / total_exceptional) * 100
        if total_exceptional
        else None
    )
    typical_share = (
        (tier_counts["typical"] / total_typical) * 100
        if total_typical
        else None
    )
    lift = None
    if exceptional_share is not None and typical_share is not None and typical_share > 0:
        lift = exceptional_share / typical_share

    signal = _performance_signal(len(measurable), relative)
    sample_strength = _sample_strength(len(measurable))

    samples = sorted(
        measurable,
        key=lambda video: video.view_count or 0,
        reverse=True,
    )[:4]

    return EvidenceMetrics(
        video_count=len(videos),
        median_views=_round(median_views, 1),
        relative_to_channel_median=_round(relative, 2),
        lower_quartile_count=tier_counts["low"],
        typical_count=tier_counts["typical"],
        strong_count=tier_counts["strong"],
        exceptional_count=tier_counts["exceptional"],
        exceptional_share_percent=_round(exceptional_share, 1),
        typical_share_percent=_round(typical_share, 1),
        exceptional_vs_typical_lift=_round(lift, 2),
        performance_signal=signal,
        sample_strength=sample_strength,
        sample_videos=[_evidence_ref(video, analysis) for video in samples],
    )


def sanitize_video_ids(video_ids: Sequence[str], analysis: AnalysisResult) -> List[str]:
    valid = {video.video_id for video in analysis.videos}
    return list(dict.fromkeys(video_id for video_id in video_ids if video_id in valid))


def _evidence_ref(video: VideoSnapshot, analysis: AnalysisResult) -> EvidenceVideoRef:
    thumbnail = (
        video.thumbnails.medium
        or video.thumbnails.high
        or video.thumbnails.default
    )
    return EvidenceVideoRef(
        video_id=video.video_id,
        title=video.title,
        views=video.view_count,
        performance_tier=performance_tier(video, analysis),
        thumbnail_url=thumbnail,
        watch_url=video.watch_url,
    )


def _sample_strength(count: int) -> str:
    if count < 3:
        return "Limited sample"
    if count <= 5:
        return "Emerging signal"
    if count <= 9:
        return "Developing signal"
    return "Broad historical support"


def _performance_signal(count: int, relative: float | None) -> str:
    if count < 3 or relative is None:
        return "Limited sample"
    if relative >= 1.5:
        return "Above channel baseline"
    if relative <= 0.67:
        return "Below channel baseline"
    return "Near channel baseline"


def _round(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)
