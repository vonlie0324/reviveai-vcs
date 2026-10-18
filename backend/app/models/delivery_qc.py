from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DeliveryQcCheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"


class DeliveryQcOverallStatus(str, Enum):
    READY = "READY"
    REVIEW = "REVIEW"
    BLOCKED = "BLOCKED"


class DeliveryQcCheck(BaseModel):
    key: str
    category: str
    label: str
    status: DeliveryQcCheckStatus
    summary: str
    detail: Optional[str] = None
    metric: Optional[str] = None
    expected: Optional[str] = None


class DeliveryQcAcknowledgment(BaseModel):
    report_id: str
    audio_version: int
    delivery_asset_id: Optional[str] = None
    warning_keys: List[str]
    acknowledged_by: str
    acknowledged_at: datetime


class DeliveryQcReport(BaseModel):
    report_id: str
    audio_job_id: str
    assembly_job_id: str
    audio_version: int = Field(ge=1)
    generated_at: datetime
    overall_status: DeliveryQcOverallStatus
    ready_for_delivery: bool
    pass_count: int = 0
    warn_count: int = 0
    fail_count: int = 0
    info_count: int = 0
    source_visual_asset_id: Optional[str] = None
    delivery_asset_id: Optional[str] = None
    checks: List[DeliveryQcCheck] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    human_acknowledgment: Optional[DeliveryQcAcknowledgment] = None
    methodology_notice: str = (
        "M2C.3 performs deterministic delivery-readiness checks against the approved audio master and its approved visual-master lineage. "
        "FFmpeg is used to inspect the rendered container, decode integrity, duration, codecs, loudness, peak level, and long-silence events. "
        "ReviveAI also verifies captions, music-rights metadata, attribution requirements, voiceover completion, and immutable visual-master lineage. "
        "The check never regenerates Veo clips, keyframes, storyboard, captions, on-screen text, visual assembly, or audio."
    )
