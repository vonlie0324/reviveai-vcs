from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.audio_finishing import BackgroundMusicPreset, MusicSource


class MusicMatchPacing(str, Enum):
    CALM = "CALM"
    BALANCED = "BALANCED"
    FAST = "FAST"


class MusicMatchContext(BaseModel):
    working_title: str
    tone: List[str] = Field(default_factory=list)
    audio_direction: str = ""
    narrative_arc: str = ""
    total_duration_seconds: float = 0.0
    narration_seconds: float = 0.0
    narration_density: float = Field(default=0.0, ge=0.0, le=1.0)
    shot_count: int = 0
    average_shot_seconds: float = 0.0
    pacing: MusicMatchPacing = MusicMatchPacing.BALANCED


class MusicMatchRecommendation(BaseModel):
    rank: int = Field(ge=1)
    candidate_key: str
    source: MusicSource
    title: str
    artist: str = ""
    score: int = Field(ge=0, le=100)
    fit_summary: str
    reasons: List[str] = Field(default_factory=list, max_length=4)
    rights_summary: str
    preview_available: bool = True
    render_ready: bool = True
    preset: Optional[BackgroundMusicPreset] = None
    track_id: Optional[str] = None
    genre: str = ""
    moods: List[str] = Field(default_factory=list)
    duration_seconds: Optional[float] = None


class MusicMatchResult(BaseModel):
    assembly_job_id: str
    production_brief_job_id: str
    generated_at: datetime
    model: str
    context: MusicMatchContext
    evaluated_candidates: int = 0
    recommendations: List[MusicMatchRecommendation] = Field(default_factory=list)
    methodology_notice: str = (
        "M2C.6 ranks only music that ReviveAI can actually render for this project. The score is a creative-fit aid based on the approved story, tone, pacing, narration density, duration, and track metadata; it is not a prediction of views or performance. Rights and render-readiness are hard filters, not popularity bonuses. The creator always chooses the soundtrack."
    )


class AiMusicMatchItem(BaseModel):
    candidate_key: str
    score: int = Field(ge=0, le=100)
    fit_summary: str = Field(max_length=220)
    reasons: List[str] = Field(default_factory=list, max_length=3)


class AiMusicMatchPack(BaseModel):
    recommendations: List[AiMusicMatchItem] = Field(default_factory=list, max_length=12)
