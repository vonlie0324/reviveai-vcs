from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ContentDnaJobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPARING_EVIDENCE = "PREPARING_EVIDENCE"
    ANALYZING_VIDEOS = "ANALYZING_VIDEOS"
    SYNTHESIZING_DNA = "SYNTHESIZING_DNA"
    CONNECTING_PERFORMANCE = "CONNECTING_PERFORMANCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CharacterMention(BaseModel):
    name: str
    animal_or_subject: Optional[str] = None
    role: Optional[str] = None


class VideoContentClassification(BaseModel):
    video_id: str
    summary: str
    themes: List[str] = Field(default_factory=list)
    characters: List[CharacterMention] = Field(default_factory=list)
    story_patterns: List[str] = Field(default_factory=list)
    visual_patterns: List[str] = Field(default_factory=list)
    tones: List[str] = Field(default_factory=list)
    content_intent: str = "unknown"
    setting: Optional[str] = None
    human_like_activity: Optional[bool] = None
    confidence: float = 0.0
    evidence_notes: List[str] = Field(default_factory=list)
    visual_evidence_available: bool = False


class EvidenceVideoRef(BaseModel):
    video_id: str
    title: str
    views: Optional[int] = None
    performance_tier: str = "unknown"
    thumbnail_url: Optional[str] = None
    watch_url: str


class EvidenceMetrics(BaseModel):
    video_count: int = 0
    median_views: Optional[float] = None
    relative_to_channel_median: Optional[float] = None
    lower_quartile_count: int = 0
    typical_count: int = 0
    strong_count: int = 0
    exceptional_count: int = 0
    exceptional_share_percent: Optional[float] = None
    typical_share_percent: Optional[float] = None
    exceptional_vs_typical_lift: Optional[float] = None
    performance_signal: str = "Limited sample"
    sample_strength: str = "Limited sample"
    sample_videos: List[EvidenceVideoRef] = Field(default_factory=list)


class ChannelIdentity(BaseModel):
    summary: str
    primary_niche: str
    content_promise: str
    dominant_format: str
    language_style: str
    confidence: float
    evidence_video_ids: List[str] = Field(default_factory=list)


class VoiceToneInsight(BaseModel):
    label: str
    explanation: str
    confidence: float
    evidence_video_ids: List[str] = Field(default_factory=list)
    evidence: EvidenceMetrics = Field(default_factory=EvidenceMetrics)


class GroupInsight(BaseModel):
    name: str
    description: str
    evidence_video_ids: List[str] = Field(default_factory=list)
    evidence: EvidenceMetrics = Field(default_factory=EvidenceMetrics)


class CharacterInsight(BaseModel):
    name: str
    description: str
    aliases: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    evidence_video_ids: List[str] = Field(default_factory=list)
    evidence: EvidenceMetrics = Field(default_factory=EvidenceMetrics)


class ContentDnaResult(BaseModel):
    generated_at: datetime
    model: str
    videos_classified: int
    visuals_analyzed: int
    metadata_only_videos: int
    unclassified_videos: int
    gemini_calls: int
    identity: ChannelIdentity
    voice_tone: List[VoiceToneInsight] = Field(default_factory=list)
    themes: List[GroupInsight] = Field(default_factory=list)
    characters: List[CharacterInsight] = Field(default_factory=list)
    story_patterns: List[GroupInsight] = Field(default_factory=list)
    visual_patterns: List[GroupInsight] = Field(default_factory=list)
    video_classifications: List[VideoContentClassification] = Field(default_factory=list)
    methodology_notice: str = (
        "Gemini classifies content from public titles, descriptions, tags, and thumbnails without seeing view counts or performance tiers. "
        "ReviveAI then connects those classifications to the deterministic M1B.2 metrics. Observed associations are historical correlations, not causal claims."
    )


class ContentDnaJob(BaseModel):
    job_id: str
    analysis_job_id: str
    stage: ContentDnaJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 0
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[ContentDnaResult] = None
    error: Optional[str] = None


# Internal structured-output schemas used by Gemini. These deliberately contain
# no performance numbers so classification is independent from channel results.
class AiVideoClassification(BaseModel):
    video_id: str
    summary: str
    themes: List[str] = Field(default_factory=list)
    characters: List[CharacterMention] = Field(default_factory=list)
    story_patterns: List[str] = Field(default_factory=list)
    visual_patterns: List[str] = Field(default_factory=list)
    tones: List[str] = Field(default_factory=list)
    content_intent: str = "unknown"
    setting: Optional[str] = None
    human_like_activity: Optional[bool] = None
    confidence: float = 0.0
    evidence_notes: List[str] = Field(default_factory=list)


class AiVideoClassificationBatch(BaseModel):
    classifications: List[AiVideoClassification] = Field(default_factory=list)


# M1C.3 channel synthesis is intentionally compact. Gemini normalizes the labels
# already produced by per-video classification, while the backend deterministically
# maps those aliases back to every supporting video_id. This avoids huge repeated
# evidence lists in Gemini output and keeps performance evidence traceable.
class AiIdentityLite(BaseModel):
    summary: str
    primary_niche: str
    content_promise: str
    dominant_format: str
    language_style: str
    confidence: float


class AiCanonicalTone(BaseModel):
    label: str
    explanation: str
    aliases: List[str] = Field(default_factory=list, max_length=8)
    confidence: float


class AiCanonicalGroup(BaseModel):
    name: str
    description: str
    aliases: List[str] = Field(default_factory=list, max_length=6)


class AiCharacterSummary(BaseModel):
    name: str
    description: str
    aliases: List[str] = Field(default_factory=list, max_length=4)
    roles: List[str] = Field(default_factory=list, max_length=6)


class AiIdentityVoiceSynthesis(BaseModel):
    identity: AiIdentityLite
    voice_tone: List[AiCanonicalTone] = Field(default_factory=list, max_length=8)


class AiThemeSynthesis(BaseModel):
    themes: List[AiCanonicalGroup] = Field(default_factory=list, max_length=10)


class AiCharacterSynthesis(BaseModel):
    characters: List[AiCharacterSummary] = Field(default_factory=list, max_length=12)


# Backward-compatible aggregate model retained for tests/checkpoint migration.
class AiThemeCharacterSynthesis(BaseModel):
    themes: List[AiCanonicalGroup] = Field(default_factory=list, max_length=10)
    characters: List[AiCharacterSummary] = Field(default_factory=list, max_length=12)


class AiPatternSynthesis(BaseModel):
    story_patterns: List[AiCanonicalGroup] = Field(default_factory=list, max_length=10)
    visual_patterns: List[AiCanonicalGroup] = Field(default_factory=list, max_length=10)


# Internal normalized synthesis after the backend reconnects canonical aliases to
# exact video IDs. These models are never requested directly from Gemini.
class AiIdentity(BaseModel):
    summary: str
    primary_niche: str
    content_promise: str
    dominant_format: str
    language_style: str
    confidence: float
    evidence_video_ids: List[str] = Field(default_factory=list)


class AiVoiceTone(BaseModel):
    label: str
    explanation: str
    confidence: float
    evidence_video_ids: List[str] = Field(default_factory=list)


class AiGroup(BaseModel):
    name: str
    description: str
    evidence_video_ids: List[str] = Field(default_factory=list)


class AiCharacterGroup(BaseModel):
    name: str
    description: str
    aliases: List[str] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    evidence_video_ids: List[str] = Field(default_factory=list)


class AiChannelSynthesis(BaseModel):
    identity: AiIdentity
    voice_tone: List[AiVoiceTone] = Field(default_factory=list)
    themes: List[AiGroup] = Field(default_factory=list)
    characters: List[AiCharacterGroup] = Field(default_factory=list)
    story_patterns: List[AiGroup] = Field(default_factory=list)
    visual_patterns: List[AiGroup] = Field(default_factory=list)
