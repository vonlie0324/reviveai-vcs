from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AutonomousActivityEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    occurred_at: datetime = Field(default_factory=utc_now)
    phase: str
    action: str
    status: Literal["INFO", "SUCCESS", "WARNING", "ERROR"] = "INFO"
    message: str
    recommendation_id: Optional[str] = None
    production_job_id: Optional[str] = None
    media_job_id: Optional[str] = None
    assembly_job_id: Optional[str] = None
    audio_job_id: Optional[str] = None
    package_id: Optional[str] = None
    publishing_draft_id: Optional[str] = None
    publication_id: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
