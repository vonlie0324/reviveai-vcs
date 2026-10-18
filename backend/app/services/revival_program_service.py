from __future__ import annotations

import json
import logging
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional, Sequence
from uuid import uuid4

from app.core.config import get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.services.firestore_job_repository import FirestoreJobRepository
from app.models.recovery import ChannelOperatingMode, EvidenceStrength, RecoveryJobStage
from app.models.revival_program import (
    RevivalCadenceIntensity,
    RevivalContentLane,
    RevivalContentPillar,
    RevivalProgram,
    RevivalProgramIdea,
    RevivalSlateSlot,
    RevivalWeekdayActivity,
)
from app.services.recovery_job_service import RecoveryJobNotFoundError, recovery_job_store
from app.services.job_service import JobNotFoundError, job_store


logger = logging.getLogger(__name__)


class RevivalProgramNotFoundError(KeyError):
    pass


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FALLBACK_DAYS = {
    1: ["Wed"],
    2: ["Mon", "Thu"],
    3: ["Mon", "Wed", "Fri"],
    4: ["Mon", "Wed", "Fri", "Sun"],
    5: ["Mon", "Tue", "Wed", "Fri", "Sat"],
    6: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    7: WEEKDAYS,
}
INTENSITY_CADENCE = {
    RevivalCadenceIntensity.SUSTAINABLE: 2,
    RevivalCadenceIntensity.BALANCED: 3,
    RevivalCadenceIntensity.ACCELERATED: 5,
    RevivalCadenceIntensity.DAILY_SPRINT: 7,
}
INTENSITY_LABEL = {
    RevivalCadenceIntensity.AUTO: "Adaptive",
    RevivalCadenceIntensity.SUSTAINABLE: "Sustainable",
    RevivalCadenceIntensity.BALANCED: "Balanced",
    RevivalCadenceIntensity.ACCELERATED: "Accelerated",
    RevivalCadenceIntensity.DAILY_SPRINT: "Daily sprint",
}


class RevivalProgramStore:
    def __init__(self, checkpoint_root: str = ".reviveai_checkpoints"):
        self._items: TenantScopedDict[str, RevivalProgram] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "revival_programs"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("revival_programs")

    def _path(self, recovery_job_id: str) -> Path:
        return tenant_scoped_root(self._root) / recovery_job_id / "latest.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[RevivalProgram]:
        if not payload:
            return None
        try:
            return RevivalProgram.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, program: RevivalProgram) -> None:
        path = self._path(program.recovery_job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(program.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud(self, program: RevivalProgram) -> None:
        self._cloud.save(program.recovery_job_id, program.model_dump(mode="json"))

    def _persist(self, program: RevivalProgram) -> None:
        with self._lock:
            self._items[program.recovery_job_id] = program.model_copy(deep=True)
            cloud_error: Exception | None = None
            try:
                self._persist_cloud(program)
            except Exception as exc:
                cloud_error = exc
                logger.exception("Could not persist revival program %s to Firestore", program.recovery_job_id)

            self._persist_local(program)

            if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
                raise RuntimeError("Durable Firestore persistence failed for the revival program") from cloud_error

    def _load_cloud(self, recovery_job_id: str) -> Optional[RevivalProgram]:
        try:
            return self._validate_payload(self._cloud.load(recovery_job_id))
        except Exception:
            logger.exception("Could not read revival program %s from Firestore", recovery_job_id)
            return None

    def _load_local(self, recovery_job_id: str) -> Optional[RevivalProgram]:
        path = self._path(recovery_job_id)
        if not path.exists():
            return None
        try:
            return RevivalProgram.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _backfill_cloud(self, program: RevivalProgram) -> None:
        try:
            self._persist_cloud(program)
        except Exception:
            logger.exception("Could not backfill local revival program %s to Firestore", program.recovery_job_id)

    def _load_raw(self, recovery_job_id: str) -> RevivalProgram:
        with self._lock:
            cached = self._items.get(recovery_job_id)
            if cached is not None:
                return cached.model_copy(deep=True)

            item = self._load_cloud(recovery_job_id)
            if item is None:
                item = self._load_local(recovery_job_id)
                if item is not None:
                    self._backfill_cloud(item)

            if item is None:
                raise RevivalProgramNotFoundError(recovery_job_id)

            self._items[recovery_job_id] = item
            return item.model_copy(deep=True)

    def get_for_recovery(self, recovery_job_id: str) -> RevivalProgram:
        item = self._load_raw(recovery_job_id)
        # M2E.2 lazy-upgrades earlier saved programs from the fixed Mon/Wed/Fri/Sun
        # scheduler without replacing their ideas, program id, or creator progress.
        if item.cadence_version < 2:
            try:
                item = self._configure_cadence(item, RevivalCadenceIntensity.AUTO)
                self._persist(item)
            except Exception:
                # A legacy plan remains readable even if its source analysis has since
                # become unavailable. The creator can still use the saved slate.
                pass
        return item.model_copy(deep=True)

    def create_for_recovery(self, recovery_job_id: str) -> RevivalProgram:
        try:
            return self.get_for_recovery(recovery_job_id)
        except RevivalProgramNotFoundError:
            pass

        recovery, analysis = self._source_jobs(recovery_job_id)
        recommendations = list(recovery.result.recommendations)
        if not recommendations:
            raise ValueError("Recovery Intelligence did not produce enough next-content directions for a revival program.")

        target_posts = len(recommendations)
        core_cut = max(1, math.ceil(target_posts * 0.60))
        adjacent_cut = max(core_cut + 1, math.ceil(target_posts * 0.85)) if target_posts > 2 else target_posts
        ideas: list[RevivalProgramIdea] = []
        strength_base = {EvidenceStrength.STRONG: 88, EvidenceStrength.SUPPORTED: 76, EvidenceStrength.EXPLORATORY: 64}
        for index, item in enumerate(recommendations):
            lane = RevivalContentLane.CORE if index < core_cut else RevivalContentLane.ADJACENT if index < adjacent_cut else RevivalContentLane.EXPERIMENT
            novelty_adjust = int(round((float(item.novelty_score) - 0.5) * 12)) if item.novelty_score is not None else 0
            rank_adjust = max(-8, 6 - index * 2)
            score = max(45, min(96, strength_base[item.evidence_strength] + novelty_adjust + rank_adjust))
            label = "High evidence fit" if score >= 84 else "Supported evidence fit" if score >= 70 else "Exploratory evidence fit"
            why_now = item.why_this_fits.strip() or "This direction is linked to the channel's current recovery evidence."
            ideas.append(
                RevivalProgramIdea(
                    idea_id=f"revival_idea_{uuid4().hex[:12]}",
                    recommendation_id=item.recommendation_id,
                    title=item.title,
                    concept=item.concept,
                    hook=item.hook,
                    format=item.format,
                    lane=lane,
                    evidence_strength=item.evidence_strength,
                    evidence_fit_score=score,
                    evidence_fit_label=label,
                    why_now=why_now,
                    strategy_lanes=list(item.strategy_lanes),
                )
            )

        now = datetime.now(timezone.utc)
        strategy = recovery.result.strategy
        labels = {
            ChannelOperatingMode.DISCOVER: ("30-Day Discovery", "Learn which content territories deserve investment without overfitting a small archive."),
            ChannelOperatingMode.SUSTAIN: ("30-Day Content Plan", "Sustain a healthy publishing system while protecting current strengths and testing controlled improvements."),
            ChannelOperatingMode.RECOVER: ("30-Day Recovery", "Correct recent weakness while preserving the channel identity that still has support."),
            ChannelOperatingMode.REVIVE: ("30-Day Revival", "Re-establish a sustainable publishing rhythm while re-validating older channel strengths."),
        }
        program_label, program_goal = labels[strategy.mode]
        freshness_note = (
            f"Historical Content DNA is weighted at {strategy.historical_evidence_weight:.0%}; "
            f"fresh evidence is prioritized at {strategy.fresh_evidence_priority:.0%}. "
            "This version does not claim live market demand unless external market evidence is explicitly added."
        )
        program = RevivalProgram(
            program_id=f"revival_program_{uuid4().hex}",
            recovery_job_id=recovery_job_id,
            channel_id=analysis.result.channel.channel_id,
            channel_title=analysis.result.channel.title,
            operating_mode=strategy.mode,
            program_label=program_label,
            program_goal=program_goal,
            historical_evidence_weight=strategy.historical_evidence_weight,
            fresh_evidence_priority=strategy.fresh_evidence_priority,
            evidence_freshness_note=freshness_note,
            created_at=now,
            updated_at=now,
            cadence_version=2,
            cadence_intensity=RevivalCadenceIntensity.AUTO,
            cadence_per_week=2,
            recommended_cadence_per_week=2,
            target_posts=len(ideas),
            pillars=_build_pillars(ideas),
            ideas=ideas,
        )
        program = self._configure_cadence(program, RevivalCadenceIntensity.AUTO, recovery=recovery, analysis=analysis)
        self._persist(program)
        return program.model_copy(deep=True)

    def update_cadence(self, recovery_job_id: str, intensity: RevivalCadenceIntensity) -> RevivalProgram:
        program = self._load_raw(recovery_job_id)
        program = self._configure_cadence(program, intensity)
        self._persist(program)
        return program.model_copy(deep=True)

    def _source_jobs(self, recovery_job_id: str):
        try:
            recovery = recovery_job_store.get(recovery_job_id)
        except RecoveryJobNotFoundError as exc:
            raise RevivalProgramNotFoundError(recovery_job_id) from exc
        if recovery.stage != RecoveryJobStage.COMPLETED or recovery.result is None:
            raise ValueError("Complete Recovery Intelligence before creating a revival program.")
        try:
            analysis = job_store.get(recovery.analysis_job_id)
        except JobNotFoundError as exc:
            raise ValueError("The source channel analysis is no longer available.") from exc
        if analysis.result is None:
            raise ValueError("The source channel analysis is incomplete.")
        return recovery, analysis

    def _configure_cadence(
        self,
        program: RevivalProgram,
        intensity: RevivalCadenceIntensity,
        *,
        recovery=None,
        analysis=None,
    ) -> RevivalProgram:
        if recovery is None or analysis is None:
            recovery, analysis = self._source_jobs(program.recovery_job_id)

        total_ideas = max(1, len(program.ideas))
        recommended = _recommended_cadence(total_ideas, analysis.result)
        cadence = recommended if intensity == RevivalCadenceIntensity.AUTO else INTENSITY_CADENCE[intensity]
        cadence = max(1, min(7, cadence))

        weekday_activity, suggested_days, schedule_basis = _weekday_schedule(analysis.result, cadence)
        slate = _build_slate(program.ideas, cadence, suggested_days)
        coverage = round(total_ideas / cadence, 1)
        capacity_label, capacity_warning = _backlog_capacity(total_ideas, cadence)
        rationale = _cadence_rationale(
            intensity=intensity,
            cadence=cadence,
            recommended=recommended,
            analysis_result=analysis.result,
            total_ideas=total_ideas,
            schedule_basis=schedule_basis,
            suggested_days=suggested_days,
        )

        program.cadence_version = 2
        program.cadence_intensity = intensity
        program.cadence_per_week = cadence
        program.recommended_cadence_per_week = recommended
        program.cadence_label = INTENSITY_LABEL[intensity]
        program.schedule_basis = schedule_basis
        program.schedule_rationale = rationale
        program.suggested_days = suggested_days
        program.weekday_activity = weekday_activity
        program.backlog_weeks_supported = coverage
        program.backlog_capacity_label = capacity_label
        program.backlog_capacity_warning = capacity_warning
        program.weekly_slate = slate
        program.updated_at = datetime.now(timezone.utc)
        return program

def _recommended_cadence(total_ideas: int, analysis_result) -> int:
    # Inventory tells us the minimum pace needed to test the current evidence-backed
    # backlog within roughly four weeks. Historical cadence can nudge that up, but
    # never makes a causal claim about what posting frequency will perform best.
    inventory_cadence = max(2, min(4, math.ceil(total_ideas / 4)))
    cadence_metrics = getattr(getattr(analysis_result, "metrics", None), "cadence", None)
    historical_days_30 = getattr(cadence_metrics, "active_days_per_30_days", None)
    if historical_days_30 is None:
        return inventory_cadence
    historical_per_week = float(historical_days_30) / 4.345
    if historical_per_week >= 4.25:
        history_cadence = 4
    elif historical_per_week >= 2.75:
        history_cadence = 3
    else:
        history_cadence = 2
    return max(2, min(4, max(inventory_cadence, history_cadence)))


def _weekday_schedule(analysis_result, cadence: int) -> tuple[list[RevivalWeekdayActivity], list[str], str]:
    videos = list(getattr(analysis_result, "videos", []) or [])
    dated = [getattr(video, "published_at", None) for video in videos]
    dated = [value for value in dated if value is not None]
    counts: Counter[int] = Counter(value.astimezone(timezone.utc).weekday() for value in dated)
    total = sum(counts.values())
    activity = [
        RevivalWeekdayActivity(
            day=WEEKDAYS[index],
            upload_count=counts.get(index, 0),
            share_percent=round((counts.get(index, 0) / total) * 100, 1) if total else 0,
        )
        for index in range(7)
    ]
    if total >= 8 and len([value for value in counts.values() if value > 0]) >= min(cadence, 2):
        indexes = _select_historical_weekdays(counts, cadence)
        return activity, [WEEKDAYS[index] for index in sorted(indexes)], "historical_activity_with_spacing"
    return activity, list(FALLBACK_DAYS[cadence]), "even_spacing_due_to_limited_weekday_evidence"


def _select_historical_weekdays(counts: Counter[int], cadence: int) -> list[int]:
    if cadence >= 7:
        return list(range(7))
    max_count = max(counts.values(), default=1) or 1
    selected: list[int] = []
    available = set(range(7))
    while len(selected) < cadence and available:
        best = None
        best_score = -1.0
        for day in available:
            activity = counts.get(day, 0) / max_count
            if not selected:
                spacing = 1.0
            else:
                distances = [min((day - other) % 7, (other - day) % 7) for other in selected]
                spacing = min(distances) / 3.0
            score = activity * 0.68 + spacing * 0.32
            if score > best_score or (score == best_score and (best is None or day < best)):
                best = day
                best_score = score
        selected.append(best if best is not None else min(available))
        available.discard(selected[-1])
    return selected


def _build_slate(ideas: Sequence[RevivalProgramIdea], cadence: int, days: Sequence[str]) -> list[RevivalSlateSlot]:
    slate: list[RevivalSlateSlot] = []
    max_slots = cadence * 4
    for index, idea in enumerate(list(ideas)[:max_slots]):
        week = index // cadence + 1
        slot = index % cadence + 1
        slate.append(
            RevivalSlateSlot(
                week=week,
                slot=slot,
                cadence_label=days[slot - 1],
                idea_id=idea.idea_id,
            )
        )
    return slate


def _backlog_capacity(total_ideas: int, cadence: int) -> tuple[str, Optional[str]]:
    weeks = total_ideas / cadence
    if weeks >= 4:
        return f"Current backlog supports at least 4 weeks at {cadence}/week.", None
    if weeks >= 2:
        return (
            f"Current backlog supports about {weeks:.1f} weeks at {cadence}/week.",
            "Generate more evidence-backed ideas before the current backlog runs out if you want to maintain this pace for the full 30 days.",
        )
    return (
        f"Current backlog supports only about {weeks:.1f} weeks at {cadence}/week.",
        "This pace will exhaust the current high-potential backlog quickly. Treat it as a short test sprint or generate more evidence-backed ideas first.",
    )


def _cadence_rationale(*, intensity: RevivalCadenceIntensity, cadence: int, recommended: int, analysis_result, total_ideas: int, schedule_basis: str, suggested_days: Sequence[str]) -> str:
    cadence_metrics = getattr(getattr(analysis_result, "metrics", None), "cadence", None)
    historical_days_30 = getattr(cadence_metrics, "active_days_per_30_days", None)
    historical_phrase = (
        f"The channel historically published on about {float(historical_days_30):.1f} active days per 30 days. "
        if historical_days_30 is not None
        else "There is not enough reliable historical cadence data to anchor frequency strongly. "
    )
    inventory_phrase = f"The current recovery backlog contains {total_ideas} evidence-backed ideas. "
    if intensity == RevivalCadenceIntensity.AUTO:
        selection_phrase = f"ReviveAI recommends {cadence} posts per week by balancing that history with the amount of testable content currently available. "
    else:
        selection_phrase = f"You selected the {INTENSITY_LABEL[intensity].lower()} pace at {cadence} posts per week; ReviveAI's current evidence-based recommendation is {recommended} per week. "
    if schedule_basis == "historical_activity_with_spacing":
        day_phrase = f"Suggested days ({', '.join(suggested_days)}) reflect historically active publishing weekdays with spacing between tests; this is a historical-activity cue, not a performance claim about those weekdays."
    else:
        day_phrase = f"Suggested days ({', '.join(suggested_days)}) are evenly spaced because weekday history is too limited to support a stronger claim."
    return historical_phrase + inventory_phrase + selection_phrase + day_phrase


def _build_pillars(ideas: list[RevivalProgramIdea]) -> list[RevivalContentPillar]:
    lane_counts: Counter[str] = Counter()
    for idea in ideas:
        for lane in idea.strategy_lanes:
            cleaned = lane.strip()
            if cleaned:
                lane_counts[cleaned] += 1
    names = [name for name, _ in lane_counts.most_common(3)]
    if not names:
        names = ["Core channel identity", "Adjacent format variation", "Controlled experiments"]
    pillars: list[RevivalContentPillar] = []
    for idx, name in enumerate(names[:3], start=1):
        matching = [idea.title for idea in ideas if name in idea.strategy_lanes][:4]
        if not matching:
            matching = [idea.title for idea in ideas[idx - 1 :: 3]][:4]
        pillars.append(
            RevivalContentPillar(
                pillar_id=f"pillar_{idx}",
                name=name,
                description=(
                    "Repeatable evidence-backed content territory for the 30-day recovery cycle. "
                    "ReviveAI will learn from each published result before expanding or reducing this pillar."
                ),
                source_ideas=matching,
            )
        )
    return pillars


_settings = get_settings()
revival_program_store = RevivalProgramStore(_settings.content_dna_checkpoint_dir)
