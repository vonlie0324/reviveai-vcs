from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.final_assembly import AssemblyAsset
from app.models.production_brief import PublishingPackage


class AudioFinishingJobStage(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    SYNTHESIZING_VOICE = "SYNTHESIZING_VOICE"
    BUILDING_MIX = "BUILDING_MIX"
    RENDERING = "RENDERING"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


class AudioFinishingReviewStatus(str, Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"


class BackgroundMusicPreset(str, Enum):
    AUTO = "AUTO"
    CINEMATIC_AMBIENT = "CINEMATIC_AMBIENT"
    WARM_INSPIRATIONAL = "WARM_INSPIRATIONAL"
    MODERN_PULSE = "MODERN_PULSE"
    REFLECTIVE = "REFLECTIVE"
    BRIGHT_UPBEAT = "BRIGHT_UPBEAT"




class MusicSource(str, Enum):
    REVIVEAI = "REVIVEAI"
    YOUTUBE_AUDIO_LIBRARY = "YOUTUBE_AUDIO_LIBRARY"
    TRENDING_LICENSED = "TRENDING_LICENSED"


class TrendingMusicRenderMode(str, Enum):
    EMBEDDED = "EMBEDDED"
    PLATFORM_ONLY = "PLATFORM_ONLY"


class YouTubeAudioLibraryLicenseType(str, Enum):
    YOUTUBE_AUDIO_LIBRARY = "YOUTUBE_AUDIO_LIBRARY"
    CREATIVE_COMMONS = "CREATIVE_COMMONS"


class YouTubeAudioLibraryTrack(BaseModel):
    track_id: str
    title: str
    artist: str = ""
    genre: str = ""
    mood: str = ""
    duration_seconds: Optional[float] = None
    license_type: YouTubeAudioLibraryLicenseType = YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY
    attribution_required: bool = False
    attribution_text: Optional[str] = None
    source_url: Optional[str] = None
    imported_at: datetime
    filename: str
    mime_type: str = "application/octet-stream"
    render_ready: bool = True
    preview_available: bool = True
    usage_note: str = (
        "Imported from YouTube Audio Library for this YouTube publishing workflow. "
        "Verify the track's current license terms before using the exported video on another platform."
    )


class YouTubeAudioLibraryCatalogResponse(BaseModel):
    tracks: List[YouTubeAudioLibraryTrack] = Field(default_factory=list)
    notice: str = (
        "ReviveAI does not scrape YouTube Audio Library. Download a track in YouTube Studio, then import the "
        "audio file and its license/attribution details here. Creative Commons attribution is preserved in the delivery metadata."
    )


class TrendingMusicTrack(BaseModel):
    track_id: str
    title: str
    artist: str = ""
    provider: str = ""
    platform: str = ""
    region: str = "GLOBAL"
    trend_rank: Optional[int] = None
    trend_label: str = ""
    genre: str = ""
    moods: List[str] = Field(default_factory=list)
    duration_seconds: Optional[float] = None
    render_mode: TrendingMusicRenderMode = TrendingMusicRenderMode.EMBEDDED
    commercial_use_allowed: bool = False
    allowed_platforms: List[str] = Field(default_factory=list)
    allowed_regions: List[str] = Field(default_factory=list)
    license_reference: Optional[str] = None
    license_expires_at: Optional[datetime] = None
    source_url: Optional[str] = None
    render_ready: bool = False
    preview_available: bool = False
    usage_status: str = "UNAVAILABLE"
    is_demo: bool = False


class TrendingMusicCatalogResponse(BaseModel):
    catalog_updated_at: Optional[datetime] = None
    tracks: List[TrendingMusicTrack] = Field(default_factory=list)
    notice: str = (
        "Trend metadata comes from the configured licensed catalog/provider feed. "
        "ReviveAI never downloads social-platform audio automatically."
    )


class AudioMixOptions(BaseModel):
    """Creator-owned, versioned settings for one audio master render."""

    music_enabled: bool = True
    voiceover_enabled: bool = True
    ambience_sfx_enabled: bool = True
    voice_volume: float = Field(default=1.0, ge=0.0, le=1.5)
    music_volume: float = Field(default=0.55, ge=0.0, le=1.5)
    music_source: MusicSource = MusicSource.YOUTUBE_AUDIO_LIBRARY
    music_preset: BackgroundMusicPreset = BackgroundMusicPreset.AUTO
    trending_track_id: Optional[str] = Field(default=None, max_length=160)
    youtube_audio_library_track_id: Optional[str] = Field(default=None, max_length=160)
    ambience_volume: float = Field(default=0.70, ge=0.0, le=1.5)
    duck_music_during_voiceover: bool = True
    # None intentionally means "use the project/backend default voice".
    voice_name: Optional[str] = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def validate_music_selection(self):
        if self.music_enabled and self.music_source == MusicSource.TRENDING_LICENSED and not self.trending_track_id:
            raise ValueError("Choose a licensed trending track before creating the audio master.")
        return self


class AudioLayerSummary(BaseModel):
    key: str
    label: str
    enabled: bool
    generated: bool
    detail: str
    warning: Optional[str] = None


class VoiceoverCue(BaseModel):
    shot_number: int
    start_seconds: float
    duration_seconds: float
    text: str
    synthesized: bool = False


class AudioFinishingResult(BaseModel):
    assembly_job_id: str
    production_brief_job_id: str
    media_job_id: str
    working_title: str
    rendered_at: datetime
    total_duration_seconds: float
    delivery_video: AssemblyAsset
    subtitles: Optional[AssemblyAsset] = None
    audio_mix: Optional[AssemblyAsset] = None
    publishing: PublishingPackage
    options: AudioMixOptions
    layers: List[AudioLayerSummary] = Field(default_factory=list)
    voiceover_cues: List[VoiceoverCue] = Field(default_factory=list)
    audio_direction: str = ""
    ambience_profile: str = "ROOM"
    effective_tts_voice: str = ""
    effective_music_preset: BackgroundMusicPreset = BackgroundMusicPreset.AUTO
    effective_music_source: MusicSource = MusicSource.YOUTUBE_AUDIO_LIBRARY
    selected_trending_track: Optional[TrendingMusicTrack] = None
    selected_youtube_audio_library_track: Optional[YouTubeAudioLibraryTrack] = None
    review_status: AudioFinishingReviewStatus = AudioFinishingReviewStatus.NEEDS_REVIEW
    reviewed_at: Optional[datetime] = None
    warnings: List[str] = Field(default_factory=list)
    methodology_notice: str = (
        "M2C.2.5 preserves the approved M2C.1 visual master and rebuilds only versioned audio buses, "
        "mix/ducking, loudness normalization, and the final audio mux. Voiceover uses Google Cloud "
        "Text-to-Speech when enabled and available; music may use ReviveAI procedural beds, an imported "
        "YouTube Audio Library track with preserved license/attribution metadata, or a locally supplied track "
        "whose commercial usage rights are recorded in the configured trending catalog. "
        "Veo clips, keyframes, storyboard, captions, "
        "on-screen text, and visual assembly are never regenerated by audio finishing."
    )


class AudioFinishingJob(BaseModel):
    job_id: str
    assembly_job_id: str
    production_brief_job_id: str
    media_job_id: str
    channel_id: str
    version_number: int = Field(default=1, ge=1)
    based_on_job_id: Optional[str] = None
    stage: AudioFinishingJobStage
    message: str
    progress_current: int = 0
    progress_total: int = 5
    created_at: datetime
    updated_at: datetime
    detail: Dict[str, Any] = Field(default_factory=dict)
    options: AudioMixOptions = Field(default_factory=AudioMixOptions)
    result: Optional[AudioFinishingResult] = None
    error: Optional[str] = None
