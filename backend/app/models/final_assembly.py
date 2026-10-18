from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.production_brief import PublishingPackage


class FinalAssemblyJobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class FinalAssemblyReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"


class AssemblyAssetKind(str, Enum):
    FINAL_VIDEO = "FINAL_VIDEO"
    SUBTITLES = "SUBTITLES"
    AUDIO_MIX = "AUDIO_MIX"


class AssemblyAsset(BaseModel):
    asset_id: str
    kind: AssemblyAssetKind
    created_at: datetime
    filename: str
    mime_type: str
    asset_url: str
    gcs_uri: Optional[str] = None


class AssemblyTimelineItem(BaseModel):
    shot_number: int
    source_clip_asset_id: str
    source_generation_attempt: int
    storyboard_duration_seconds: float
    source_duration_seconds: int
    output_duration_seconds: float
    on_screen_text: str = ""
    voiceover_or_dialogue: str = ""


class FinalAssemblyResult(BaseModel):
    media_job_id: str
    production_brief_job_id: str
    working_title: str
    rendered_at: datetime
    total_duration_seconds: float
    timeline: List[AssemblyTimelineItem] = Field(default_factory=list)
    final_video: AssemblyAsset
    subtitles: Optional[AssemblyAsset] = None
    publishing: PublishingPackage
    review_status: FinalAssemblyReviewStatus = FinalAssemblyReviewStatus.NEEDS_REVIEW
    reviewed_at: Optional[datetime] = None
    captions_burned_in: bool = True
    audio_mode: str = "SILENT_MASTER"
    methodology_notice: str = (
        "M2C.1.2 trims and sequences only human-approved Veo clips, preserves storyboard timing, and burns approved on-screen text into a deterministic visual master. "
        "A silent AAC track is included for compatibility; the M2A audio direction is preserved for a later soundtrack/voice mix rather than being invented automatically."
    )


class FinalAssemblyJob(BaseModel):
    job_id: str
    media_job_id: str
    production_brief_job_id: str
    channel_id: str
    stage: FinalAssemblyJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 1
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[FinalAssemblyResult] = None
    error: Optional[str] = None
