from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.content_dna import EvidenceMetrics, EvidenceVideoRef


class ChannelOperatingMode(str, Enum):
    DISCOVER = "DISCOVER"
    SUSTAIN = "SUSTAIN"
    RECOVER = "RECOVER"
    REVIVE = "REVIVE"


class ChannelStrategyContext(BaseModel):
    mode: ChannelOperatingMode
    label: str
    reason: str
    days_since_latest_upload: Optional[int] = None
    historical_evidence_weight: float = Field(ge=0, le=1)
    fresh_evidence_priority: float = Field(ge=0, le=1)
    historical_confidence_label: str
    guidance: str


class EvidenceStrength(str, Enum):
    STRONG = "STRONG"
    SUPPORTED = "SUPPORTED"
    EXPLORATORY = "EXPLORATORY"


class GapOpportunityStrength(str, Enum):
    EVIDENCE_BACKED_GAP = "EVIDENCE_BACKED_GAP"
    ADJACENT_OPPORTUNITY = "ADJACENT_OPPORTUNITY"
    EMERGING_OPPORTUNITY = "EMERGING_OPPORTUNITY"


class RecoveryJobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPARING_SIGNALS = "PREPARING_SIGNALS"
    DISCOVERING_GAPS = "DISCOVERING_GAPS"
    FINDING_REVIVALS = "FINDING_REVIVALS"
    BUILDING_RECOMMENDATIONS = "BUILDING_RECOMMENDATIONS"
    VALIDATING_EVIDENCE = "VALIDATING_EVIDENCE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RecoverySignal(BaseModel):
    kind: str
    name: str
    description: str = ""
    evidence: EvidenceMetrics = Field(default_factory=EvidenceMetrics)


class ArchiveMatch(BaseModel):
    video: EvidenceVideoRef
    similarity: float
    similarity_label: str


class CanonicalRecoveryIdea(BaseModel):
    idea_id: str
    canonical_title: str
    concept: str
    evidence_strength: EvidenceStrength
    evidence_signals: List[RecoverySignal] = Field(default_factory=list)
    novelty_label: str
    novelty_score: float
    closest_archive_matches: List[ArchiveMatch] = Field(default_factory=list)
    roles: List[str] = Field(default_factory=list)
    strategy_lanes: List[str] = Field(default_factory=list)


class ContentGapOpportunity(BaseModel):
    gap_id: str
    canonical_idea_id: Optional[str] = None
    selected_for_recovery_plan: bool = False
    title: str
    concept: str
    why_it_fits: str
    novelty_label: str
    novelty_score: float
    evidence_strength: EvidenceStrength
    opportunity_strength: GapOpportunityStrength
    evidence_signals: List[RecoverySignal] = Field(default_factory=list)
    closest_archive_matches: List[ArchiveMatch] = Field(default_factory=list)
    caution: str = ""


class RevivalOpportunity(BaseModel):
    revival_id: str
    source_video: EvidenceVideoRef
    source_age_days: Optional[int] = None
    source_summary: str
    revival_angle: str
    why_revive: str
    evidence_strength: EvidenceStrength
    evidence_signals: List[RecoverySignal] = Field(default_factory=list)


class NextContentRecommendation(BaseModel):
    rank: int
    canonical_idea_id: Optional[str] = None
    recommendation_id: str
    title: str
    concept: str
    hook: str
    format: str
    why_this_fits: str
    recommended_characters: List[str] = Field(default_factory=list)
    evidence_strength: EvidenceStrength
    evidence_signals: List[RecoverySignal] = Field(default_factory=list)
    novelty_label: str
    novelty_score: float
    closest_archive_matches: List[ArchiveMatch] = Field(default_factory=list)
    strategy_lanes: List[str] = Field(default_factory=list)
    diversity_note: str = ""
    guardrail: str = (
        "This is an evidence-backed creative direction, not a prediction of future performance."
    )


class RecoveryResult(BaseModel):
    generated_at: datetime
    strategy: ChannelStrategyContext = Field(default_factory=lambda: ChannelStrategyContext(
        mode=ChannelOperatingMode.REVIVE,
        label="Revival",
        reason="Legacy saved intelligence predates lifecycle diagnosis; regenerate intelligence to refresh this classification.",
        historical_evidence_weight=0.5,
        fresh_evidence_priority=0.5,
        historical_confidence_label="Legacy / refresh recommended",
        guidance="Use historical evidence cautiously until channel strategy is regenerated.",
    ))
    model: str
    gemini_calls: int
    top_signals: List[RecoverySignal] = Field(default_factory=list)
    canonical_ideas: List[CanonicalRecoveryIdea] = Field(default_factory=list)
    content_gaps: List[ContentGapOpportunity] = Field(default_factory=list)
    revival_opportunities: List[RevivalOpportunity] = Field(default_factory=list)
    recommendations: List[NextContentRecommendation] = Field(default_factory=list)
    methodology_notice: str = (
        "ReviveAI uses historical Content DNA plus deterministic public-performance evidence to form channel-strategy hypotheses. "
        "Gemini proposes creative directions from those evidence-linked signals; the backend then canonicalizes equivalent ideas, checks archive similarity, filters evidence for idea-specific semantic relevance, reconnects exact supporting evidence, and applies diversity caps to the final recovery plan. "
        "Historical association does not imply causation and recommendations do not guarantee future performance."
    )


class RecoveryJob(BaseModel):
    job_id: str
    content_dna_job_id: str
    analysis_job_id: str
    stage: RecoveryJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 5
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[RecoveryResult] = None
    error: Optional[str] = None


# Compact structured-output schemas used by Gemini. Exact performance evidence
# is reattached by ReviveAI after generation.
class AiGapSuggestion(BaseModel):
    title: str
    concept: str
    why_it_fits: str
    evidence_ingredients: List[str] = Field(default_factory=list, max_length=5)


class AiGapSuggestionBatch(BaseModel):
    items: List[AiGapSuggestion] = Field(default_factory=list, max_length=8)


class AiRevivalSuggestion(BaseModel):
    source_video_id: str
    revival_angle: str
    why_revive: str
    evidence_ingredients: List[str] = Field(default_factory=list, max_length=5)


class AiRevivalSuggestionBatch(BaseModel):
    items: List[AiRevivalSuggestion] = Field(default_factory=list, max_length=6)


class AiRecommendationSuggestion(BaseModel):
    title: str
    concept: str
    hook: str
    format: str
    why_this_fits: str
    recommended_characters: List[str] = Field(default_factory=list, max_length=3)
    evidence_ingredients: List[str] = Field(default_factory=list, max_length=6)


class AiRecommendationSuggestionBatch(BaseModel):
    items: List[AiRecommendationSuggestion] = Field(default_factory=list, max_length=10)
