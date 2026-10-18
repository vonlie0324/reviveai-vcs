from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class PublishingDraftStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class YouTubePublishingCopy(BaseModel):
    title: str = Field(max_length=120)
    description: str = Field(max_length=5000)
    hashtags: List[str] = Field(default_factory=list, max_length=15)
    tags: List[str] = Field(default_factory=list, max_length=20)
    thumbnail_text_suggestions: List[str] = Field(default_factory=list, max_length=3)


class TikTokPublishingCopy(BaseModel):
    hook: str = Field(max_length=220)
    caption: str = Field(max_length=2200)
    hashtags: List[str] = Field(default_factory=list, max_length=12)
    cta: str = Field(default="", max_length=240)


class InstagramPublishingCopy(BaseModel):
    caption_short: str = Field(max_length=500)
    caption_long: str = Field(max_length=2200)
    hashtags: List[str] = Field(default_factory=list, max_length=15)
    alt_text: str = Field(max_length=1000)
    cta: str = Field(default="", max_length=240)


class PublishingDraftContent(BaseModel):
    youtube: YouTubePublishingCopy
    tiktok: TikTokPublishingCopy
    instagram: InstagramPublishingCopy


class PublishingDraft(BaseModel):
    draft_id: str
    assembly_job_id: str
    audio_job_id: str
    audio_version: int = Field(ge=1)
    source_package_id: Optional[str] = None
    source_package_version: Optional[int] = Field(default=None, ge=1)
    qc_report_id: str
    version_number: int = Field(ge=1)
    based_on_draft_id: Optional[str] = None
    generated_at: datetime
    updated_at: datetime
    model: str
    content: PublishingDraftContent
    status: PublishingDraftStatus = PublishingDraftStatus.DRAFT
    approved_at: Optional[datetime] = None
    generation_note: str = "Generated from the approved story, narration, final-master metadata, and recorded music rights. Creator review is required before publishing."


class PublishingDraftUpdateRequest(BaseModel):
    content: PublishingDraftContent


class PublishingDraftRegenerateRequest(BaseModel):
    fields: List[str] = Field(default_factory=list, min_length=1, max_length=20)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, values: List[str]) -> List[str]:
        allowed = {
            "youtube.title",
            "youtube.description",
            "youtube.hashtags",
            "youtube.tags",
            "youtube.thumbnail_text_suggestions",
            "tiktok.hook",
            "tiktok.caption",
            "tiktok.hashtags",
            "tiktok.cta",
            "instagram.caption_short",
            "instagram.caption_long",
            "instagram.hashtags",
            "instagram.alt_text",
            "instagram.cta",
        }
        normalized: list[str] = []
        for value in values:
            key = value.strip()
            if key not in allowed:
                raise ValueError(f"Unsupported publishing field: {key}")
            if key not in normalized:
                normalized.append(key)
        return normalized


class PublishingPackageRequest(BaseModel):
    publishing_draft_id: str
