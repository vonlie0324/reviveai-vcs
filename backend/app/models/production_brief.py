from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.content_dna import EvidenceVideoRef
from app.models.recovery import ArchiveMatch, NextContentRecommendation, RecoverySignal


class ProductionBriefJobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPARING_CONTEXT = "PREPARING_CONTEXT"
    BUILDING_CREATIVE_DIRECTION = "BUILDING_CREATIVE_DIRECTION"
    BUILDING_STORYBOARD_OUTLINE = "BUILDING_STORYBOARD_OUTLINE"
    BUILDING_STORYBOARD_PROMPTS = "BUILDING_STORYBOARD_PROMPTS"
    BUILDING_PUBLISHING_PACKAGE = "BUILDING_PUBLISHING_PACKAGE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProductionReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"


class ProductionConsistencyStatus(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class DirectionFidelityStatus(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ADAPTATION_ACCEPTED = "ADAPTATION_ACCEPTED"


class ProductionFidelityMode(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class ProductionBriefRequest(BaseModel):
    recommendation_id: str
    fidelity_mode: ProductionFidelityMode = ProductionFidelityMode.STANDARD


class ProductionBriefRetryRequest(BaseModel):
    fidelity_mode: Optional[ProductionFidelityMode] = None


class SourceDirectionSnapshot(BaseModel):
    snapshot_id: str
    captured_at: datetime
    recovery_job_id: str
    channel_id: str
    channel_title: str
    recovery_generated_at: Optional[datetime] = None
    source_hash: str
    immutable: bool = True
    recommendation: NextContentRecommendation


class ProductionBriefHistoryEntry(BaseModel):
    job_id: str
    channel_id: str
    analysis_job_id: str
    recovery_job_id: str
    captured_at: datetime
    updated_at: datetime
    stage: str
    review_status: Optional[ProductionReviewStatus] = None
    source_snapshot: SourceDirectionSnapshot
    working_title: Optional[str] = None
    consistency_status: Optional[ProductionConsistencyStatus] = None
    direction_fidelity_status: Optional[DirectionFidelityStatus] = None


class DirectionFidelityContract(BaseModel):
    source_title: str
    source_concept: str
    required_characters: List[str] = Field(default_factory=list)
    explicit_subject_count: Optional[int] = None
    core_terms: List[str] = Field(default_factory=list)
    concept_terms: List[str] = Field(default_factory=list)
    source_summary: str


class ProductionIdentity(BaseModel):
    character_name: str
    identity_source: str = "generated"
    subject_count: int = Field(default=1, ge=1, le=8)
    supporting_subjects: List[str] = Field(default_factory=list)
    species_or_subject: str
    appearance: str
    wardrobe: str
    personality: List[str] = Field(default_factory=list)
    primary_prop: str
    setting_anchor: str
    lighting_style: str
    anatomy_rule: str


class CharacterIdentityEvidence(BaseModel):
    """Historical channel appearances used to preserve one recurring character's identity."""

    character_name: str
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    evidence_video_ids: List[str] = Field(default_factory=list)
    source_videos: List[EvidenceVideoRef] = Field(default_factory=list)
    resolved_from_content_dna: bool = False
    selection_basis: str = (
        "Content DNA character evidence ranked toward videos whose public title/metadata explicitly names the character."
    )


class CreativeDirection(BaseModel):
    working_title: str
    creative_objective: str
    one_sentence_promise: str
    opening_hook: str
    narrative_arc: str
    target_duration_seconds: int = Field(ge=6, le=60)
    format: str
    tone: List[str] = Field(default_factory=list)
    production_identity: ProductionIdentity
    character_direction: str
    setting: str
    continuity_rules: List[str] = Field(default_factory=list)
    avoid: List[str] = Field(default_factory=list)
    asset_checklist: List[str] = Field(default_factory=list)


class StoryboardShot(BaseModel):
    shot_number: int
    duration_seconds: float = Field(gt=0, le=20)
    purpose: str
    visual_action: str
    camera_direction: str
    on_screen_text: str = ""
    voiceover_or_dialogue: str = ""
    generation_prompt: str


class StoryboardPlan(BaseModel):
    shots: List[StoryboardShot] = Field(default_factory=list)
    estimated_duration_seconds: float = 0.0
    prompt_generation_mode: str = "gemini"


class PublishingPackage(BaseModel):
    youtube_title: str
    description: str
    social_caption: str
    hashtags: List[str] = Field(default_factory=list)
    thumbnail_concept: str
    audio_direction: str
    accessibility_alt_text: str
    review_notes: List[str] = Field(default_factory=list)


class ConsistencyCheck(BaseModel):
    key: str
    label: str
    status: str
    detail: str


class ConsistencyAnchorSet(BaseModel):
    character_name: str
    setting_terms: List[str] = Field(default_factory=list)
    primary_prop_terms: List[str] = Field(default_factory=list)


class ProductionConsistencyReport(BaseModel):
    status: ProductionConsistencyStatus
    checks: List[ConsistencyCheck] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    anchors: Optional[ConsistencyAnchorSet] = None


class DirectionFidelityCheck(BaseModel):
    key: str
    label: str
    status: str
    source_value: str
    brief_value: str
    detail: str


class DirectionFidelityReport(BaseModel):
    status: DirectionFidelityStatus
    contract: DirectionFidelityContract
    checks: List[DirectionFidelityCheck] = Field(default_factory=list)
    blocking_issues: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    adaptation_accepted: bool = False
    accepted_at: Optional[datetime] = None


class ProductionBriefResult(BaseModel):
    generated_at: datetime
    source_snapshot: SourceDirectionSnapshot
    model: str
    gemini_calls: int
    selected_recommendation: NextContentRecommendation
    creative_direction: CreativeDirection
    storyboard: StoryboardPlan
    publishing: PublishingPackage
    consistency_report: ProductionConsistencyReport
    direction_fidelity: DirectionFidelityReport
    evidence_anchor: List[RecoverySignal] = Field(default_factory=list)
    closest_archive_matches: List[ArchiveMatch] = Field(default_factory=list)
    character_identity_evidence: Optional[CharacterIdentityEvidence] = None
    review_status: ProductionReviewStatus = ProductionReviewStatus.NEEDS_REVIEW
    reviewed_at: Optional[datetime] = None
    creative_firewall_notice: str = (
        "Gemini receives the approved recovery direction, channel identity, tone, and semantically relevant Content DNA labels, but not view counts, medians, or performance tiers while writing the production brief. Performance evidence remains attached separately for human review."
    )
    methodology_notice: str = (
        "M2A turns one human-selected Recovery Intelligence direction into a production brief. The brief is a creative draft for review, not an instruction to auto-publish or a prediction of future performance."
    )


class ProductionBriefJob(BaseModel):
    job_id: str
    source_snapshot: SourceDirectionSnapshot
    channel_id: str
    recovery_job_id: str
    content_dna_job_id: str
    analysis_job_id: str
    recommendation_id: str
    fidelity_mode: ProductionFidelityMode = ProductionFidelityMode.STANDARD
    stage: ProductionBriefJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 5
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[ProductionBriefResult] = None
    error: Optional[str] = None


# Compact structured-output schemas used by Gemini. Performance values are
# deliberately absent so creative generation cannot simply chase historic views.
class AiProductionIdentity(BaseModel):
    character_name: str = Field(max_length=80)
    identity_source: str = Field(max_length=40)
    subject_count: int = Field(default=1, ge=1, le=8)
    supporting_subjects: List[str] = Field(default_factory=list, max_length=7)
    species_or_subject: str = Field(max_length=120)
    appearance: str = Field(max_length=260)
    wardrobe: str = Field(max_length=260)
    personality: List[str] = Field(default_factory=list, max_length=5)
    primary_prop: str = Field(max_length=180)
    setting_anchor: str = Field(max_length=220)
    lighting_style: str = Field(max_length=180)
    anatomy_rule: str = Field(max_length=260)


class AiCreativeDirection(BaseModel):
    working_title: str = Field(max_length=120)
    creative_objective: str = Field(max_length=400)
    one_sentence_promise: str = Field(max_length=280)
    opening_hook: str = Field(max_length=280)
    narrative_arc: str = Field(max_length=500)
    target_duration_seconds: int = Field(ge=6, le=60)
    format: str = Field(
        max_length=100,
        description=(
            "Short production-format label only, not a detailed execution description. "
            "Maximum 100 characters; put execution detail in the other creative-direction fields."
        ),
    )
    tone: List[str] = Field(default_factory=list, max_length=5)
    production_identity: AiProductionIdentity
    character_direction: str = Field(max_length=500)
    setting: str = Field(max_length=350)
    continuity_rules: List[str] = Field(default_factory=list, max_length=8)
    avoid: List[str] = Field(default_factory=list, max_length=7)
    asset_checklist: List[str] = Field(default_factory=list, max_length=10)


class AiStoryboardOutlineShot(BaseModel):
    shot_number: int = Field(ge=1, le=8)
    duration_seconds: float = Field(ge=0.5, le=20)
    purpose: str = Field(max_length=160)
    visual_action: str = Field(max_length=420)
    camera_direction: str = Field(max_length=220)
    on_screen_text: str = Field(default="", max_length=180)
    voiceover_or_dialogue: str = Field(default="", max_length=280)


class AiStoryboardOutline(BaseModel):
    shots: List[AiStoryboardOutlineShot] = Field(default_factory=list, min_length=4, max_length=7)


class AiShotPrompt(BaseModel):
    shot_number: int = Field(ge=1, le=8)
    generation_prompt: str = Field(max_length=1200)


class AiStoryboardPromptPack(BaseModel):
    prompts: List[AiShotPrompt] = Field(default_factory=list, max_length=7)


class AiPublishingPackage(BaseModel):
    youtube_title: str = Field(max_length=120)
    description: str = Field(max_length=1200)
    social_caption: str = Field(max_length=700)
    hashtags: List[str] = Field(default_factory=list, max_length=10)
    thumbnail_concept: str = Field(max_length=500)
    audio_direction: str = Field(max_length=500)
    accessibility_alt_text: str = Field(max_length=700)
    review_notes: List[str] = Field(default_factory=list, max_length=6)
    character_name_used: str = Field(max_length=80)
    setting_anchor_used: str = Field(max_length=220)
    primary_prop_used: str = Field(max_length=180)


class ProductionBriefCheckpoint(BaseModel):
    version: str = "m2a7"
    source_snapshot: Optional[SourceDirectionSnapshot] = None
    fidelity_contract: Optional[DirectionFidelityContract] = None
    creative_direction: Optional[CreativeDirection] = None
    storyboard_outline: Optional[AiStoryboardOutline] = None
    storyboard: Optional[StoryboardPlan] = None
    publishing: Optional[PublishingPackage] = None
    publishing_character_name_used: Optional[str] = None
    publishing_setting_anchor_used: Optional[str] = None
    publishing_primary_prop_used: Optional[str] = None
