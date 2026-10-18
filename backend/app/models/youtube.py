from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class JobStage(str, Enum):
    QUEUED = "QUEUED"
    RESOLVING_CHANNEL = "RESOLVING_CHANNEL"
    READING_UPLOADS = "READING_UPLOADS"
    FETCHING_VIDEO_DETAILS = "FETCHING_VIDEO_DETAILS"
    COMPUTING_METRICS = "COMPUTING_METRICS"
    PREPARING_SNAPSHOT = "PREPARING_SNAPSHOT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalyzeRequest(BaseModel):
    url: str = Field(min_length=3, max_length=2048)


class ThumbnailSet(BaseModel):
    default: Optional[str] = None
    medium: Optional[str] = None
    high: Optional[str] = None
    standard: Optional[str] = None
    maxres: Optional[str] = None


class ChannelSnapshot(BaseModel):
    channel_id: str
    title: str
    description: str = ""
    custom_url: Optional[str] = None
    published_at: Optional[datetime] = None
    country: Optional[str] = None
    thumbnails: ThumbnailSet = Field(default_factory=ThumbnailSet)
    subscriber_count: Optional[int] = None
    subscriber_count_hidden: bool = False
    lifetime_view_count: Optional[int] = None
    public_video_count_reported: Optional[int] = None
    uploads_playlist_id: str
    channel_url: str


class VideoSnapshot(BaseModel):
    video_id: str
    title: str
    description: str = ""
    published_at: Optional[datetime] = None
    thumbnails: ThumbnailSet = Field(default_factory=ThumbnailSet)
    duration_seconds: int = 0
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    category_id: Optional[str] = None
    default_language: Optional[str] = None
    default_audio_language: Optional[str] = None
    captions_available: bool = False
    definition: Optional[str] = None
    live_broadcast_content: Optional[str] = None
    watch_url: str


class IngestionSummary(BaseModel):
    retrieved_videos: int
    analysis_snapshot_at: Optional[datetime] = None
    latest_upload_at: Optional[datetime] = None
    days_since_latest_upload: Optional[int] = None
    videos_le_60_seconds: int = 0
    videos_le_180_seconds: int = 0
    total_retrieved_views: int = 0
    total_retrieved_likes: int = 0
    total_retrieved_comments: int = 0
    youtube_api_requests: int = 0
    retrieval_limit_applied: bool = False


class DistributionMetrics(BaseModel):
    count: int = 0
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    mean: Optional[float] = None
    median: Optional[float] = None
    p25: Optional[float] = None
    p75: Optional[float] = None
    p90: Optional[float] = None
    p95: Optional[float] = None
    iqr: Optional[float] = None
    high_outlier_threshold: Optional[float] = None
    high_outlier_count: int = 0


class PerformanceTier(BaseModel):
    key: str
    label: str
    count: int
    min_inclusive: Optional[float] = None
    max_exclusive: Optional[float] = None
    description: str


class EngagementMetrics(BaseModel):
    likes_per_1000_views: Optional[float] = None
    comments_per_1000_views: Optional[float] = None
    like_coverage_videos: int = 0
    comment_coverage_videos: int = 0
    view_coverage_videos: int = 0


class MonthlyUploadPoint(BaseModel):
    month: str
    upload_count: int


class CadenceMetrics(BaseModel):
    dated_videos: int = 0
    active_publishing_days: int = 0
    active_span_days: Optional[int] = None
    historical_uploads_per_30_days: Optional[float] = None
    active_days_per_30_days: Optional[float] = None
    typical_uploads_per_active_day: Optional[float] = None
    publishing_style: str = "Insufficient history"
    median_active_day_gap_days: Optional[float] = None
    p75_active_day_gap_days: Optional[float] = None
    p90_active_day_gap_days: Optional[float] = None
    longest_historical_active_day_gap_days: Optional[int] = None
    current_gap_days: Optional[int] = None
    current_gap_vs_median_active_day_gap: Optional[float] = None
    current_gap_vs_historical_max: Optional[float] = None
    status: str = "insufficient_data"
    status_label: str = "Insufficient history"
    status_explanation: str = "Not enough active publishing days to establish a historical cadence."
    monthly_uploads: List[MonthlyUploadPoint] = Field(default_factory=list)


class DurationPerformanceBand(BaseModel):
    key: str
    label: str
    min_seconds: int
    max_seconds: Optional[int] = None
    video_count: int
    median_views: Optional[float] = None
    mean_views: Optional[float] = None
    total_views: int = 0


class RankedVideoMetric(BaseModel):
    video_id: str
    title: str
    published_at: Optional[datetime] = None
    duration_seconds: int = 0
    views: int
    likes: Optional[int] = None
    comments: Optional[int] = None
    relative_to_median: Optional[float] = None
    watch_url: str
    thumbnail_url: Optional[str] = None


class RecencyComparison(BaseModel):
    recent_video_count: int = 0
    older_video_count: int = 0
    recent_median_views: Optional[float] = None
    older_median_views: Optional[float] = None
    recent_to_older_ratio: Optional[float] = None
    recent_median_views_per_published_day: Optional[float] = None
    older_median_views_per_published_day: Optional[float] = None
    age_normalized_ratio: Optional[float] = None
    note: str = (
        "Lifetime public views favor older uploads because they have had more time to accumulate views. "
        "Views per published day is included only as a rough age-normalized public proxy; it is not equivalent to first-day or retention analytics."
    )


class ChannelMetrics(BaseModel):
    views: DistributionMetrics
    performance_tiers: List[PerformanceTier] = Field(default_factory=list)
    engagement: EngagementMetrics
    cadence: CadenceMetrics
    duration_bands: List[DurationPerformanceBand] = Field(default_factory=list)
    top_videos: List[RankedVideoMetric] = Field(default_factory=list)
    bottom_videos: List[RankedVideoMetric] = Field(default_factory=list)
    recency: RecencyComparison
    metrics_notice: str = (
        "M1B.2 metrics are deterministic calculations from public YouTube Data API fields. "
        "They do not include owner-only watch time, retention, impressions, CTR, or audience demographics."
    )


class AnalysisResult(BaseModel):
    channel: ChannelSnapshot
    summary: IngestionSummary
    metrics: ChannelMetrics
    videos: List[VideoSnapshot]
    data_scope_notice: str = (
        "Public YouTube Data API data only. Owner-only analytics such as watch time, "
        "retention, impressions, CTR, and audience demographics are not included."
    )


class AnalysisJob(BaseModel):
    job_id: str
    url: str
    stage: JobStage
    message: str
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[AnalysisResult] = None
    error: Optional[str] = None
