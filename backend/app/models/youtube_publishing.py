from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class YouTubeConnection(BaseModel):
    connected: bool = False
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    connected_at: Optional[datetime] = None
    scopes: list[str] = Field(default_factory=list)


class YouTubePublishStatus(str, Enum):
    UPLOADING = "UPLOADING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"


class YouTubePublishRequest(BaseModel):
    package_id: str
    publishing_draft_id: str
    recommendation_id: str
    program_id: Optional[str] = None
    production_job_id: Optional[str] = None
    media_job_id: Optional[str] = None
    assembly_job_id: Optional[str] = None
    audio_job_id: Optional[str] = None
    privacy_status: str = "private"
    publish_at: Optional[datetime] = None
    recommended_public_date: Optional[str] = None
    made_for_kids: bool = False
    contains_synthetic_media: bool = True
    schedule_reason: Optional[str] = None
    autonomous: bool = False


class YouTubePublication(BaseModel):
    publication_id: str
    package_id: str
    publishing_draft_id: str
    recommendation_id: str
    program_id: Optional[str] = None
    production_job_id: Optional[str] = None
    media_job_id: Optional[str] = None
    assembly_job_id: Optional[str] = None
    audio_job_id: Optional[str] = None
    video_title: Optional[str] = None
    master_fingerprint: Optional[str] = None
    superseded_by_publication_id: Optional[str] = None
    superseded_at: Optional[datetime] = None
    youtube_video_id: Optional[str] = None
    youtube_url: Optional[str] = None
    status: YouTubePublishStatus
    privacy_status: str
    publish_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    recommended_public_date: Optional[str] = None
    public_confirmed_at: Optional[datetime] = None
    # First verification time is retained for audit. Performance uses the
    # separately resolved release time, including for previously published rows.
    public_release_at: Optional[datetime] = None
    public_release_time_source: Optional[Literal["YOUTUBE", "SCHEDULE_ESTIMATE", "CONFIRMATION"]] = None
    release_clock_version: int = 1
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    error: Optional[str] = None

    # Autonomous publishing/recovery metadata. The resumable-session URI is a
    # capability URL and is therefore persisted only inside the tenant-scoped
    # Firestore payload; it is never included in activity-log details.
    autonomous: bool = False
    autonomous_final_approved_at: Optional[datetime] = None
    schedule_reason: Optional[str] = None
    upload_session_uri: Optional[str] = None
    upload_bytes_total: int = 0
    upload_bytes_committed: int = 0
    upload_started_at: Optional[datetime] = None
    upload_completed_at: Optional[datetime] = None
    last_reconciled_at: Optional[datetime] = None
    retry_count: int = 0
    made_for_kids: bool = False
    contains_synthetic_media: bool = True


MetricStatus = Literal["UNVERIFIED", "PENDING", "PARTIAL", "READY", "ERROR"]


class YouTubePerformanceSnapshot(BaseModel):
    checkpoint: str
    # Original capture time remains stable when delayed evidence is reconciled.
    observed_at: datetime = Field(default_factory=utc_now)
    age_hours: float = 0
    public_release_at: Optional[datetime] = None
    views: Optional[int] = None
    estimated_minutes_watched: Optional[float] = None
    average_view_duration_seconds: Optional[float] = None
    average_percentage_viewed: Optional[float] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    subscribers_gained: Optional[int] = None
    subscribers_lost: Optional[int] = None
    evidence_version: int = 1
    statistics_status: MetricStatus = "UNVERIFIED"
    analytics_status: MetricStatus = "UNVERIFIED"
    statistics_source: Optional[str] = None
    analytics_source: Optional[str] = None
    statistics_observed_at: Optional[datetime] = None
    analytics_last_checked_at: Optional[datetime] = None
    analytics_observed_at: Optional[datetime] = None
    analytics_start_date: Optional[str] = None
    analytics_end_date: Optional[str] = None
    analytics_views: Optional[int] = None
    statistics_error: Optional[str] = None
    analytics_error: Optional[str] = None
    statistics_response: Optional[dict] = None
    analytics_response: Optional[dict] = None
    reconciled_at: Optional[datetime] = None
    retry_count: int = 0
    next_retry_at: Optional[datetime] = None
    retry_deadline_at: Optional[datetime] = None
    learning_synced: bool = False
    # Counters from a later fetch cannot recreate an exact historical 1H/24H count.
    statistics_is_late: bool = False

    @model_validator(mode="before")
    @classmethod
    def quarantine_legacy_zeros(cls, value):
        if isinstance(value, dict) and int(value.get("evidence_version") or 1) < 2:
            value = dict(value)
            value["statistics_status"] = "UNVERIFIED"
            value["analytics_status"] = "UNVERIFIED"
            for name in ("views", "likes", "comments", "estimated_minutes_watched",
                         "average_view_duration_seconds", "average_percentage_viewed",
                         "shares", "subscribers_gained", "subscribers_lost"):
                if value.get(name) == 0:
                    value[name] = None
        return value

    @property
    def statistics_ready(self) -> bool:
        return self.evidence_version >= 2 and self.statistics_status == "READY" and self.views is not None

    @property
    def learning_ready(self) -> bool:
        return (self.statistics_ready and self.analytics_status == "READY"
                and self.average_percentage_viewed is not None
                and self.shares is not None and self.subscribers_gained is not None
                and self.subscribers_lost is not None)


class YouTubePublicationDetail(BaseModel):
    publication: YouTubePublication
    snapshots: list[YouTubePerformanceSnapshot] = Field(default_factory=list)
