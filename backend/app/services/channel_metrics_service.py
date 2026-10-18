from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median
from typing import Iterable, List, Optional, Sequence

from app.models.youtube import (
    CadenceMetrics,
    ChannelMetrics,
    DistributionMetrics,
    DurationPerformanceBand,
    EngagementMetrics,
    MonthlyUploadPoint,
    PerformanceTier,
    RankedVideoMetric,
    RecencyComparison,
    VideoSnapshot,
)
from app.services.time_utils import utc_calendar_day_gap


class ChannelMetricsService:
    """Deterministic public-data metrics used by M1B.

    Gemini is intentionally not involved here. These metrics are the evidence layer
    that later AI interpretation will consume.
    """

    def build(
        self,
        videos: Sequence[VideoSnapshot],
        *,
        now: Optional[datetime] = None,
    ) -> ChannelMetrics:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

        view_values = sorted(
            int(video.view_count)
            for video in videos
            if video.view_count is not None and video.view_count >= 0
        )
        distribution = self._distribution(view_values)
        tiers = self._performance_tiers(view_values, distribution)
        engagement = self._engagement(videos)
        cadence = self._cadence(videos, now)
        duration_bands = self._duration_bands(videos)
        top_videos, bottom_videos = self._ranked_videos(videos, distribution.median)
        recency = self._recency_comparison(videos, now)

        return ChannelMetrics(
            views=distribution,
            performance_tiers=tiers,
            engagement=engagement,
            cadence=cadence,
            duration_bands=duration_bands,
            top_videos=top_videos,
            bottom_videos=bottom_videos,
            recency=recency,
        )

    def _distribution(self, values: Sequence[int]) -> DistributionMetrics:
        if not values:
            return DistributionMetrics()

        q25 = _percentile(values, 25)
        q75 = _percentile(values, 75)
        q90 = _percentile(values, 90)
        q95 = _percentile(values, 95)
        iqr = q75 - q25
        outlier_threshold = q75 + 1.5 * iqr

        return DistributionMetrics(
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            mean=_round(mean(values), 1),
            median=_round(median(values), 1),
            p25=_round(q25, 1),
            p75=_round(q75, 1),
            p90=_round(q90, 1),
            p95=_round(q95, 1),
            iqr=_round(iqr, 1),
            high_outlier_threshold=_round(outlier_threshold, 1),
            high_outlier_count=sum(1 for value in values if value > outlier_threshold),
        )

    def _performance_tiers(
        self,
        values: Sequence[int],
        distribution: DistributionMetrics,
    ) -> List[PerformanceTier]:
        if not values or distribution.p25 is None or distribution.p75 is None or distribution.p90 is None:
            return []

        p25 = distribution.p25
        p75 = distribution.p75
        p90 = distribution.p90

        counts = {
            "low": sum(1 for value in values if value < p25),
            "typical": sum(1 for value in values if p25 <= value < p75),
            "strong": sum(1 for value in values if p75 <= value < p90),
            "exceptional": sum(1 for value in values if value >= p90),
        }

        return [
            PerformanceTier(
                key="low",
                label="Lower quartile",
                count=counts["low"],
                max_exclusive=p25,
                description="Below the channel's 25th percentile of public lifetime views.",
            ),
            PerformanceTier(
                key="typical",
                label="Typical range",
                count=counts["typical"],
                min_inclusive=p25,
                max_exclusive=p75,
                description="The middle 50% of the channel's public lifetime views.",
            ),
            PerformanceTier(
                key="strong",
                label="Strong",
                count=counts["strong"],
                min_inclusive=p75,
                max_exclusive=p90,
                description="Between the 75th and 90th percentile for this channel.",
            ),
            PerformanceTier(
                key="exceptional",
                label="Exceptional",
                count=counts["exceptional"],
                min_inclusive=p90,
                description="At or above the channel's 90th percentile.",
            ),
        ]

    def _engagement(self, videos: Sequence[VideoSnapshot]) -> EngagementMetrics:
        like_videos = [
            video for video in videos
            if video.view_count is not None and video.view_count > 0 and video.like_count is not None
        ]
        comment_videos = [
            video for video in videos
            if video.view_count is not None and video.view_count > 0 and video.comment_count is not None
        ]
        view_coverage = sum(1 for video in videos if video.view_count is not None)

        like_views = sum(video.view_count or 0 for video in like_videos)
        comment_views = sum(video.view_count or 0 for video in comment_videos)
        likes = sum(video.like_count or 0 for video in like_videos)
        comments = sum(video.comment_count or 0 for video in comment_videos)

        return EngagementMetrics(
            likes_per_1000_views=_safe_rate(likes, like_views, 1000),
            comments_per_1000_views=_safe_rate(comments, comment_views, 1000),
            like_coverage_videos=len(like_videos),
            comment_coverage_videos=len(comment_videos),
            view_coverage_videos=view_coverage,
        )

    def _cadence(self, videos: Sequence[VideoSnapshot], now: datetime) -> CadenceMetrics:
        dates = sorted(
            video.published_at.astimezone(timezone.utc)
            for video in videos
            if video.published_at is not None
        )
        if not dates:
            return CadenceMetrics()

        monthly_counter = Counter(date.strftime("%Y-%m") for date in dates)
        monthly_uploads = _monthly_points(dates[-1], monthly_counter, months=12)
        current_gap = utc_calendar_day_gap(dates[-1], now)

        # M1B.2 cadence is based on active publishing days, not individual uploads.
        # This prevents burst publishing (multiple uploads on one date) from turning
        # the channel's normal cadence into a misleading 0-day median gap.
        uploads_by_day = Counter(date.date() for date in dates)
        active_days = sorted(uploads_by_day)
        active_day_count = len(active_days)
        typical_uploads_per_active_day = float(median(uploads_by_day.values()))
        publishing_style = _publishing_style(typical_uploads_per_active_day)

        active_span_days = max(0, (active_days[-1] - active_days[0]).days)
        uploads_per_30 = None
        active_days_per_30 = None
        if active_span_days > 0:
            uploads_per_30 = ((len(dates) - 1) / active_span_days) * 30
            active_days_per_30 = ((active_day_count - 1) / active_span_days) * 30

        if active_day_count < 2:
            return CadenceMetrics(
                dated_videos=len(dates),
                active_publishing_days=active_day_count,
                active_span_days=active_span_days,
                historical_uploads_per_30_days=_round(uploads_per_30, 1),
                active_days_per_30_days=_round(active_days_per_30, 1),
                typical_uploads_per_active_day=_round(typical_uploads_per_active_day, 1),
                publishing_style=publishing_style,
                current_gap_days=current_gap,
                monthly_uploads=monthly_uploads,
            )

        gaps = sorted((later - earlier).days for earlier, later in zip(active_days, active_days[1:]))
        median_gap = float(median(gaps))
        p75_gap = _percentile(gaps, 75)
        p90_gap = _percentile(gaps, 90)
        longest_gap = max(gaps)

        current_vs_median = current_gap / median_gap if median_gap > 0 else None
        current_vs_historical_max = current_gap / longest_gap if longest_gap > 0 else None

        status, label, explanation = _dormancy_status(
            current_gap=current_gap,
            median_gap=median_gap,
            p90_gap=p90_gap,
        )

        return CadenceMetrics(
            dated_videos=len(dates),
            active_publishing_days=active_day_count,
            active_span_days=active_span_days,
            historical_uploads_per_30_days=_round(uploads_per_30, 1),
            active_days_per_30_days=_round(active_days_per_30, 1),
            typical_uploads_per_active_day=_round(typical_uploads_per_active_day, 1),
            publishing_style=publishing_style,
            median_active_day_gap_days=_round(median_gap, 1),
            p75_active_day_gap_days=_round(p75_gap, 1),
            p90_active_day_gap_days=_round(p90_gap, 1),
            longest_historical_active_day_gap_days=longest_gap,
            current_gap_days=current_gap,
            current_gap_vs_median_active_day_gap=_round(current_vs_median, 1),
            current_gap_vs_historical_max=_round(current_vs_historical_max, 1),
            status=status,
            status_label=label,
            status_explanation=explanation,
            monthly_uploads=monthly_uploads,
        )

    def _duration_bands(self, videos: Sequence[VideoSnapshot]) -> List[DurationPerformanceBand]:
        definitions = [
            ("short", "≤ 60 sec", 1, 60),
            ("brief", "61 sec–3 min", 61, 180),
            ("medium", "3–10 min", 181, 600),
            ("long", "> 10 min", 601, None),
        ]
        result: List[DurationPerformanceBand] = []
        for key, label, minimum, maximum in definitions:
            matching = [
                video for video in videos
                if video.duration_seconds >= minimum
                and (maximum is None or video.duration_seconds <= maximum)
            ]
            views = [video.view_count for video in matching if video.view_count is not None]
            result.append(
                DurationPerformanceBand(
                    key=key,
                    label=label,
                    min_seconds=minimum,
                    max_seconds=maximum,
                    video_count=len(matching),
                    median_views=_round(median(views), 1) if views else None,
                    mean_views=_round(mean(views), 1) if views else None,
                    total_views=sum(views),
                )
            )
        return result

    def _ranked_videos(
        self,
        videos: Sequence[VideoSnapshot],
        median_views: Optional[float],
    ) -> tuple[List[RankedVideoMetric], List[RankedVideoMetric]]:
        measurable = [video for video in videos if video.view_count is not None]
        if not measurable:
            return [], []

        top = sorted(measurable, key=lambda video: video.view_count or 0, reverse=True)[:5]
        bottom = sorted(measurable, key=lambda video: video.view_count or 0)[:5]
        return (
            [self._ranked_video(video, median_views) for video in top],
            [self._ranked_video(video, median_views) for video in bottom],
        )

    @staticmethod
    def _ranked_video(video: VideoSnapshot, median_views: Optional[float]) -> RankedVideoMetric:
        relative = None
        if median_views and median_views > 0 and video.view_count is not None:
            relative = video.view_count / median_views
        thumbnail = (
            video.thumbnails.medium
            or video.thumbnails.high
            or video.thumbnails.default
        )
        return RankedVideoMetric(
            video_id=video.video_id,
            title=video.title,
            published_at=video.published_at,
            duration_seconds=video.duration_seconds,
            views=video.view_count or 0,
            likes=video.like_count,
            comments=video.comment_count,
            relative_to_median=_round(relative, 2),
            watch_url=video.watch_url,
            thumbnail_url=thumbnail,
        )

    def _recency_comparison(self, videos: Sequence[VideoSnapshot], now: datetime) -> RecencyComparison:
        dated = sorted(
            [video for video in videos if video.published_at is not None and video.view_count is not None],
            key=lambda video: video.published_at,
            reverse=True,
        )
        if len(dated) < 4:
            return RecencyComparison()

        recent_count = min(20, max(5, round(len(dated) * 0.25)))
        recent = dated[:recent_count]
        older = dated[recent_count:]
        if not older:
            return RecencyComparison()

        recent_median = float(median([video.view_count or 0 for video in recent]))
        older_median = float(median([video.view_count or 0 for video in older]))
        ratio = recent_median / older_median if older_median > 0 else None

        def views_per_published_day(video: VideoSnapshot) -> float:
            published = video.published_at.astimezone(timezone.utc)
            age_days = max(1, (now.date() - published.date()).days)
            return (video.view_count or 0) / age_days

        recent_age_normalized = float(median([views_per_published_day(video) for video in recent]))
        older_age_normalized = float(median([views_per_published_day(video) for video in older]))
        age_ratio = recent_age_normalized / older_age_normalized if older_age_normalized > 0 else None

        return RecencyComparison(
            recent_video_count=len(recent),
            older_video_count=len(older),
            recent_median_views=_round(recent_median, 1),
            older_median_views=_round(older_median, 1),
            recent_to_older_ratio=_round(ratio, 2),
            recent_median_views_per_published_day=_round(recent_age_normalized, 2),
            older_median_views_per_published_day=_round(older_age_normalized, 2),
            age_normalized_ratio=_round(age_ratio, 2),
        )


def _percentile(values: Sequence[int] | Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


def _round(value: Optional[float], digits: int) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_rate(numerator: int, denominator: int, multiplier: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * multiplier, 2)


def _publishing_style(typical_uploads_per_active_day: float) -> str:
    if typical_uploads_per_active_day >= 2:
        return "Burst publishing"
    return "Steady publishing"


def _dormancy_status(*, current_gap: int, median_gap: float, p90_gap: float) -> tuple[str, str, str]:
    historical_reference = max(p90_gap, median_gap * 2, 1)

    if current_gap >= 30 and current_gap > historical_reference * 2:
        return (
            "dormant",
            "Dormant",
            "The current inactive period is at least 30 days and more than twice the channel's historical 90th-percentile gap between active publishing days.",
        )
    if current_gap > historical_reference:
        return (
            "slowing",
            "Publishing slowed",
            "The current inactive period is longer than the channel's historical 90th-percentile gap between active publishing days.",
        )
    return (
        "within_pattern",
        "Within historical pattern",
        "The current inactive period remains within the channel's historical gap range between active publishing days.",
    )


def _monthly_points(latest: datetime, counter: Counter, *, months: int) -> List[MonthlyUploadPoint]:
    year = latest.year
    month = latest.month
    points: List[MonthlyUploadPoint] = []
    for offset in range(months - 1, -1, -1):
        shifted_year, shifted_month = _shift_month(year, month, -offset)
        key = f"{shifted_year:04d}-{shifted_month:02d}"
        points.append(MonthlyUploadPoint(month=key, upload_count=counter.get(key, 0)))
    return points


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    zero_based = year * 12 + (month - 1) + delta
    return zero_based // 12, zero_based % 12 + 1
