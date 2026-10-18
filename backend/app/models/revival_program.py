from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.recovery import ChannelOperatingMode, EvidenceStrength


class RevivalContentLane(str, Enum):
    CORE = "CORE"
    ADJACENT = "ADJACENT"
    EXPERIMENT = "EXPERIMENT"


class RevivalIdeaStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    PUBLISHED = "PUBLISHED"


class RevivalProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class RevivalCadenceIntensity(str, Enum):
    AUTO = "AUTO"
    SUSTAINABLE = "SUSTAINABLE"
    BALANCED = "BALANCED"
    ACCELERATED = "ACCELERATED"
    DAILY_SPRINT = "DAILY_SPRINT"


class RevivalContentPillar(BaseModel):
    pillar_id: str
    name: str
    description: str
    source_ideas: List[str] = Field(default_factory=list)


class RevivalProgramIdea(BaseModel):
    idea_id: str
    recommendation_id: str
    title: str
    concept: str
    hook: str
    format: str
    lane: RevivalContentLane
    evidence_strength: EvidenceStrength
    evidence_fit_score: int = Field(ge=0, le=100)
    evidence_fit_label: str
    why_now: str
    strategy_lanes: List[str] = Field(default_factory=list)
    status: RevivalIdeaStatus = RevivalIdeaStatus.PLANNED


class RevivalSlateSlot(BaseModel):
    week: int = Field(ge=1, le=4)
    slot: int = Field(ge=1, le=7)
    cadence_label: str
    idea_id: str


class RevivalWeekdayActivity(BaseModel):
    day: str
    upload_count: int = Field(ge=0)
    share_percent: float = Field(ge=0, le=100)


class RevivalCadenceUpdateRequest(BaseModel):
    intensity: RevivalCadenceIntensity = RevivalCadenceIntensity.AUTO


class RevivalProgram(BaseModel):
    program_id: str
    recovery_job_id: str
    channel_id: str
    channel_title: str
    operating_mode: ChannelOperatingMode = ChannelOperatingMode.REVIVE
    program_label: str = "30-Day Revival"
    program_goal: str = "Re-establish a sustainable publishing rhythm while testing evidence-backed directions."
    historical_evidence_weight: float = Field(default=0.5, ge=0, le=1)
    fresh_evidence_priority: float = Field(default=0.5, ge=0, le=1)
    evidence_freshness_note: str = "Historical evidence is being balanced with newer observations as they become available."
    created_at: datetime
    updated_at: datetime
    status: RevivalProgramStatus = RevivalProgramStatus.ACTIVE
    duration_days: int = 30
    cadence_version: int = 1
    cadence_intensity: RevivalCadenceIntensity = RevivalCadenceIntensity.AUTO
    cadence_per_week: int = Field(ge=1, le=7)
    recommended_cadence_per_week: int = Field(default=2, ge=1, le=7)
    cadence_label: str = "Adaptive"
    schedule_basis: str = "legacy_even_spacing"
    schedule_rationale: str = "This saved plan used the earlier evenly spaced cadence model."
    suggested_days: List[str] = Field(default_factory=list)
    weekday_activity: List[RevivalWeekdayActivity] = Field(default_factory=list)
    backlog_weeks_supported: float = Field(default=0, ge=0)
    backlog_capacity_label: str = "Backlog capacity not calculated"
    backlog_capacity_warning: Optional[str] = None
    target_posts: int = Field(ge=1)
    guidance: str = (
        "This program prioritizes sustainable evidence-backed content operations and continuous learning. "
        "Evidence fit is not a prediction of views, virality, reach, or revenue."
    )
    pillars: List[RevivalContentPillar] = Field(default_factory=list)
    ideas: List[RevivalProgramIdea] = Field(default_factory=list)
    weekly_slate: List[RevivalSlateSlot] = Field(default_factory=list)
