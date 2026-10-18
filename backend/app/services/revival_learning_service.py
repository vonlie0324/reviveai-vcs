from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.services.firestore_job_repository import FirestoreJobRepository

logger = logging.getLogger(__name__)

Decision = Literal["EXPAND", "REFINE", "PAUSE", "OBSERVE"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CharacterBibleEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    character_id: str
    name: str
    personality: list[str] = Field(default_factory=list)
    visual_identity: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    source_signals: list[str] = Field(default_factory=list)
    appearances_planned: int = 0
    active: bool = True


class SeriesEntry(BaseModel):
    model_config = ConfigDict(extra="allow")
    series_id: str
    name: str
    premise: str
    character_names: list[str] = Field(default_factory=list)
    recommendation_ids: list[str] = Field(default_factory=list)
    episode_count: int = 0
    decision: Decision = "OBSERVE"
    decision_reason: str = "Awaiting enough published evidence."


class PerformanceObservation(BaseModel):
    recommendation_id: str
    publication_id: Optional[str] = None
    checkpoint: Optional[str] = None
    evidence_source: str = "MANUAL"
    statistics_status: str = "READY"
    analytics_status: str = "READY"
    analytics_views: Optional[int] = None
    observed_at: str = Field(default_factory=_now)
    views: Optional[int] = None
    viewed_vs_swiped_percent: Optional[float] = None
    average_percentage_viewed: Optional[float] = None
    average_view_duration_seconds: Optional[float] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    subscribers_gained: Optional[int] = None
    subscribers_lost: Optional[int] = None


    @model_validator(mode="before")
    @classmethod
    def quarantine_ambiguous_legacy_zero(cls, value):
        # The old exporter wrote every one of these fields as zero on empty rows.
        # Source-tagged observations (including genuine zero API rows) are exempt.
        fields = ("views", "average_percentage_viewed", "average_view_duration_seconds",
                  "likes", "comments", "shares", "subscribers_gained", "subscribers_lost")
        if (isinstance(value, dict) and "evidence_source" not in value
                and value.get("viewed_vs_swiped_percent") is None
                and all(value.get(name) == 0 for name in fields)):
            value = dict(value)
            value["evidence_source"] = "LEGACY_UNVERIFIED"
            value["statistics_status"] = "UNVERIFIED"
            value["analytics_status"] = "UNVERIFIED"
            for name in fields:
                value[name] = None
        return value

    @property
    def decision_ready(self) -> bool:
        if self.evidence_source == "LEGACY_UNVERIFIED":
            return False
        if self.evidence_source == "YOUTUBE_APIS":
            return (self.statistics_status == "READY" and self.views is not None
                    and self.analytics_status == "READY"
                    and self.average_percentage_viewed is not None
                    and self.shares is not None and self.subscribers_gained is not None
                    and self.subscribers_lost is not None)
        # Preserve the existing behavior for manually supplied observations.
        return True


class LearningWorkspace(BaseModel):
    version: int = 2
    recovery_job_id: str
    program_id: str
    channel_id: str
    updated_at: str = Field(default_factory=_now)
    character_bible: list[CharacterBibleEntry] = Field(default_factory=list)
    series_registry: list[SeriesEntry] = Field(default_factory=list)
    observations: list[PerformanceObservation] = Field(default_factory=list)
    next_wave_recommendation_ids: list[str] = Field(default_factory=list)
    learning_summary: str = "No publishing observations yet. Produce the first wave, then learn from real outcomes."


class BootstrapRequest(BaseModel):
    recovery_job_id: str
    program_id: str
    channel_id: str
    characters: list[str] = Field(default_factory=list)
    ideas: list[dict] = Field(default_factory=list)


class ObservationRequest(BaseModel):
    observation: PerformanceObservation


class RevivalLearningStore:
    """Durable learning workspace used by the continuous autonomous campaign.

    Firestore is authoritative so ranking/learning survives Cloud Run instance
    replacement. Local JSON remains a recovery mirror for development.
    """

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "revival_learning"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cloud = FirestoreJobRepository("revival_learning")

    def _path(self, program_id: str) -> Path:
        root = tenant_scoped_root(self._root)
        root.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in program_id)[:120]
        return root / f"{safe}.json"

    def _validate(self, payload: dict | None) -> Optional[LearningWorkspace]:
        if not payload:
            return None
        try:
            workspace = LearningWorkspace.model_validate(payload)
            if any(not x.decision_ready for x in workspace.observations):
                self._recalculate(workspace)
            return workspace
        except Exception:
            return None

    def _load_local(self, program_id: str) -> Optional[LearningWorkspace]:
        path = self._path(program_id)
        if not path.exists():
            return None
        try:
            return self._validate(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None

    def get(self, program_id: str) -> Optional[LearningWorkspace]:
        with self._lock:
            try:
                cloud = self._validate(self._cloud.load(program_id))
            except Exception:
                logger.exception("Could not read revival learning workspace %s from Firestore", program_id)
                cloud = None
            if cloud is not None:
                return cloud.model_copy(deep=True)
            local = self._load_local(program_id)
            if local is not None:
                try:
                    self._cloud.save(program_id, local.model_dump(mode="json"))
                except Exception:
                    logger.exception("Could not backfill revival learning workspace %s", program_id)
                return local.model_copy(deep=True)
            return None

    def _save(self, workspace: LearningWorkspace) -> LearningWorkspace:
        workspace.updated_at = _now()
        payload = workspace.model_dump(mode="json")
        cloud_error: Exception | None = None
        try:
            self._cloud.save(workspace.program_id, payload)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist revival learning workspace %s", workspace.program_id)

        path = self._path(workspace.program_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for revival learning") from cloud_error
        return workspace.model_copy(deep=True)

    def bootstrap(self, request: BootstrapRequest) -> LearningWorkspace:
        with self._lock:
            existing = None
            try:
                existing = self._validate(self._cloud.load(request.program_id))
            except Exception:
                logger.exception("Could not read revival learning workspace during bootstrap")
            if existing is None:
                existing = self._load_local(request.program_id)
            if existing is not None:
                # Ensure old v1 local workspaces become durable.
                if existing.version < 2:
                    existing.version = 2
                    return self._save(existing)
                return existing.model_copy(deep=True)

            characters = []
            for index, name in enumerate(dict.fromkeys(x.strip() for x in request.characters if x.strip()), start=1):
                characters.append(CharacterBibleEntry(
                    character_id=f"character_{index:02d}",
                    name=name,
                    source_signals=[name],
                ))

            series = []
            for index, idea in enumerate(request.ideas[:12], start=1):
                title = str(idea.get("title") or f"Series {index}").strip()
                concept = str(idea.get("concept") or "").strip()
                recommendation_id = str(idea.get("recommendation_id") or "").strip()
                idea_chars = [str(x) for x in (idea.get("recommended_characters") or []) if str(x).strip()]
                series.append(SeriesEntry(
                    series_id=f"series_{index:02d}",
                    name=title,
                    premise=concept,
                    character_names=idea_chars,
                    recommendation_ids=[recommendation_id] if recommendation_id else [],
                ))

            workspace = LearningWorkspace(
                recovery_job_id=request.recovery_job_id,
                program_id=request.program_id,
                channel_id=request.channel_id,
                character_bible=characters,
                series_registry=series,
                next_wave_recommendation_ids=[
                    str(x.get("recommendation_id")) for x in request.ideas[:5] if x.get("recommendation_id")
                ],
            )
            return self._save(workspace)

    def add_observation(self, program_id: str, observation: PerformanceObservation) -> LearningWorkspace:
        with self._lock:
            workspace = None
            try:
                workspace = self._validate(self._cloud.load(program_id))
            except Exception:
                logger.exception("Could not read revival learning workspace before observation")
            if workspace is None:
                workspace = self._load_local(program_id)
            if workspace is None:
                raise KeyError(program_id)
            workspace.observations = [
                x for x in workspace.observations if x.recommendation_id != observation.recommendation_id
            ] + [observation]
            self._recalculate(workspace)
            return self._save(workspace)

    @staticmethod
    def _score(obs: PerformanceObservation) -> float:
        if not obs.decision_ready:
            return 0.0
        score = 0.0
        if obs.viewed_vs_swiped_percent is not None:
            score += max(0.0, min(100.0, obs.viewed_vs_swiped_percent)) / 100.0 * 2.0
        if obs.average_percentage_viewed is not None:
            score += max(0.0, min(150.0, obs.average_percentage_viewed)) / 100.0 * 2.5
        views = max(1, obs.analytics_views if obs.analytics_views is not None else (obs.views or 0))
        score += min(2.0, ((obs.shares or 0) / views) * 100.0 * 4.0)
        score += min(2.0, ((obs.comments or 0) / max(1, obs.views or 0)) * 100.0 * 2.0)
        # Subscriber conversion is deliberately weighted heavily because the revival goal is growth.
        # Use net subscribers so a high-view release that also causes unsubscribes is
        # not incorrectly rewarded by the continuous campaign selector.
        net_subscribers = (obs.subscribers_gained or 0) - (obs.subscribers_lost or 0)
        score += max(-2.0, min(3.0, (net_subscribers / views) * 1000.0 * 0.35))
        return score

    @classmethod
    def score_observation(cls, observation: PerformanceObservation) -> float:
        return cls._score(observation)

    def _recalculate(self, workspace: LearningWorkspace) -> None:
        obs_by_id = {x.recommendation_id: x for x in workspace.observations}
        ranked: list[tuple[float, str]] = []
        expanded = refined = paused = 0
        for series in workspace.series_registry:
            scores = [self._score(obs_by_id[rid]) for rid in series.recommendation_ids if rid in obs_by_id and obs_by_id[rid].decision_ready]
            if not scores:
                series.decision = "OBSERVE"
                series.decision_reason = "Awaiting verified retention, sharing, and subscriber evidence; public statistics may already be available."
                continue
            score = sum(scores) / len(scores)
            primary_id = series.recommendation_ids[0] if series.recommendation_ids else ""
            ranked.append((score, primary_id))
            if score >= 5.5:
                series.decision = "EXPAND"
                series.decision_reason = "Strong combined retention, engagement, and subscriber-conversion signal; generate descendants, not copies."
                expanded += 1
            elif score >= 3.0:
                series.decision = "REFINE"
                series.decision_reason = "Promising signal with room to improve the hook, pacing, or payoff before scaling."
                refined += 1
            else:
                series.decision = "PAUSE"
                series.decision_reason = "Current observed signal is weak relative to the learning objective; preserve the idea but stop automatic expansion."
                paused += 1
        ranked.sort(reverse=True)
        workspace.next_wave_recommendation_ids = [rid for _, rid in ranked[:5] if rid]
        workspace.learning_summary = (
            f"Learning loop updated from {sum(x.decision_ready for x in workspace.observations)} verified observation(s) "
            f"({sum(not x.decision_ready for x in workspace.observations)} pending): "
            f"{expanded} expand, {refined} refine, {paused} pause. "
            "Next-wave priority favors subscriber conversion plus retention and sharing rather than raw views alone."
        )


revival_learning_store = RevivalLearningStore(get_settings().content_dna_checkpoint_dir)
