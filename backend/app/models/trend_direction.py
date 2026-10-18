from __future__ import annotations
from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator

DirectionLane = Literal["PROVEN_EVOLUTION", "TREND_BRIDGE", "TREND_NATIVE", "AUDIENCE_EXPANSION", "EXPERIMENTAL", "CUSTOM"]

class TrendEvidence(BaseModel):
    title: str
    channel_title: str = ""
    published_at: str = ""
    views: int = 0
    views_per_day: float = 0
    url: str = ""

class DirectionScores(BaseModel):
    trend_momentum: int = Field(ge=0, le=30)
    channel_fit: int = Field(ge=0, le=25)
    format_momentum: int = Field(ge=0, le=20)
    differentiation: int = Field(ge=0, le=15)
    feasibility: int = Field(ge=0, le=10)

class TrendDirection(BaseModel):
    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value):
        """Accept Gemini's numeric or textual confidence without failing the whole direction."""
        if value is None:
            return "MEDIUM"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            score = max(0.0, min(1.0, float(value)))
            if score < 0.40:
                return "LOW"
            if score < 0.70:
                return "MEDIUM"
            return "HIGH"
        text = str(value).strip().upper()
        if text in {"LOW", "MEDIUM", "HIGH"}:
            return text
        # Tolerate common model variants such as "high confidence" or "0.9".
        try:
            score = max(0.0, min(1.0, float(text)))
            if score < 0.40:
                return "LOW"
            if score < 0.70:
                return "MEDIUM"
            return "HIGH"
        except ValueError:
            if "HIGH" in text:
                return "HIGH"
            if "LOW" in text:
                return "LOW"
            return "MEDIUM"

    direction_id: str
    lane: DirectionLane
    lane_label: str
    title: str
    concept: str
    why_now: str
    suggested_hook: str
    suggested_format: str = "Short-form video"
    suggested_first_video: str
    opportunity_score: int = Field(ge=0, le=100)
    confidence: Literal["LOW", "MEDIUM", "HIGH"] = "MEDIUM"
    scores: DirectionScores
    evidence: List[TrendEvidence] = Field(default_factory=list)
    guardrail: str = "Opportunity score prioritizes testable current signals; it is not a probability of virality."

class TrendDirectionSet(BaseModel):
    recovery_job_id: str
    generated_at: str
    market_window_days: int = 30
    directions: List[TrendDirection]
    methodology_notice: str

class CustomDirectionRequest(BaseModel):
    idea: str = Field(min_length=8, max_length=1200)

class DirectionProductionRequest(BaseModel):
    direction: TrendDirection
    fidelity_mode: Literal["STANDARD", "STRICT"] = "STANDARD"
