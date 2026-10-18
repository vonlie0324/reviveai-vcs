from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class DeliveryPackageAssetKind(str, Enum):
    MASTER_VIDEO = "MASTER_VIDEO"
    CAPTIONS_SRT = "CAPTIONS_SRT"
    CAPTIONS_VTT = "CAPTIONS_VTT"
    THUMBNAIL = "THUMBNAIL"
    YOUTUBE_TITLE = "YOUTUBE_TITLE"
    YOUTUBE_DESCRIPTION = "YOUTUBE_DESCRIPTION"
    YOUTUBE_HASHTAGS = "YOUTUBE_HASHTAGS"
    YOUTUBE_TAGS = "YOUTUBE_TAGS"
    TIKTOK_CAPTION = "TIKTOK_CAPTION"
    INSTAGRAM_CAPTION = "INSTAGRAM_CAPTION"
    INSTAGRAM_ALT_TEXT = "INSTAGRAM_ALT_TEXT"
    PUBLISHING_DRAFT = "PUBLISHING_DRAFT"
    MUSIC_ATTRIBUTION = "MUSIC_ATTRIBUTION"
    PRODUCTION_SUMMARY = "PRODUCTION_SUMMARY"
    DELIVERY_QC = "DELIVERY_QC"
    README = "README"
    ZIP = "ZIP"


class DeliveryPackageAsset(BaseModel):
    key: str
    label: str
    kind: DeliveryPackageAssetKind
    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    asset_url: str
    gcs_uri: Optional[str] = None
    included: bool = True


class DeliveryPackage(BaseModel):
    package_id: str
    assembly_job_id: str
    audio_job_id: str
    audio_version: int = Field(ge=1)
    package_version: int = Field(ge=1)
    qc_report_id: str
    generated_at: datetime
    working_title: str
    source_visual_asset_id: Optional[str] = None
    delivery_asset_id: Optional[str] = None
    root_folder_name: str
    publishing_draft_id: Optional[str] = None
    publishing_draft_version: Optional[int] = Field(default=None, ge=1)
    zip_asset: DeliveryPackageAsset
    assets: List[DeliveryPackageAsset] = Field(default_factory=list)
    methodology_notice: str = (
        "M2C.4 packages the already-approved, QC-verified delivery master and its companion publishing assets. "
        "Package generation copies existing media, creates delivery metadata, converts existing subtitles to WebVTT, "
        "and extracts a thumbnail frame. It never regenerates Veo clips, keyframes, storyboard, captions, visual assembly, "
        "voiceover, music, ambience/SFX, or the approved audio master."
    )
