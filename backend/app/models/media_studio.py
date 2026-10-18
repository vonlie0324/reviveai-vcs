from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.production_brief import CharacterIdentityEvidence, ProductionIdentity, StoryboardPlan
from app.models.recovery import ArchiveMatch


class MediaStudioJobStage(str, Enum):
    QUEUED = "QUEUED"
    GENERATING_REFERENCE = "GENERATING_REFERENCE"
    AWAITING_REFERENCE_APPROVAL = "AWAITING_REFERENCE_APPROVAL"
    GENERATING_KEYFRAMES = "GENERATING_KEYFRAMES"
    REVIEWING_KEYFRAME_FIDELITY = "REVIEWING_KEYFRAME_FIDELITY"
    AWAITING_KEYFRAME_REVIEW = "AWAITING_KEYFRAME_REVIEW"
    READY_FOR_ANIMATION = "READY_FOR_ANIMATION"
    GENERATING_CLIPS = "GENERATING_CLIPS"
    AWAITING_CLIP_REVIEW = "AWAITING_CLIP_REVIEW"
    READY_FOR_ASSEMBLY = "READY_FOR_ASSEMBLY"
    PARTIAL_COMPLETED = "PARTIAL_COMPLETED"
    FAILED = "FAILED"


class MediaAssetKind(str, Enum):
    CHARACTER_REFERENCE = "CHARACTER_REFERENCE"
    KEYFRAME = "KEYFRAME"
    VIDEO_CLIP = "VIDEO_CLIP"


class MediaAssetReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class KeyframeFidelityStatus(str, Enum):
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ADAPTATION_ACCEPTED = "ADAPTATION_ACCEPTED"


class FidelityCheckStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"


class ShotOperationStatus(str, Enum):
    REGENERATING = "REGENERATING"
    FIDELITY_REVIEW = "FIDELITY_REVIEW"
    READY = "READY"
    FAILED = "FAILED"


class ShotOperation(BaseModel):
    shot_number: int
    status: ShotOperationStatus
    message: str
    started_at: datetime
    updated_at: datetime
    target_generation_attempt: int
    previous_review_status: Optional[MediaAssetReviewStatus] = None
    error: Optional[str] = None
    updated_asset_id: Optional[str] = None


class KeyframeFidelityCheck(BaseModel):
    key: str
    label: str
    status: FidelityCheckStatus
    detail: str


class KeyframeFidelityReport(BaseModel):
    shot_number: int
    status: KeyframeFidelityStatus
    checks: List[KeyframeFidelityCheck] = Field(default_factory=list)
    issues: List[str] = Field(default_factory=list)
    corrective_instruction: Optional[str] = None
    evaluated_at: datetime
    model: str
    creator_override: bool = False
    methodology_notice: str = (
        "AI-assisted visual fidelity review compares the generated keyframe with the approved reference and storyboard. It is a review aid, not a calibrated vision score; the creator remains the final approver."
    )


class AiKeyframeFidelity(BaseModel):
    character_identity: FidelityCheckStatus
    wardrobe: FidelityCheckStatus
    setting: FidelityCheckStatus
    primary_prop: FidelityCheckStatus
    supporting_subjects: FidelityCheckStatus
    required_action: FidelityCheckStatus
    camera_framing: FidelityCheckStatus
    camera_angle: FidelityCheckStatus
    issues: List[str] = Field(default_factory=list)
    corrective_instruction: Optional[str] = None




class ClipOperationStatus(str, Enum):
    QUEUED = "QUEUED"
    GENERATING = "GENERATING"
    READY = "READY"
    FAILED = "FAILED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class VideoGenerationChargeStatus(str, Enum):
    CLAIMED = "CLAIMED"
    SUBMITTED = "SUBMITTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class VideoGenerationCharge(BaseModel):
    charge_id: str
    shot_number: int
    generation_attempt: int
    model: str
    resolution: str
    audio_enabled: bool
    requested_duration_seconds: int
    estimated_units: float
    unit_rate_usd: float
    estimated_cost_usd: float
    status: VideoGenerationChargeStatus
    created_at: datetime
    updated_at: datetime
    generation_claim_id: str
    provider_operation_name: Optional[str] = None
    asset_id: Optional[str] = None
    error: Optional[str] = None


class ClipOperation(BaseModel):
    shot_number: int
    status: ClipOperationStatus
    message: str
    started_at: datetime
    updated_at: datetime
    target_generation_attempt: int
    previous_review_status: Optional[MediaAssetReviewStatus] = None
    error: Optional[str] = None
    updated_asset_id: Optional[str] = None
    generation_claim_id: Optional[str] = None
    provider_operation_name: Optional[str] = None
    estimated_units: float = 0.0
    estimated_cost_usd: float = 0.0


class VideoClipAsset(BaseModel):
    asset_id: str
    kind: MediaAssetKind = MediaAssetKind.VIDEO_CLIP
    shot_number: int
    created_at: datetime
    model: str
    mime_type: str = "video/mp4"
    filename: str
    asset_url: str
    prompt: str
    intended_duration_seconds: float
    generated_duration_seconds: int
    source_keyframe_asset_id: str
    gcs_uri: Optional[str] = None
    review_status: MediaAssetReviewStatus = MediaAssetReviewStatus.NEEDS_REVIEW
    generation_attempt: int = 1
    review_note: Optional[str] = None

class MediaSourceSnapshot(BaseModel):
    production_brief_job_id: str
    source_snapshot_id: str
    source_hash: str
    captured_at: datetime
    working_title: str
    production_identity: ProductionIdentity
    storyboard: StoryboardPlan
    closest_archive_matches: List[ArchiveMatch] = Field(default_factory=list)
    character_identity_evidence: Optional[CharacterIdentityEvidence] = None


class MediaAsset(BaseModel):
    asset_id: str
    kind: MediaAssetKind
    shot_number: Optional[int] = None
    created_at: datetime
    model: str
    mime_type: str
    filename: str
    asset_url: str
    gcs_uri: Optional[str] = None
    prompt: str
    review_status: MediaAssetReviewStatus = MediaAssetReviewStatus.NEEDS_REVIEW
    source_reference_asset_id: Optional[str] = None
    generation_attempt: int = 1
    review_note: Optional[str] = None
    identity_grounding_video_ids: List[str] = Field(default_factory=list)
    identity_grounding_images_supplied: int = 0
    fidelity_report: Optional[KeyframeFidelityReport] = None


class MediaStudioResult(BaseModel):
    source_snapshot: MediaSourceSnapshot
    image_model: str
    aspect_ratio: str
    reference_asset: Optional[MediaAsset] = None
    keyframes: List[MediaAsset] = Field(default_factory=list)
    shot_operations: Dict[int, ShotOperation] = Field(default_factory=dict)
    video_model: Optional[str] = None
    video_clips: List[VideoClipAsset] = Field(default_factory=list)
    clip_operations: Dict[int, ClipOperation] = Field(default_factory=dict)
    video_generation_charges: List[VideoGenerationCharge] = Field(default_factory=list)
    approved_clips: int = 0
    required_clips: int = 0
    assembly_ready: bool = False
    reference_approved: bool = False
    approved_keyframes: int = 0
    required_keyframes: int = 0
    fidelity_reviewed_keyframes: int = 0
    fidelity_passed_keyframes: int = 0
    animation_ready: bool = False
    methodology_notice: str = (
        "M2B.2 preserves the approved M2B.1.2 identity/keyframes, animates each approved keyframe with Veo, and keeps clip generation/regeneration local to each shot. Every generated clip still requires human approval before final assembly."
    )


class MediaStudioJob(BaseModel):
    job_id: str
    production_brief_job_id: str
    channel_id: str
    stage: MediaStudioJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 1
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[MediaStudioResult] = None
    error: Optional[str] = None


class AssetReviewRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)


class RegenerateAssetRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=500)
