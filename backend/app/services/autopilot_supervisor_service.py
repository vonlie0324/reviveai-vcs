from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import BackgroundTasks, HTTPException

from app.core.config import Settings, get_settings
from app.core.tenant import tenant_bound
from app.models.audio_finishing import AudioFinishingJobStage, AudioMixOptions
from app.models.delivery_qc import DeliveryQcOverallStatus
from app.models.final_assembly import FinalAssemblyJobStage, FinalAssemblyReviewStatus
from app.models.media_studio import (
    ClipOperationStatus,
    KeyframeFidelityStatus,
    MediaAssetReviewStatus,
    MediaStudioJobStage,
    ShotOperationStatus,
)
from app.models.production_brief import (
    DirectionFidelityStatus,
    ProductionBriefJobStage,
    ProductionBriefRequest,
    ProductionBriefRetryRequest,
    ProductionFidelityMode,
    ProductionReviewStatus,
)
from app.models.publishing_assistant import PublishingDraftStatus
from app.models.youtube_publishing import YouTubePublishRequest, YouTubePublishStatus
from app.models.recovery import RecoveryJobStage
from app.services.channel_autonomy_policy import channel_policy_store
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.autonomous_activity_service import autonomous_activity_store
from app.services.autonomous_publish_planner import AutonomousPublishPlanner
from app.services.autopilot_state_service import (
    AutopilotBlockedProduction,
    AutopilotStateConflictError,
    AutopilotStateRecord,
    autopilot_state_store,
)
from app.services.delivery_package_service import delivery_package_store
from app.services.delivery_qc_service import DeliveryQcReportNotFoundError, delivery_qc_store
from app.services.final_assembly_job_service import final_assembly_job_store
from app.services.media_studio_job_service import media_studio_job_store
from app.services.production_brief_job_service import production_brief_job_store
from app.services.publishing_assistant_service import publishing_draft_store
from app.services.recovery_job_service import recovery_job_store
from app.services.campaign_replenishment_service import campaign_replenishment_service
from app.services.revival_program_service import RevivalProgramNotFoundError, revival_program_store
from app.services.revival_learning_service import BootstrapRequest, revival_learning_store
from app.services.youtube_publishing_service import youtube_publishing_service


logger = logging.getLogger(__name__)

AUTOPILOT_MAX_RETRIES = 2
AUTOPILOT_MAX_GENERATION_ATTEMPTS = 3
AUTOPILOT_ALTERNATE_APPROACH_LIMIT = 5
AUTOPILOT_SHOT_REPLAN_LIMIT = 7

ACTIVE_MEDIA_STAGES = {
    MediaStudioJobStage.QUEUED,
    MediaStudioJobStage.GENERATING_REFERENCE,
    MediaStudioJobStage.GENERATING_KEYFRAMES,
    MediaStudioJobStage.REVIEWING_KEYFRAME_FIDELITY,
    MediaStudioJobStage.GENERATING_CLIPS,
}
ACTIVE_ASSEMBLY_STAGES = {
    FinalAssemblyJobStage.QUEUED,
    FinalAssemblyJobStage.PREPARING,
    FinalAssemblyJobStage.RENDERING,
}
ACTIVE_AUDIO_STAGES = {
    AudioFinishingJobStage.QUEUED,
    AudioFinishingJobStage.PREPARING,
    AudioFinishingJobStage.SYNTHESIZING_VOICE,
    AudioFinishingJobStage.BUILDING_MIX,
    AudioFinishingJobStage.RENDERING,
}


def keyframe_retry_strategy(generation_attempt: int, max_attempts: int) -> str:
    """Plan a bounded retry that changes approach *before* the attempt cap.

    `generation_attempt` is the attempt already completed. An allowed retry
    creates attempt `generation_attempt + 1`, never an unbounded fallback.
    """
    if max_attempts < 1 or generation_attempt < 1 or generation_attempt >= max_attempts:
        return "STOP"
    # For a 3-attempt channel: first generation, alternate composition,
    # then simplified composition. No generic near-identical repetition.
    if max_attempts == 2:
        return "SIMPLIFY"
    if generation_attempt == 1:
        return "ALTERNATIVE"
    if generation_attempt == max_attempts - 1:
        return "SIMPLIFY"
    return "CORRECT"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detail(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _ai_pass(value: Any) -> bool:
    return str(_detail(value).get("decision") or "").upper() == "PASS"


def _has_active_shot_operation(job) -> bool:
    operations = (job.result.shot_operations if job.result else {}) or {}
    return any(op.status in {ShotOperationStatus.REGENERATING, ShotOperationStatus.FIDELITY_REVIEW} for op in operations.values())


def _has_active_clip_operation(job) -> bool:
    operations = (job.result.clip_operations if job.result else {}) or {}
    return any(op.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING} for op in operations.values())


def _reference_ai_passed(job) -> bool:
    if not job.result or not job.result.reference_asset or not job.result.reference_approved:
        return False
    detail = _detail(job.detail)
    review = detail.get("reference_ai_review") or detail.get("ai_reference_review")
    return str(detail.get("reference_approval_actor") or "").upper() == "AI" and _ai_pass(review)


def _keyframes_ai_passed(job) -> bool:
    if not job.result or job.result.required_keyframes <= 0 or len(job.result.keyframes) < job.result.required_keyframes:
        return False
    detail = _detail(job.detail)
    actors = _detail(detail.get("keyframe_approval_actor"))
    for asset in job.result.keyframes:
        if asset.review_status != MediaAssetReviewStatus.APPROVED:
            return False
        report = asset.fidelity_report
        if not report:
            return False
        if report.status != KeyframeFidelityStatus.PASS:
            return False
        if str(actors.get(str(asset.shot_number)) or "").upper() != "AI":
            return False
    return True


def _clips_ai_passed(job) -> bool:
    if not job.result or job.result.required_clips <= 0 or len(job.result.video_clips) < job.result.required_clips:
        return False
    detail = _detail(job.detail)
    actors = _detail(detail.get("clip_approval_actor"))
    reviews = _detail(detail.get("ai_clip_reviews"))
    for clip in job.result.video_clips:
        if clip.review_status != MediaAssetReviewStatus.APPROVED:
            return False
        if str(actors.get(str(clip.shot_number)) or "").upper() != "AI":
            return False
        review = _detail(reviews.get(str(clip.shot_number)))
        if not _ai_pass(review) or str(review.get("outcome") or "").upper() == "AI_SALVAGED":
            return False
    return True


def _assembly_matches_media(assembly, media) -> bool:
    if not assembly or not assembly.result or not media or not media.result:
        return False
    current = {clip.shot_number: clip.asset_id for clip in media.result.video_clips}
    if len(assembly.result.timeline) != media.result.required_clips:
        return False
    return all(current.get(item.shot_number) == item.source_clip_asset_id for item in assembly.result.timeline)


def _visual_master_ai_passed(assembly, media) -> bool:
    return bool(
        assembly
        and assembly.result
        and assembly.stage == FinalAssemblyJobStage.DELIVERED
        and assembly.result.review_status == FinalAssemblyReviewStatus.APPROVED
        and str(_detail(assembly.detail).get("approval_actor") or "").upper() == "AI"
        and _ai_pass(_detail(assembly.detail).get("ai_visual_master_review"))
        and _assembly_matches_media(assembly, media)
    )


def _audio_master_ai_passed(audio, assembly) -> bool:
    return bool(
        audio
        and audio.result
        and audio.stage == AudioFinishingJobStage.DELIVERED
        and audio.result.review_status.value == "APPROVED"
        and str(_detail(audio.detail).get("approval_actor") or "").upper() == "AI"
        and _ai_pass(_detail(audio.detail).get("ai_audio_review"))
        # Salvage is retention of an asset, not proof that quality defects were fixed.
        and str(_detail(_detail(audio.detail).get("ai_audio_review")).get("original_decision") or "PASS").upper() == "PASS"
        and assembly
        and audio.assembly_job_id == assembly.job_id
    )


def _human_final_approved(audio) -> bool:
    return bool(audio and _detail(audio.detail).get("human_final_approved") is True)


def _ordered_recommendation_ids(program) -> list[str]:
    ideas_by_id = {idea.idea_id: idea for idea in program.ideas}
    ordered: list[str] = []
    for slot in sorted(program.weekly_slate, key=lambda item: (item.week, item.slot)):
        idea = ideas_by_id.get(slot.idea_id)
        if idea and idea.recommendation_id not in ordered:
            ordered.append(idea.recommendation_id)
    for idea in program.ideas:
        if idea.recommendation_id not in ordered:
            ordered.append(idea.recommendation_id)
    return ordered


class AutopilotSupervisorService:
    """Backend owner of the creator Autopilot state machine.

    One call advances at most one meaningful state-machine action. Long-running work is
    spawned using the same tenant-bound background callbacks as the HTTP routes, then a
    later supervisor tick observes the persisted job checkpoint and advances again.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._spawned: set[asyncio.Task] = set()
        self._publish_planner = AutonomousPublishPlanner(self.settings)

    def _status_is_actionable(self, session) -> bool:
        """Return True when the backend supervisor is allowed to advance this session."""
        status = str(getattr(session, "status", session) or "")
        if status == "RUNNING":
            return True
        if (
            status == "WAITING_FOR_FINAL_APPROVAL"
            and bool(self.settings.autopilot_autonomous_final_approval_enabled)
        ):
            return True
        if (
            status == "WAITING_FOR_LEARNING"
            and bool(self.settings.autopilot_continuous_campaign_enabled)
        ):
            return True
        # Adopt only a legacy completed production that still points at the
        # publication it just created. A genuinely exhausted campaign remains
        # terminal and is not polled forever.
        if (
            status == "COMPLETED"
            and bool(self.settings.autopilot_continuous_campaign_enabled)
            and (bool(getattr(session, "currentPublicationId", None)) or bool(self.settings.autopilot_auto_replenish_enabled))
        ):
            return True
        return False

    def next_wake_delay(self, record: AutopilotStateRecord) -> float:
        """Return the next useful wake-up delay for event-driven execution."""
        status = str(record.session.status)
        active_delay = float(self.settings.autopilot_task_active_interval_seconds)
        if status in {"RUNNING", "WAITING_FOR_FINAL_APPROVAL"}:
            return active_delay
        if status == "COMPLETED":
            return (active_delay if record.session.currentPublicationId else 3600.0) if (self.settings.autopilot_continuous_campaign_enabled and self.settings.autopilot_auto_replenish_enabled) else (active_delay if self.settings.autopilot_continuous_campaign_enabled and record.session.currentPublicationId else 86_400.0)
        if status != "WAITING_FOR_LEARNING":
            return 300.0

        publication = None
        if record.session.currentPublicationId:
            try:
                publication = youtube_publishing_service.get(record.session.currentPublicationId)
            except Exception:
                logger.exception(
                    "Could not load current YouTube publication %s while calculating the next Autopilot wake",
                    record.session.currentPublicationId,
                )
                publication = None
        if publication is None and record.session.currentRecommendationId:
            try:
                publication = youtube_publishing_service.latest_for_recommendation(
                    record.session.currentRecommendationId
                )
            except Exception:
                logger.exception(
                    "Could not load fallback YouTube publication for recommendation %s",
                    record.session.currentRecommendationId,
                )
                publication = None
        if publication is None:
            # A missing publication is a recovery condition, not a reason to wake
            # Cloud Run every five minutes indefinitely.
            return 1_800.0

        now_utc = datetime.now(timezone.utc)
        grace = float(self.settings.autopilot_task_public_probe_grace_seconds)
        publication_status = str(
            getattr(publication.status, "value", publication.status) or ""
        ).upper()

        if publication_status == str(YouTubePublishStatus.SCHEDULED.value).upper():
            if youtube_publishing_service.authorization_reconnect_required():
                # Reconnection explicitly wakes this queue, so there is no reason to
                # burn Cloud Run requests while human OAuth action is required.
                return 86_400.0
            if publication.publish_at:
                publish_at = publication.publish_at
                if publish_at.tzinfo is None:
                    publish_at = publish_at.replace(tzinfo=timezone.utc)
                if publish_at > now_utc:
                    return max(
                        30.0,
                        (publish_at - now_utc).total_seconds() + grace,
                    )
            return 300.0

        if (
            publication_status == str(YouTubePublishStatus.PUBLISHED.value).upper()
            and publication.public_confirmed_at
        ):
            # The configured next-production checkpoint is authoritative.
            # Older persisted sessions may still carry the legacy 24H learning gate;
            # never let that stale state restore the old blocking behavior.
            required = str(
                self.settings.autopilot_next_production_checkpoint
                or "6H"
            ).upper()
            hours = {
                "1H": 1,
                "6H": 6,
                "24H": 24,
                "72H": 72,
                "7D": 168,
                "28D": 672,
            }.get(required)

            if hours is None:
                return 300.0

            if not self._learning_checkpoint_ready(publication, required):
                confirmed_at = publication.public_release_at or publication.public_confirmed_at
                if confirmed_at.tzinfo is None:
                    confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
                due_at = confirmed_at + timedelta(hours=hours)
                timeout_at = confirmed_at + timedelta(
                    hours=float(self.settings.autopilot_next_production_max_wait_hours)
                )
                target = min(due_at, timeout_at)

                if target > now_utc:
                    return max(
                        30.0,
                        (target - now_utc).total_seconds()
                        + float(self.settings.autopilot_task_analytics_grace_seconds),
                    )

                # The checkpoint is due but the YouTube analytics worker has not
                # persisted it yet. Retry shortly, but do not fall back to a generic
                # five-minute poll while the actual checkpoint is still in the future.
                return 120.0

            return 120.0

        return 1_800.0

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._spawned.add(task)
        task.add_done_callback(self._spawned.discard)

    def _spawn_background(self, background: BackgroundTasks) -> None:
        if background.tasks:
            self._spawn(background())

    async def drain_spawned(self) -> None:
        """Wait for background work started by the current supervisor action.

        In v3.5 Cloud Tasks mode CPU may be removed as soon as the HTTP request
        returns, so route-style FastAPI BackgroundTasks must finish while the task
        request is still active. The old in-process mode keeps its original behavior.
        """
        tasks = [task for task in self._spawned if not task.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=False)

    async def shutdown(self) -> None:
        """Cancel in-process task wrappers during application shutdown.

        Durable provider/job checkpoints remain authoritative; Cloud Run may restart an
        instance at any time, so the next instance must reconcile rather than assume an
        in-memory task survived.
        """
        tasks = [task for task in self._spawned if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._spawned.clear()

    def _save(self, record: AutopilotStateRecord, **patch) -> AutopilotStateRecord:
        session = record.session.model_copy(deep=True)
        previous_message = session.message
        previous_status = session.status
        previous_attention = session.attentionStage
        for key, value in patch.items():
            setattr(session, key, value)
        session.executionOwner = "BACKEND"
        session.executionVersion = 1
        session.lastSupervisorHeartbeatAt = _now_iso()
        session.updatedAt = _now_iso()
        saved = autopilot_state_store.save(session, expected_revision=record.revision)
        if (session.message != previous_message or session.status != previous_status or session.attentionStage != previous_attention):
            try:
                autonomous_activity_store.append(
                    phase=str(session.attentionStage or "AUTOPILOT"),
                    action="STATE_ADVANCED",
                    status="ERROR" if session.status == "NEEDS_ATTENTION" else "INFO",
                    message=session.message,
                    recommendation_id=session.currentRecommendationId,
                    production_job_id=session.currentProductionJobId,
                    media_job_id=session.currentMediaJobId,
                    assembly_job_id=session.currentAssemblyJobId,
                    audio_job_id=session.currentAudioJobId,
                    package_id=session.currentDeliveryPackageId,
                    publishing_draft_id=session.currentPublishingDraftId,
                    publication_id=getattr(session, "currentPublicationId", None),
                    details={"autopilot_status": session.status, "attention_stage": session.attentionStage},
                )
            except Exception:
                logger.exception("Could not append autonomous activity event")
        return saved

    def _message(self, record: AutopilotStateRecord, message: str, **patch) -> AutopilotStateRecord:
        if record.session.message == message and not patch:
            # Keep a durable supervisor heartbeat even while the workflow is waiting on
            # the same backend job. Throttle these writes so RUNNING sessions do not
            # rewrite Firestore on every 5-second supervisor tick.
            heartbeat = record.session.lastSupervisorHeartbeatAt
            if heartbeat:
                try:
                    last = datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    min_gap = max(15.0, float(self.settings.autopilot_supervisor_interval_seconds) * 3.0)
                    if (datetime.now(timezone.utc) - last).total_seconds() < min_gap:
                        return record
                except (TypeError, ValueError):
                    pass
            return self._save(record)
        return self._save(record, message=message, **patch)

    def _record_attempt(self, record: AutopilotStateRecord, key: str, message: str) -> AutopilotStateRecord:
        attempts = dict(record.session.attempts)
        attempts[key] = attempts.get(key, 0) + 1
        return self._save(record, attempts=attempts, message=message)

    @staticmethod
    def _blocked_item_blocks_autonomy(item: AutopilotBlockedProduction) -> bool:
        if item.blocksAutonomy is not None:
            return bool(item.blocksAutonomy)
        if item.resolutionStatus == "BLOCKING":
            return True
        if item.resolutionStatus in {"ARCHIVED", "RETRYABLE"}:
            return False
        # Legacy records did not have explicit resolution metadata. Content and
        # technical failures are historical production exceptions; infrastructure
        # failures remain blocking until they can be verified/recovered.
        return item.kind == "INFRASTRUCTURE"

    @classmethod
    def _blocking_items(cls, items: list[AutopilotBlockedProduction]) -> list[AutopilotBlockedProduction]:
        return [item for item in items if cls._blocked_item_blocks_autonomy(item)]

    @staticmethod
    def _normalize_blocked_item(item: AutopilotBlockedProduction) -> AutopilotBlockedProduction:
        if item.resolutionStatus is not None and item.blocksAutonomy is not None:
            return item

        has_lineage = bool(item.productionJobId or item.recoveryJobId or item.analysisJobId)
        if item.kind == "INFRASTRUCTURE":
            resolution_status = "BLOCKING"
            blocks_autonomy = True
            reason = item.resolutionReason or "INFRASTRUCTURE_ACTION_REQUIRED"
            resolved_at = item.resolvedAt
        elif has_lineage:
            resolution_status = "RETRYABLE"
            blocks_autonomy = False
            reason = item.resolutionReason or "DURABLE_LINEAGE_AVAILABLE"
            resolved_at = item.resolvedAt
        else:
            resolution_status = "ARCHIVED"
            blocks_autonomy = False
            reason = item.resolutionReason or "LEGACY_LINEAGE_UNAVAILABLE"
            resolved_at = item.resolvedAt or _now_iso()

        return item.model_copy(update={
            "resolutionStatus": resolution_status,
            "resolutionReason": reason,
            "resolvedAt": resolved_at,
            "blocksAutonomy": blocks_autonomy,
        })

    def _normalize_blocked_productions(self, record: AutopilotStateRecord) -> AutopilotStateRecord:
        normalized = [self._normalize_blocked_item(item) for item in record.session.blockedProductions]
        if [item.model_dump(mode="json") for item in normalized] == [item.model_dump(mode="json") for item in record.session.blockedProductions]:
            return record
        blocking = self._blocking_items(normalized)
        patch = {"blockedProductions": normalized}
        if record.session.status == "NEEDS_ATTENTION" and not blocking and record.session.currentRecommendationId is None:
            patch.update({
                "status": "RUNNING",
                "attentionStage": None,
                "message": f"Archived {len(normalized)} historical production exception(s). They remain in history and no longer block autonomous production.",
            })
        return self._save(record, **patch)

    def _quarantine(self, record: AutopilotStateRecord, program, stage: str, message: str, kind: str = "CONTENT") -> AutopilotStateRecord:
        session = record.session
        recommendation_id = session.currentRecommendationId
        if not recommendation_id or session.scope == "PRODUCTION" or stage == "FINAL_VIDEO":
            return self._save(record, status="NEEDS_ATTENTION", attentionStage=stage, message=message)

        blocked = [item for item in session.blockedProductions if item.recommendationId != recommendation_id]
        analysis_job_id = None
        if session.recoveryJobId:
            try:
                lineage_recovery = recovery_job_store.get(session.recoveryJobId)
                analysis_job_id = lineage_recovery.analysis_job_id
            except Exception:
                logger.warning("Could not resolve recovery lineage while quarantining recommendation_id=%s", recommendation_id)

        # Channel owners may choose to pause rather than quarantine a failed video.
        # Provider outages remain blocking in either mode, to avoid a cascade of
        # wasted or duplicated work across the rest of the campaign.
        policy = channel_policy_store.get(program.channel_id)
        is_blocking = kind == "INFRASTRUCTURE"
        if not is_blocking and not policy.isolate_failed_productions:
            return self._save(record, status="NEEDS_ATTENTION", attentionStage=stage, message=message)
        blocked_item = AutopilotBlockedProduction(
            recommendationId=recommendation_id,
            title=session.currentTitle or "Production",
            message=message,
            attentionStage=stage,
            blockedAt=_now_iso(),
            kind=kind,
            productionJobId=session.currentProductionJobId,
            recoveryJobId=session.recoveryJobId,
            analysisJobId=analysis_job_id,
            resolutionStatus="BLOCKING" if is_blocking else "ARCHIVED",
            resolutionReason="INFRASTRUCTURE_ACTION_REQUIRED" if is_blocking else "PRODUCTION_RETRIES_EXHAUSTED",
            resolvedAt=None if is_blocking else _now_iso(),
            blocksAutonomy=is_blocking,
        )
        blocked.append(blocked_item)
        completed = set(session.completedRecommendationIds)
        blocked_ids = {item.recommendationId for item in blocked}
        has_next = any(rid not in completed and rid not in blocked_ids for rid in _ordered_recommendation_ids(program))
        next_status = "RUNNING" if has_next else ("NEEDS_ATTENTION" if is_blocking else "COMPLETED")
        clear_current = has_next or not is_blocking
        return self._save(
            record,
            status=next_status,
            blockedProductions=blocked,
            attentionStage=stage if (not has_next and is_blocking) else None,
            currentRecommendationId=None if clear_current else session.currentRecommendationId,
            currentTitle=None if clear_current else session.currentTitle,
            currentStartedAt=None if clear_current else session.currentStartedAt,
            currentProductionJobId=None if clear_current else session.currentProductionJobId,
            currentMediaJobId=None if clear_current else session.currentMediaJobId,
            currentAssemblyJobId=None if clear_current else session.currentAssemblyJobId,
            currentAudioJobId=None if clear_current else session.currentAudioJobId,
            currentDeliveryPackageId=None if clear_current else session.currentDeliveryPackageId,
            currentPublishingDraftId=None if clear_current else session.currentPublishingDraftId,
            currentPublicationId=None if clear_current else getattr(session, "currentPublicationId", None),
            message=(
                f"{blocked_item.title} needs attention, but it will not block the campaign. ReviveAI is moving to the next available idea."
                if has_next
                else (
                    f"{blocked_item.title} needs attention. No other unblocked revival ideas remain."
                    if is_blocking
                    else f"{blocked_item.title} was archived after automatic retries. No other unblocked revival ideas remain."
                )
            ),
        )

    def _ensure_learning_workspace(self, program, recovery_job):
        existing = revival_learning_store.get(program.program_id)
        if existing is not None:
            return existing
        return revival_learning_store.bootstrap(
            BootstrapRequest(
                recovery_job_id=recovery_job.job_id,
                program_id=program.program_id,
                channel_id=program.channel_id,
                characters=[],
                ideas=[
                    {
                        "recommendation_id": idea.recommendation_id,
                        "title": idea.title,
                        "concept": idea.concept,
                        "recommended_characters": [],
                    }
                    for idea in program.ideas
                ],
            )
        )

    def _ordered_ids_with_learning(self, program, recovery_job) -> list[str]:
        base = _ordered_recommendation_ids(program)
        try:
            learning = self._ensure_learning_workspace(program, recovery_job)
        except Exception:
            logger.exception("Could not load continuous Autopilot learning workspace")
            return base
        if not learning.observations:
            return base

        idea_by_id = {idea.recommendation_id: idea for idea in program.ideas}
        lane_values: dict[str, list[float]] = {}
        for observation in learning.observations:
            if not observation.decision_ready:
                continue
            idea = idea_by_id.get(observation.recommendation_id)
            if idea is None:
                continue
            lane = str(getattr(idea.lane, "value", idea.lane))
            lane_values.setdefault(lane, []).append(
                revival_learning_store.score_observation(observation)
            )
        lane_scores = {
            lane: sum(values) / len(values)
            for lane, values in lane_values.items()
            if values
        }
        learned_priority = {rid: len(learning.next_wave_recommendation_ids) - index for index, rid in enumerate(learning.next_wave_recommendation_ids)}
        base_index = {rid: index for index, rid in enumerate(base)}

        def _priority(rid: str):
            idea = idea_by_id.get(rid)
            lane = str(getattr(idea.lane, "value", idea.lane)) if idea is not None else ""
            return (
                learned_priority.get(rid, 0),
                lane_scores.get(lane, -1.0),
                int(getattr(idea, "evidence_fit_score", 0) or 0) if idea is not None else 0,
                -base_index.get(rid, 10_000),
            )

        return sorted(base, key=_priority, reverse=True)

    @staticmethod
    def _checkpoint_rank(name: str | None) -> int:
        order = {"1H": 1, "6H": 2, "24H": 3, "72H": 4, "7D": 5, "28D": 6}
        return order.get(str(name or "").upper(), 0)

    def _learning_checkpoint_ready(self, publication, required: str) -> bool:
        required_rank = self._checkpoint_rank(required)
        if required_rank <= 0:
            return True
        snapshots = youtube_publishing_service.snapshots(publication.publication_id)
        anchor = publication.public_release_at or publication.public_confirmed_at
        required_hours = {"1H": 1, "6H": 6, "24H": 24, "72H": 72, "7D": 168, "28D": 672}.get(required.upper(), 0)
        if anchor is not None and anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return any(self._checkpoint_rank(item.checkpoint) >= required_rank and item.statistics_ready
                   and anchor is not None and (item.observed_at - anchor).total_seconds() >= required_hours * 3600
                   for item in snapshots)

    def _learning_wait_timed_out(self, record, publication) -> bool:
        anchor = publication.public_release_at or publication.public_confirmed_at
        if anchor is None and record.session.learningWaitStartedAt:
            try:
                anchor = datetime.fromisoformat(str(record.session.learningWaitStartedAt).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                anchor = None
        if anchor is None:
            return False
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return (
            datetime.now(timezone.utc) - anchor
        ).total_seconds() >= float(self.settings.autopilot_next_production_max_wait_hours) * 3600.0

    def _advance_after_learning(self, record, program, recovery_job):
        recommendation_id = record.session.currentRecommendationId
        publication = None
        if record.session.currentPublicationId:
            try:
                publication = youtube_publishing_service.get(record.session.currentPublicationId)
            except Exception:
                publication = None
        if publication is None and recommendation_id:
            publication = youtube_publishing_service.latest_for_recommendation(recommendation_id)

        if publication is None:
            return self._save(
                record,
                status="NEEDS_ATTENTION",
                attentionStage="FAILURE",
                message="Continuous Autopilot could not find the durable YouTube publication for the completed production.",
            )

        if publication.status != YouTubePublishStatus.PUBLISHED or not publication.public_confirmed_at:
            if youtube_publishing_service.authorization_reconnect_required():
                return self._message(
                    record,
                    "YouTube authorization requires reconnection before ReviveAI can confirm the release and continue the learning checkpoint.",
                )
            return self._message(
                record,
                "Continuous Autopilot is waiting for the scheduled video to become public before starting its learning checkpoint.",
            )

        # The next-production gate is controlled by the current configuration,
        # not by a legacy checkpoint persisted before daily learning was enabled.
        required = str(
            self.settings.autopilot_next_production_checkpoint
            or "6H"
        ).upper()
        ready = self._learning_checkpoint_ready(publication, required)
        timed_out = self._learning_wait_timed_out(record, publication)
        if not ready and not timed_out:
            return self._message(
                record,
                f"Continuous Autopilot is waiting for the {required} performance checkpoint before selecting the next production.",
            )

        try:
            self._ensure_learning_workspace(program, recovery_job)
        except Exception:
            logger.exception("Could not ensure continuous learning workspace")

        completed = list(dict.fromkeys([
            *record.session.completedRecommendationIds,
            *([recommendation_id] if recommendation_id else []),
        ]))
        blocked = [
            item for item in record.session.blockedProductions
            if item.recommendationId != recommendation_id
        ]
        note = (
            f"{required} public statistics are available. ReviveAI is selecting the next production; delayed Analytics evidence will be reconciled when available."
            if ready
            else f"The {required} learning wait exceeded the configured maximum. ReviveAI is continuing with the best available evidence."
        )
        try:
            autonomous_activity_store.append(
                phase="LEARNING",
                action="CONTINUOUS_LEARNING_READY" if ready else "CONTINUOUS_LEARNING_TIMEOUT",
                status="SUCCESS" if ready else "WARNING",
                message=note,
                recommendation_id=recommendation_id,
                publication_id=publication.publication_id,
                details={
                    "video_title": publication.video_title,
                    "checkpoint": required,
                    "timed_out": timed_out,
                },
            )
        except Exception:
            logger.exception("Could not append continuous learning activity")
        return self._save(
            record,
            scope="CAMPAIGN",
            status="RUNNING",
            attentionStage=None,
            currentRecommendationId=None,
            currentTitle=None,
            currentStartedAt=None,
            currentProductionJobId=None,
            currentMediaJobId=None,
            currentAssemblyJobId=None,
            currentAudioJobId=None,
            currentDeliveryPackageId=None,
            currentPublishingDraftId=None,
            currentPublicationId=None,
            learningCheckpointRequired=None,
            learningWaitStartedAt=None,
            completedRecommendationIds=completed,
            blockedProductions=blocked,
            message=note,
        )

    def _saved_production_for(self, recovery_job, recommendation_id: str, blocked_item: AutopilotBlockedProduction | None = None):
        # 1) Exact durable lineage is authoritative. Never guess when a quarantined
        # production already remembers its original production job.
        if blocked_item and blocked_item.productionJobId:
            try:
                job = production_brief_job_store.get(blocked_item.productionJobId)
                if job.recommendation_id == recommendation_id:
                    history = production_brief_job_store.list_history(analysis_job_id=job.analysis_job_id)
                    return next((entry for entry in history if entry.job_id == job.job_id), None)
            except Exception:
                logger.warning(
                    "Blocked production lineage could not load production job_id=%s recommendation_id=%s",
                    blocked_item.productionJobId,
                    recommendation_id,
                )

        # 2) Prefer the analysis/recovery lineage saved when the item was quarantined.
        lineage_analysis_id = blocked_item.analysisJobId if blocked_item else None
        history = production_brief_job_store.list_history(
            analysis_job_id=lineage_analysis_id or recovery_job.analysis_job_id
        )
        candidates = [
            entry for entry in history
            if entry.source_snapshot.recommendation.recommendation_id == recommendation_id
            and (not blocked_item or not blocked_item.recoveryJobId or entry.recovery_job_id == blocked_item.recoveryJobId)
        ]

        # 3) Legacy sessions did not persist lineage. Fall back to tenant-wide durable
        # history, but only with strong title/recovery evidence to avoid attaching a
        # reused recommendation_1/recommendation_2 id to the wrong production.
        if not candidates and blocked_item:
            all_history = production_brief_job_store.list_history()
            legacy = [
                entry for entry in all_history
                if entry.source_snapshot.recommendation.recommendation_id == recommendation_id
            ]
            if blocked_item.recoveryJobId:
                legacy = [entry for entry in legacy if entry.recovery_job_id == blocked_item.recoveryJobId]
            if len(legacy) > 1 and blocked_item.title:
                wanted = blocked_item.title.strip().casefold()
                title_matches = [
                    entry for entry in legacy
                    if wanted in {
                        str(entry.working_title or "").strip().casefold(),
                        str(entry.source_snapshot.recommendation.title or "").strip().casefold(),
                    }
                ]
                if title_matches:
                    legacy = title_matches
            candidates = legacy

        candidates.sort(
            key=lambda entry: (
                1 if str(entry.review_status or "") == "APPROVED" else 0,
                entry.updated_at,
            ),
            reverse=True,
        )
        return candidates[0] if candidates else None

    async def _call_background(self, func, /, *args, **kwargs):
        background = BackgroundTasks()
        kwargs["background_tasks"] = background
        if "settings" in func.__annotations__ or "settings" in str(func):
            # Most route functions use a Depends default; explicit settings keeps this
            # internal call independent of FastAPI dependency injection.
            kwargs.setdefault("settings", self.settings)
        result = await func(*args, **kwargs)
        self._spawn_background(background)
        return result

    async def _create_production(self, recovery_job_id: str, recommendation_id: str):
        from app.api.routes.production_brief import create_production_brief_job

        background = BackgroundTasks()
        result = await create_production_brief_job(
            recovery_job_id,
            ProductionBriefRequest(recommendation_id=recommendation_id, fidelity_mode=ProductionFidelityMode.STANDARD),
            background,
            self.settings,
        )
        self._spawn_background(background)
        return result

    async def _retry_production(self, job_id: str, fidelity_mode: ProductionFidelityMode):
        from app.api.routes.production_brief import retry_production_brief_job

        background = BackgroundTasks()
        result = await retry_production_brief_job(
            job_id,
            ProductionBriefRetryRequest(fidelity_mode=fidelity_mode),
            background,
            self.settings,
        )
        self._spawn_background(background)
        return result

    async def _create_media(self, production_job_id: str):
        from app.api.routes.media_studio import create_media_job

        background = BackgroundTasks()
        result = await create_media_job(production_job_id, background, self.settings)
        self._spawn_background(background)
        return result

    async def _regenerate_reference(self, job_id: str, note: str):
        from app.api.routes.media_studio import regenerate_reference
        from app.models.media_studio import RegenerateAssetRequest

        background = BackgroundTasks()
        result = await regenerate_reference(job_id, RegenerateAssetRequest(note=note), background, self.settings)
        self._spawn_background(background)
        return result

    async def _approve_reference_retry(self, job_id: str, note: str):
        from app.api.routes.media_studio import approve_reference
        from app.models.media_studio import AssetReviewRequest

        background = BackgroundTasks()
        result = await approve_reference(job_id, AssetReviewRequest(note=note), background, self.settings)
        self._spawn_background(background)
        return result

    async def _review_all_keyframes(self, job_id: str):
        from app.api.routes.media_studio import review_all_keyframes

        background = BackgroundTasks()
        result = await review_all_keyframes(job_id, background, self.settings)
        self._spawn_background(background)
        return result

    async def _regenerate_keyframe(self, job_id: str, shot_number: int, note: str):
        from app.api.routes.media_studio import regenerate_keyframe
        from app.models.media_studio import RegenerateAssetRequest

        background = BackgroundTasks()
        result = await regenerate_keyframe(job_id, shot_number, RegenerateAssetRequest(note=note), background, self.settings)
        self._spawn_background(background)
        return result

    async def _start_animation(self, job_id: str):
        from app.api.routes.media_studio import start_animation

        background = BackgroundTasks()
        result = await start_animation(job_id, background, self.settings)
        self._spawn_background(background)
        return result

    async def _regenerate_clip(self, job_id: str, shot_number: int, note: str):
        from app.api.routes.media_studio import regenerate_clip
        from app.models.media_studio import RegenerateAssetRequest

        background = BackgroundTasks()
        result = await regenerate_clip(job_id, shot_number, RegenerateAssetRequest(note=note), background, self.settings)
        self._spawn_background(background)
        return result

    async def _create_assembly(self, media_job_id: str):
        from app.api.routes.final_assembly import create_assembly_job

        background = BackgroundTasks()
        result = await create_assembly_job(media_job_id, background, self.settings)
        self._spawn_background(background)
        return result

    async def _create_audio(self, assembly_job_id: str):
        from app.api.routes.audio_finishing import create_audio_job

        background = BackgroundTasks()
        # An authorized review correction creates a fresh mix at the reviewer's
        # safer music level; never silently reuse the same loud settings.
        channel_id = final_assembly_job_store.get(assembly_job_id).channel_id
        options = AudioMixOptions(voice_name=channel_policy_store.get(channel_id).narrator_voice_name)
        previous = audio_finishing_job_store.latest_for_assembly_job(assembly_job_id)
        # Carry the last outstanding music correction forward across audio
        # generations, including versions that have not been reviewed yet.
        ancestor_id = previous.job_id if previous else None
        seen_ids: set[str] = set()
        for _ in range(30):
            if not ancestor_id or ancestor_id in seen_ids:
                break
            seen_ids.add(ancestor_id)
            try:
                ancestor = audio_finishing_job_store.get(ancestor_id)
            except Exception:
                break
            review = _detail(_detail(ancestor.detail).get("ai_audio_review"))
            review_text = " ".join(str(x) for x in review.get("issues", [])) + " " + str(review.get("corrective_instruction") or "")
            if review and any(term in review_text.lower() for term in ("music", "soundtrack", "genre", "acoustic", "vocal")):
                mix = _detail(review.get("suggested_mix"))
                options.music_volume = min(0.30, max(0.0, float(mix.get("music_volume", 0.30))))
                options.voice_volume = 1.0
                options.duck_music_during_voiceover = True
                options.ambience_volume = min(0.8, max(0.0, float(mix.get("ambience_volume", 0.7))))
                break
            ancestor_id = ancestor.based_on_job_id
        result = await create_audio_job(assembly_job_id, options, background, self.settings)
        # Keep an immutable-by-job correction plan for the renderer to validate.
        # This manifest is added before the background render is scheduled.
        if previous and previous.result:
            ancestor_id = previous.job_id
            rejected = set()
            review_found = False
            seen = set()
            for _ in range(30):
                if not ancestor_id or ancestor_id in seen:
                    break
                seen.add(ancestor_id)
                ancestor = audio_finishing_job_store.get(ancestor_id)
                review = _detail(_detail(ancestor.detail).get("ai_audio_review"))
                text = " ".join(str(x) for x in review.get("issues", [])) + " " + str(review.get("corrective_instruction") or "")
                if review and any(term in text.lower() for term in ("music", "soundtrack", "genre", "acoustic", "vocal")):
                    review_found = True
                    track_id = _detail(ancestor.detail).get("youtube_audio_library_track_id")
                    if track_id:
                        rejected.add(str(track_id))
                ancestor_id = ancestor.based_on_job_id
            if review_found:
                selected_prior = _detail(previous.detail).get("youtube_audio_library_track_id")
                if selected_prior:
                    rejected.add(str(selected_prior))
                pending = audio_finishing_job_store.get(result.job_id)
                pending.detail = {**(pending.detail or {}), "correction_manifest": {
                    "source_audio_job_id": previous.job_id,
                    "previous_track_id": selected_prior,
                    "previous_music_volume": previous.options.music_volume,
                    "rejected_track_ids": sorted(rejected),
                    "music_volume_ceiling": 0.30,
                    "requested_music_volume": options.music_volume,
                    "requested_ambience_volume": options.ambience_volume,
                    "requested_ducking": options.duck_music_during_voiceover,
                    "status": "PENDING_RENDER",
                }}
                audio_finishing_job_store.save(pending)
        self._spawn_background(background)
        return result

    async def _recover_keyframe_mismatch(self, record, media_job, shot_number: int, generation_attempt: int, inherited: bool = False):
        """Use each *allowed* attempt for a distinct strategy, never beyond policy.

        Prior implementation required three generic corrections before trying an
        alternative layout; with max_keyframe_attempts=3, those latter branches
        were unreachable. These changes affect future attempts only. There is
        no modification of stored jobs, attempts, or prior approvals.
        """
        policy = channel_policy_store.get(media_job.channel_id)
        max_attempts = policy.max_keyframe_attempts
        strategy = keyframe_retry_strategy(generation_attempt, max_attempts)
        if strategy == "STOP":
            return self._save(
                record, status="NEEDS_ATTENTION", attentionStage="KEYFRAMES",
                message=(f"Storyboard shot {shot_number} exhausted the channel limit of "
                         f"{max_attempts} keyframe attempts. Identity and fidelity gates "
                         "remain enforced; approved shots are preserved. No extra paid "
                         "generation was authorized."),
            )

        if strategy == "CORRECT":
            note = (
                "Replace inherited human adaptation. Preserve the locked character "
                "identity, source narrative, required subject count, and approved "
                "composition; correct only the specific fidelity findings."
                if inherited else
                "Fidelity correction: retain validated elements; fix the specific "
                "reviewer-identified mismatches without changing locked identity."
            )
            message = f"Correcting storyboard shot {shot_number} toward the locked production identity."
        elif strategy == "ALTERNATIVE":
            note = (
                "Distinct alternative composition (not a rephrase of the failed shot). "
                "Preserve the exact locked Production Identity, subject count, essential "
                "story action, and continuity. Favor one dominant foreground subject, "
                "clearly separated supporting subjects and static medium framing; "
                "simplify synchronized gestures and background objects. Never change "
                "anatomy, wardrobe identity, or required characters."
            )
            message = f"Storyboard shot {shot_number} is trying a distinct alternative composition."
        else:  # SIMPLIFY: last permitted attempt, not an extra attempt.
            note = (
                "Last policy-authorized attempt: simplify the shot substantially "
                "while preserving the immutable story purpose, exact locked subject "
                "count, character identity, anatomy, wardrobe, and setting. Use a "
                "clear static composition, simpler poses and props, and only one "
                "prominent movement. Do not omit mandatory characters or bypass "
                "fidelity/AI review. If essential criteria cannot be met, fail closed."
            )
            message = f"Storyboard shot {shot_number} is using its final permitted simplified composition."

        await self._regenerate_keyframe(media_job.job_id, shot_number, note)
        return self._message(record, message)

    async def advance(self, record: AutopilotStateRecord) -> AutopilotStateRecord:
        if not self._status_is_actionable(record.session):
            return record
        record = self._normalize_blocked_productions(record)
        if not self._status_is_actionable(record.session):
            return record
        if record.session.executionOwner != "BACKEND":
            record = self._save(record, executionOwner="BACKEND")

        recovery_id = record.session.recoveryJobId
        if not recovery_id:
            return self._save(record, status="NEEDS_ATTENTION", attentionStage="FAILURE", message="Autopilot has no saved Recovery Intelligence checkpoint.")

        recovery_job = recovery_job_store.get(recovery_id)
        if recovery_job.stage != RecoveryJobStage.COMPLETED or not recovery_job.result:
            return self._message(record, recovery_job.message or "Waiting for Recovery Intelligence to finish.")

        try:
            program = revival_program_store.get_for_recovery(recovery_id)
        except RevivalProgramNotFoundError:
            program = revival_program_store.create_for_recovery(recovery_id)

        if record.session.scope == "CAMPAIGN" and record.session.programId != program.program_id:
            record = self._save(record, programId=program.program_id)

        if bool(self.settings.autopilot_continuous_campaign_enabled):
            if record.session.status == "COMPLETED" and record.session.currentPublicationId:
                record = self._save(
                    record,
                    status="WAITING_FOR_LEARNING",
                    learningCheckpointRequired=str(self.settings.autopilot_next_production_checkpoint).upper(),
                    learningWaitStartedAt=record.session.learningWaitStartedAt or _now_iso(),
                    message="Continuous Autopilot adopted the completed production and is waiting for post-publication learning before choosing the next idea.",
                )
            if record.session.status == "WAITING_FOR_LEARNING":
                # Migrate durable sessions created by the old 24H-blocking loop.
                # `learningCheckpointRequired` now means only the checkpoint that
                # unlocks the *next production*. The 24H primary-performance
                # checkpoint continues independently in YouTube analytics.
                configured_gate = str(
                    self.settings.autopilot_next_production_checkpoint or "6H"
                ).upper()
                if str(record.session.learningCheckpointRequired or "").upper() != configured_gate:
                    record = self._save(
                        record,
                        learningCheckpointRequired=configured_gate,
                    )
                return self._advance_after_learning(record, program, recovery_job)

        recommendation_id = record.session.currentRecommendationId
        if not recommendation_id:
            if record.session.scope == "PRODUCTION":
                return self._save(record, status="NEEDS_ATTENTION", attentionStage="FAILURE", message="The production Autopilot lost its saved direction. Reopen the production and run Autopilot again.")
            completed = set(record.session.completedRecommendationIds)
            blocked = {item.recommendationId for item in record.session.blockedProductions}
            next_id = next((rid for rid in self._ordered_ids_with_learning(program, recovery_job) if rid not in completed and rid not in blocked), None)
            if not next_id:
                if (self.settings.autopilot_continuous_campaign_enabled and self.settings.autopilot_auto_replenish_enabled
                        and record.session.scope == "CAMPAIGN"):
                    try:
                        count = await campaign_replenishment_service.replenish(recovery_job, program)
                        if count:
                            return self._save(record, status="RUNNING", attentionStage=None,
                                              message=f"Replenished {count} new creative directions. Autopilot is resuming production.")
                    except Exception as exc:
                        return self._save(record, status="COMPLETED", attentionStage=None,
                                          message=f"Replenishment is paused after {type(exc).__name__}; the existing campaign history is preserved. It will retry after the cooldown.")
                    return self._save(record, status="COMPLETED", attentionStage=None,
                                      message="All current ideas are complete. Automatic replenishment is waiting for its next eligible cycle.")
                blocking_items = self._blocking_items(record.session.blockedProductions)
                if blocking_items:
                    return self._save(
                        record,
                        status="NEEDS_ATTENTION",
                        attentionStage=blocking_items[0].attentionStage or "FAILURE",
                        message=f"{len(blocking_items)} blocking production issue(s) still need attention. Historical failures remain preserved separately.",
                    )
                archived_count = len(record.session.blockedProductions)
                return self._save(
                    record,
                    status="COMPLETED",
                    attentionStage=None,
                    message=(
                        f"Autopilot finished every available idea. {archived_count} historical production exception(s) are preserved and do not block autonomy."
                        if archived_count
                        else "Autopilot finished every available idea in this revival program."
                    ),
                )
            recommendation = next((item for item in recovery_job.result.recommendations if item.recommendation_id == next_id), None)
            idea = next((item for item in program.ideas if item.recommendation_id == next_id), None)
            if not recommendation:
                return self._quarantine(record, program, "FAILURE", "The next revival idea no longer has a matching Recovery Intelligence recommendation.")
            saved = self._saved_production_for(recovery_job, next_id)
            if saved:
                production_job = production_brief_job_store.get(saved.job_id)
            else:
                production_job = await self._create_production(recovery_id, next_id)
            return self._save(
                record,
                currentRecommendationId=next_id,
                currentTitle=(idea.title if idea else recommendation.title),
                currentStartedAt=_now_iso(),
                currentProductionJobId=production_job.job_id,
                currentMediaJobId=None,
                currentAssemblyJobId=None,
                currentAudioJobId=None,
                currentDeliveryPackageId=None,
                currentPublishingDraftId=None,
                attentionStage=None,
                message=(f"Adopting existing production: {idea.title if idea else recommendation.title}" if saved else f"Starting production: {idea.title if idea else recommendation.title}"),
            )

        # Production brief.
        production_job = None
        if record.session.currentProductionJobId:
            try:
                production_job = production_brief_job_store.get(record.session.currentProductionJobId)
            except Exception:
                production_job = None
        if not production_job or production_job.recommendation_id != recommendation_id:
            blocked_item = next(
                (item for item in record.session.blockedProductions if item.recommendationId == recommendation_id),
                None,
            )
            saved = self._saved_production_for(recovery_job, recommendation_id, blocked_item)
            if saved:
                production_job = production_brief_job_store.get(saved.job_id)
                record = self._save(record, currentProductionJobId=production_job.job_id, message="Reconnected the current production brief from durable history.")
            else:
                return self._message(record, "Waiting for the current production to reconnect before advancing.")

        if production_job.stage not in {ProductionBriefJobStage.COMPLETED, ProductionBriefJobStage.FAILED}:
            return self._message(record, production_job.message or "Building the production brief.")
        if production_job.stage == ProductionBriefJobStage.FAILED:
            key = f"brief:{recommendation_id}"
            attempts = record.session.attempts.get(key, 0)
            if attempts < AUTOPILOT_MAX_RETRIES:
                record = self._record_attempt(record, key, f"Production brief failed. Retrying automatically ({attempts + 1}/{AUTOPILOT_MAX_RETRIES}).")
                next_job = await self._retry_production(production_job.job_id, production_job.fidelity_mode)
                return self._save(record, currentProductionJobId=next_job.job_id)
            return self._quarantine(record, program, "FAILURE", production_job.error or "The production brief failed repeatedly and needs review.", "TECHNICAL")

        brief = production_job.result
        if not brief:
            return self._quarantine(record, program, "FAILURE", "The production brief completed without a result.", "TECHNICAL")
        if brief.direction_fidelity.status == DirectionFidelityStatus.REVIEW_REQUIRED:
            key = f"direction:{recommendation_id}"
            attempts = record.session.attempts.get(key, 0)
            if attempts < AUTOPILOT_MAX_GENERATION_ATTEMPTS:
                record = self._record_attempt(record, key, f"The brief drifted from the source direction. Rebuilding in STRICT mode ({attempts + 1}/{AUTOPILOT_MAX_GENERATION_ATTEMPTS}).")
                next_job = await self._retry_production(production_job.job_id, ProductionFidelityMode.STRICT)
                return self._save(record, currentProductionJobId=next_job.job_id)
            return self._quarantine(record, program, "PRODUCTION_DIRECTION", "AI could not restore the approved source direction after automatic retries.")
        if brief.consistency_report.status.value != "PASS":
            key = f"consistency:{recommendation_id}"
            attempts = record.session.attempts.get(key, 0)
            if attempts < AUTOPILOT_MAX_RETRIES:
                record = self._record_attempt(record, key, f"Production consistency did not pass. Regenerating automatically ({attempts + 1}/{AUTOPILOT_MAX_RETRIES}).")
                next_job = await self._retry_production(production_job.job_id, production_job.fidelity_mode)
                return self._save(record, currentProductionJobId=next_job.job_id)
            issue = brief.consistency_report.blocking_issues[0] if brief.consistency_report.blocking_issues else "Production consistency still needs correction."
            return self._quarantine(record, program, "PRODUCTION_DIRECTION", issue)

        detail = _detail(production_job.detail)
        plan_review = _detail(detail.get("ai_plan_review"))
        plan_review_current = str(detail.get("ai_plan_review_for_generated_at") or "") == str(brief.model_dump(mode="json").get("generated_at") or "")
        plan_pass = brief.review_status == ProductionReviewStatus.APPROVED and str(detail.get("approval_actor") or "").upper() == "AI" and plan_review_current and _ai_pass(plan_review)
        if not plan_pass:
            if plan_review_current and str(plan_review.get("decision") or "").upper() == "REGENERATE":
                key = f"plan-critic:{recommendation_id}"
                attempts = record.session.attempts.get(key, 0)
                if attempts < AUTOPILOT_MAX_GENERATION_ATTEMPTS:
                    record = self._record_attempt(record, key, f"The independent AI plan critic found a material issue. Rebuilding the brief ({attempts + 1}/{AUTOPILOT_MAX_GENERATION_ATTEMPTS}).")
                    next_job = await self._retry_production(production_job.job_id, ProductionFidelityMode.STRICT)
                    return self._save(record, currentProductionJobId=next_job.job_id)
                return self._quarantine(record, program, "PRODUCTION_DIRECTION", "The production plan could not pass the independent AI text critic after automatic retries.")
            from app.api.routes.ai_review import ai_review_production_brief
            reviewed = await ai_review_production_brief(production_job.job_id, self.settings)
            return self._save(record, currentProductionJobId=reviewed.job_id, message="Independent AI plan critic reviewed the production brief.")

        # Media / visual generation.
        media_job = None
        if record.session.currentMediaJobId:
            try:
                media_job = media_studio_job_store.get(record.session.currentMediaJobId)
            except Exception:
                media_job = None
        if not media_job or media_job.production_brief_job_id != production_job.job_id:
            media_job = media_studio_job_store.latest_for_production_brief(production_job.job_id)
            if not media_job:
                media_job = await self._create_media(production_job.job_id)
                return self._save(record, currentMediaJobId=media_job.job_id, message="Starting visual reference generation.")
            record = self._save(record, currentMediaJobId=media_job.job_id)

        if media_job.stage in ACTIVE_MEDIA_STAGES or _has_active_shot_operation(media_job) or _has_active_clip_operation(media_job):
            return self._message(record, media_job.message or "Generating visual assets.")
        if media_job.stage == MediaStudioJobStage.FAILED:
            key = f"media:{recommendation_id}"
            attempts = record.session.attempts.get(key, 0)
            if attempts < AUTOPILOT_MAX_RETRIES:
                record = self._record_attempt(record, key, f"Media generation paused. Retrying failed visual work ({attempts + 1}/{AUTOPILOT_MAX_RETRIES}).")
                if media_job.result and media_job.result.reference_approved:
                    await self._approve_reference_retry(media_job.job_id, "Autopilot retry after interrupted keyframe generation.")
                else:
                    await self._regenerate_reference(media_job.job_id, "Autopilot retry after reference generation failure.")
                return record
            return self._quarantine(record, program, "FAILURE", media_job.error or "Media generation failed repeatedly.", "TECHNICAL")

        if media_job.result and media_job.result.reference_asset and not _reference_ai_passed(media_job) and media_job.stage not in {MediaStudioJobStage.QUEUED, MediaStudioJobStage.GENERATING_REFERENCE}:
            if _detail(media_job.detail).get("ai_review_exhausted") is True:
                return self._quarantine(record, program, "REFERENCE", "The AI visual reviewer could not clear the canonical reference after automatic recovery attempts.")
            from app.api.routes.ai_review import ai_review_reference
            background = BackgroundTasks()
            reviewed = await ai_review_reference(media_job.job_id, background, self.settings)
            self._spawn_background(background)
            return self._save(record, currentMediaJobId=reviewed.job_id, message="AI visual reviewer checked the canonical character reference.")

        if media_job.result and media_job.result.keyframes and not _has_active_shot_operation(media_job):
            failed_asset_operation = next(
                (
                    op
                    for op in (media_job.result.shot_operations or {}).values()
                    if op.status == ShotOperationStatus.FAILED
                    and str(op.error or "").startswith("MEDIA_ARTIFACT_MISSING:")
                ),
                None,
            )
            if failed_asset_operation is not None:
                return self._quarantine(
                    record,
                    program,
                    "KEYFRAMES",
                    failed_asset_operation.error
                    or f"Shot {failed_asset_operation.shot_number} requires a source asset that is unavailable in durable storage.",
                    "TECHNICAL",
                )
            detail = _detail(media_job.detail)
            actors = _detail(detail.get("keyframe_approval_actor"))
            missing = next((asset for asset in media_job.result.keyframes if asset.fidelity_report is None), None)
            if missing:
                await self._review_all_keyframes(media_job.job_id)
                return self._message(record, "Running Gemini storyboard-fidelity review for generated keyframes.")
            inherited = next((asset for asset in media_job.result.keyframes if asset.fidelity_report and asset.fidelity_report.status == KeyframeFidelityStatus.ADAPTATION_ACCEPTED and asset.fidelity_report.creator_override), None)
            if inherited and inherited.shot_number:
                return await self._recover_keyframe_mismatch(record, media_job, inherited.shot_number, inherited.generation_attempt, True)
            mismatch = next((asset for asset in media_job.result.keyframes if asset.fidelity_report and asset.fidelity_report.status == KeyframeFidelityStatus.REVIEW_REQUIRED), None)
            if mismatch and mismatch.shot_number:
                return await self._recover_keyframe_mismatch(record, media_job, mismatch.shot_number, mismatch.generation_attempt)
            needs_owner = next((asset for asset in media_job.result.keyframes if asset.shot_number and asset.fidelity_report and asset.fidelity_report.status == KeyframeFidelityStatus.PASS and str(actors.get(str(asset.shot_number)) or "").upper() != "AI"), None)
            if needs_owner and needs_owner.shot_number:
                from app.api.routes.ai_review import ai_approve_keyframe
                await ai_approve_keyframe(media_job.job_id, needs_owner.shot_number)
                return self._message(record, f"AI approved storyboard shot {needs_owner.shot_number} after fidelity PASS.")

        if media_job.stage == MediaStudioJobStage.READY_FOR_ANIMATION and media_job.result and media_job.result.animation_ready:
            await self._start_animation(media_job.job_id)
            return self._message(record, "All keyframes are fidelity-cleared. Starting Veo animation.")

        if media_job.stage == MediaStudioJobStage.AWAITING_CLIP_REVIEW and media_job.result:
            if _has_active_clip_operation(media_job):
                return self._message(record, media_job.message or "Waiting for animated-shot generation.")
            # Inspect *all* shot operations before considering any generation retry:
            # a blocked reservation anywhere in this production is a global budget
            # stop, even when another shot is listed first as FAILED.
            operations = list((media_job.result.clip_operations or {}).values())
            budget_block = next((op for op in operations if
                op.status == ClipOperationStatus.BUDGET_EXCEEDED
                or "BUDGET_EXCEEDED" in str(op.error or "").upper()), None)
            if budget_block:
                return self._quarantine(
                    record, program, "CLIPS",
                    f"Veo budget exhausted on shot {budget_block.shot_number}. "
                    "Autopilot paused before further paid retries; approved assets are preserved. "
                    f"{budget_block.error or 'Review the production budget and outstanding reservations.'}",
                    "TECHNICAL",
                )
            failed = next((op for op in operations if op.status == ClipOperationStatus.FAILED), None)
            if failed:
                if failed.target_generation_attempt < channel_policy_store.get(program.channel_id).max_keyframe_attempts:
                    await self._regenerate_clip(media_job.job_id, failed.shot_number, "Autopilot retry for failed Veo shot.")
                    return self._message(record, f"Retrying animated shot {failed.shot_number}.")
                return self._save(record, status="NEEDS_ATTENTION", attentionStage="CLIPS",
                    message=f"Veo shot {failed.shot_number} failed after bounded attempts. Automatic motion substitution is forbidden.")
            unapproved = next((clip for clip in media_job.result.video_clips if clip.review_status != MediaAssetReviewStatus.APPROVED), None)
            if unapproved:
                exhausted = {int(v) for v in (_detail(media_job.detail).get("ai_review_exhausted_clips") or []) if str(v).isdigit()}
                if unapproved.shot_number in exhausted:
                    # Legacy sessions could be marked exhausted after ONE review solely
                    # because autonomous regeneration was disabled. Reconsider only an
                    # explicit REGENERATE verdict on a first-generation clip; never
                    # bypass actual generation-attempt limits or AI quality approval.
                    review = _detail(_detail(media_job.detail).get("ai_clip_reviews")).get(str(unapproved.shot_number))
                    review = _detail(review)
                    verdict = str(review.get("decision") or "").upper()
                    if (self.settings.autopilot_allow_regeneration
                        and verdict == "REGENERATE"
                        and int(unapproved.generation_attempt) < 3):
                        instruction = str(review.get("corrective_instruction") or review.get("summary") or "").strip()
                        if instruction:
                            # Clear only this obsolete exhaustion marker. The normal
                            # Firestore reservation gate still checks the next paid call.
                            fresh = media_studio_job_store.get(media_job.job_id)
                            fresh_detail = dict(fresh.detail or {})
                            fresh_detail["ai_review_exhausted_clips"] = [
                                x for x in (fresh_detail.get("ai_review_exhausted_clips") or [])
                                if str(x) != str(unapproved.shot_number)
                            ]
                            fresh.detail = fresh_detail
                            media_studio_job_store.save(fresh)
                            await self._regenerate_clip(media_job.job_id, unapproved.shot_number, instruction)
                            return self._message(record, f"Correcting Veo shot {unapproved.shot_number} using Gemini motion feedback.")
                    return self._save(record, status="NEEDS_ATTENTION", attentionStage="CLIPS",
                        message=f"Veo shot {unapproved.shot_number} did not pass motion fidelity after bounded review. No substitute was approved.")
                from app.api.routes.ai_review import ai_review_clip
                background = BackgroundTasks()
                reviewed = await ai_review_clip(media_job.job_id, unapproved.shot_number, background, self.settings)
                self._spawn_background(background)
                return self._save(record, currentMediaJobId=reviewed.job_id, message=f"AI video reviewer is checking animated shot {unapproved.shot_number}.")

        if media_job.stage == MediaStudioJobStage.READY_FOR_ASSEMBLY and media_job.result and media_job.result.assembly_ready:
            detail = _detail(media_job.detail)
            actors = _detail(detail.get("clip_approval_actor"))
            reviews = _detail(detail.get("ai_clip_reviews"))
            needs_review = next((clip for clip in media_job.result.video_clips if str(actors.get(str(clip.shot_number)) or "").upper() != "AI" or not _ai_pass(reviews.get(str(clip.shot_number))) or str(_detail(reviews.get(str(clip.shot_number))).get("outcome") or "").upper() == "AI_SALVAGED"), None)
            if needs_review:
                from app.api.routes.ai_review import ai_review_clip
                background = BackgroundTasks()
                await ai_review_clip(media_job.job_id, needs_review.shot_number, background, self.settings)
                self._spawn_background(background)
                return self._message(record, f"AI is validating adopted animated shot {needs_review.shot_number} before assembly.")

        # Final assembly.
        assembly_job = None
        if record.session.currentAssemblyJobId:
            try:
                assembly_job = final_assembly_job_store.get(record.session.currentAssemblyJobId)
            except Exception:
                assembly_job = None
        if media_job.stage == MediaStudioJobStage.READY_FOR_ASSEMBLY and media_job.result and media_job.result.assembly_ready:
            # An active/failed assembly has no result until the render succeeds.
            # Never treat a missing result as a reason to spawn another render.
            def belongs_to_current_media(candidate) -> bool:
                return bool(
                    candidate
                    and candidate.media_job_id == media_job.job_id
                    and (
                        _assembly_matches_media(candidate, media_job)
                        or (candidate.result is None and candidate.stage in (
                            *ACTIVE_ASSEMBLY_STAGES, FinalAssemblyJobStage.FAILED
                        ))
                    )
                )

            if not belongs_to_current_media(assembly_job):
                existing = final_assembly_job_store.latest_for_media_job(media_job.job_id)
                if belongs_to_current_media(existing):
                    assembly_job = existing
                else:
                    # The media clips are approved and no current assembly exists.
                    assembly_job = await self._create_assembly(media_job.job_id)
                    return self._save(record, currentAssemblyJobId=assembly_job.job_id, message="Building the visual master from AI-reviewed clips.")
                record = self._save(record, currentAssemblyJobId=assembly_job.job_id)
        if not assembly_job:
            return record
        if assembly_job.stage in ACTIVE_ASSEMBLY_STAGES:
            # A process may have disappeared during Cloud Run deployment. Report
            # stalled progress without creating a second competing assembly.
            updated = assembly_job.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - updated > timedelta(minutes=45):
                return self._save(
                    record, status="NEEDS_ATTENTION", attentionStage="VISUAL_MASTER",
                    message=f"Assembly {assembly_job.job_id} has not checkpointed in over 45 minutes. Inspect the worker before retrying; approved clips remain saved."
                )
            return self._message(record, assembly_job.message or "Rendering the visual master.")
        if assembly_job.stage == FinalAssemblyJobStage.FAILED:
            # One controlled assembly-only retry after a failed attempt. Veo clips
            # are reused; no reference/keyframe/video generation is restarted.
            retry_key = f"assembly-recovery:{media_job.job_id}"
            attempts = record.session.attempts.get(retry_key, 0)
            # An authenticated operator may authorize ONE extra infrastructure-only
            # attempt after the rendering image is repaired. Approval is tied to
            # the failed assembly ID, never to a campaign-wide retry counter.
            repair_key = f"assembly-infra-repair:{assembly_job.job_id}"
            repair_authorized = record.session.attempts.get(repair_key, 0) == 1
            if attempts < 1 or repair_authorized:
                next_attempts = dict(record.session.attempts)
                next_attempts[retry_key] = attempts + 1
                if repair_authorized:
                    # Consume authorization durably *before* creating the job;
                    # otherwise a failed state write could trigger infinite repairs.
                    next_attempts[repair_key] = 2
                record = self._save(
                    record, attempts=next_attempts,
                    message=f"Starting a controlled visual-master render using existing approved clips ({assembly_job.job_id}).",
                )
                # Another in-flight request may already have created a replacement.
                # Prefer adopting it over issuing a second render.
                latest = final_assembly_job_store.latest_for_media_job(media_job.job_id)
                if latest and latest.job_id != assembly_job.job_id and latest.created_at >= assembly_job.created_at:
                    replacement = latest
                else:
                    replacement = await self._create_assembly(media_job.job_id)
                return self._save(
                    record, currentAssemblyJobId=replacement.job_id,
                    message="Restarted visual-master assembly using existing approved Veo clips."
                )
            return self._save(
                record, status="NEEDS_ATTENTION", attentionStage="VISUAL_MASTER",
                message=f"Assembly failed after a controlled retry: {assembly_job.error or 'unknown error'}. Approved clips were preserved."
            )
        if assembly_job.stage in {FinalAssemblyJobStage.COMPLETED, FinalAssemblyJobStage.DELIVERED} and not _visual_master_ai_passed(assembly_job, media_job):
            from app.api.routes.ai_review import ai_review_visual_master
            background = BackgroundTasks()
            reviewed = await ai_review_visual_master(assembly_job.job_id, background, self.settings)
            self._spawn_background(background)
            return self._save(record, currentAssemblyJobId=reviewed.job_id, message="AI visual reviewer checked the assembled master.")
        if not _visual_master_ai_passed(assembly_job, media_job):
            return record

        # Audio finishing.
        audio_job = None
        if record.session.currentAudioJobId:
            try:
                audio_job = audio_finishing_job_store.get(record.session.currentAudioJobId)
            except Exception:
                audio_job = None
        if not audio_job or audio_job.assembly_job_id != assembly_job.job_id:
            audio_job = audio_finishing_job_store.latest_for_assembly_job(assembly_job.job_id)
            if not audio_job:
                audio_job = await self._create_audio(assembly_job.job_id)
                return self._save(record, currentAudioJobId=audio_job.job_id, message="Visual master passed AI review. Creating voice, music, ambience, and final audio mix.")
            record = self._save(record, currentAudioJobId=audio_job.job_id)
        if audio_job.stage in ACTIVE_AUDIO_STAGES:
            # A Cloud Run instance may terminate after recording RENDERING but
            # before completing the mux. Never replay TTS or assume a HTTP 200
            # from the supervisor means the audio worker is still alive.
            # Stale recovery is restricted to jobs having a durable MUX_READY
            # manifest and is run under the tenant's supervisor execution lease.
            now = datetime.now(timezone.utc)
            updated = audio_job.updated_at
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            stale_seconds = (now - updated).total_seconds()
            # Opt-in: do not automatically change existing production state on
            # deployment. Enable only after a maintenance review.
            # Only newly created jobs are eligible. This prevents deployment
            # from reopening historical defective productions.
            watchdog_enabled = os.getenv("REVIVEAI_AUDIO_MUX_WATCHDOG_ENABLED", "false").lower() in {"1", "true", "yes"}
            created = audio_job.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            cutoff_raw = os.getenv("REVIVEAI_FUTURE_AUDIO_RECOVERY_FROM", "").strip()
            cutoff = None
            if cutoff_raw:
                try:
                    cutoff = datetime.fromisoformat(cutoff_raw.replace("Z", "+00:00"))
                    if cutoff.tzinfo is None:
                        cutoff = None
                except ValueError:
                    logger.error("Invalid future audio recovery cutoff; watchdog disabled")
            future_eligible = cutoff is not None and created >= cutoff
            if watchdog_enabled and future_eligible and stale_seconds >= 7200 and audio_job.stage == AudioFinishingJobStage.RENDERING:
                manifest = _detail(_detail(audio_job.detail).get("render_checkpoint"))
                if manifest.get("version") == 1 and manifest.get("state") == "MUX_READY":
                    claim_key = f"durable-audio-mux-recovery:{audio_job.job_id}"
                    if record.session.attempts.get(claim_key, 0) == 0:
                        record = self._save(record, attempts={
                            **record.session.attempts, claim_key: 1,
                        }, message="Resuming abandoned final mux from saved audio artifacts; no AI generation is repeated.")
                        from app.services.audio_finishing_job_service import resume_audio_final_mux
                        background = BackgroundTasks()
                        background.add_task(tenant_bound(resume_audio_final_mux), audio_job.job_id, self.settings)
                        self._spawn_background(background)
                        return record
                    # One attempted recovery is the limit. No unattended
                    # provider regeneration or repeated mux retries.
                    return self._save(record, status="NEEDS_ATTENTION", attentionStage="AUDIO_MASTER",
                        message="Durable audio mux recovery was already attempted; inspect audio job before further action.")
                # Pre-checkpoint jobs (including legacy jobs at 4/5) have no
                # durable, reconstructible metadata. Do not silently reset or
                # regenerate providers; make the existing stall actionable.
                return self._save(record, status="NEEDS_ATTENTION", attentionStage="AUDIO_MASTER",
                    message="Audio rendering has stalled without a durable mux checkpoint. Original narration and visual master preserved; operator review required.")
            if (watchdog_enabled and future_eligible and stale_seconds >= 7200
                    and audio_job.stage != AudioFinishingJobStage.RENDERING):
                return self._save(record, status="NEEDS_ATTENTION", attentionStage="AUDIO_MASTER",
                    message="Audio production stalled before the durable mux checkpoint. Preserved existing assets; no automatic provider regeneration.")
            return self._message(record, audio_job.message or "Rendering the audio master.")
        if audio_job.stage == AudioFinishingJobStage.FAILED:
            # An authenticated operator may authorize exactly one infrastructure
            # repair for a particular failed audio job. Other failures retain
            # the normal quarantine behavior and are never retried blindly.
            repair_key = f"audio-infra-repair:{audio_job.job_id}"
            if record.session.attempts.get(repair_key) == 1:
                # Mark the grant consumed *before* scheduling work, so another
                # supervisor invocation cannot independently spend it.
                record = self._save(
                    record,
                    attempts={**record.session.attempts, repair_key: 2},
                    message="Starting repaired Google TTS audio using the delivered visual master.",
                )
                replacement = await self._create_audio(assembly_job.job_id)
                return self._save(
                    record, currentAudioJobId=replacement.job_id,
                    message="Retrying audio master with corrected TTS SDK; approved visual assets preserved.",
                )
            return self._quarantine(record, program, "AUDIO_MASTER", audio_job.error or "Audio finishing failed.", "TECHNICAL")
        # Authenticated caption recovery: consume the grant before creating a fresh
        # audio version. This reuses approved visual assets and regenerates voice
        # narration only as part of the existing audio finishing stage.
        speech_repair_key = f"speech-caption-repair:{audio_job.job_id}"
        if (audio_job.stage == AudioFinishingJobStage.DELIVERED
                and record.session.attempts.get(speech_repair_key) == 1):
            record = self._save(record,
                attempts={**record.session.attempts, speech_repair_key: 2},
                message="Claimed speech-caption repair; regenerating narration using existing visual master.")
            replacement = await self._create_audio(assembly_job.job_id)
            return self._save(record, currentAudioJobId=replacement.job_id,
                message="Creating speech-aligned audio master using approved Veo visuals; fresh reviews required.")
        # A one-time, operator-authorized audio quality retry is handled before
        # AI review. Never silently approve legacy AI-salvaged audio, and do
        # not re-render the visual master or attempt to publish this old mix.
        quality_repair_key = f"audio-quality-repair:{audio_job.job_id}"
        if (
            audio_job.stage == AudioFinishingJobStage.DELIVERED
            and record.session.attempts.get(quality_repair_key) == 1
        ):
            record = self._save(
                record,
                attempts={**record.session.attempts, quality_repair_key: 2},
                message="Claimed one audio-only quality retry; visual master remains unchanged.",
            )
            # Use the normal service helper, which creates a new version from
            # the last audio mix and enforces the existing per-assembly guard.
            replacement = await self._create_audio(assembly_job.job_id)
            return self._save(
                record,
                currentAudioJobId=replacement.job_id,
                message="Rendering replacement audio with duration safeguards and fresh AI review required.",
            )
        if audio_job.stage in {AudioFinishingJobStage.COMPLETED, AudioFinishingJobStage.DELIVERED} and not _audio_master_ai_passed(audio_job, assembly_job):
            # A salvaged review retains an asset but is not an AI quality approval.
            # Re-reviewing an unchanged salvaged asset on every supervisor heartbeat
            # makes no progress and can incur repeated reviewer costs.
            audio_detail = _detail(audio_job.detail)
            audio_review = _detail(audio_detail.get("ai_audio_review"))
            originally_rejected = str(audio_review.get("original_decision") or "").upper() in {"REGENERATE", "FAIL", "REJECT"}
            salvaged = str(audio_review.get("outcome") or "").upper() == "AI_SALVAGED" or audio_detail.get("ai_salvaged_audio_master") is True
            if salvaged and originally_rejected:
                issues = audio_review.get("issues")
                if isinstance(issues, list):
                    explanation = "; ".join(str(issue).strip() for issue in issues if str(issue).strip())
                else:
                    explanation = ""
                explanation = explanation or str(audio_review.get("summary") or "Unresolved audio quality concerns")
                return self._save(
                    record,
                    status="NEEDS_ATTENTION",
                    attentionStage="AUDIO_MASTER",
                    message=(
                        "Audio review did not pass: the saved mix was AI-salvaged after a regeneration recommendation. "
                        "No automatic replay or publication will occur. Correct the audio before resuming. "
                        + explanation[:700]
                    ),
                )
            from app.api.routes.ai_review import ai_review_audio_master
            background = BackgroundTasks()
            reviewed = await ai_review_audio_master(audio_job.job_id, background, self.settings)
            self._spawn_background(background)
            # The reviewer can return the same job with a salvaged decision.
            # Re-evaluate on the next tick, where the guard above will pause it.
            return self._save(record, currentAudioJobId=reviewed.job_id, message="AI audio reviewer checked narration, music, ambience, and mix balance.")

        versions = audio_finishing_job_store.list_for_assembly_job(assembly_job.job_id)
        approved_master = next((item for item in versions if _audio_master_ai_passed(item, assembly_job)), None)
        if not approved_master:
            return record
        if approved_master.job_id != record.session.currentAudioJobId:
            record = self._save(record, currentAudioJobId=approved_master.job_id)

        # Deterministic delivery QC.
        try:
            qc = delivery_qc_store.get(approved_master.job_id)
        except DeliveryQcReportNotFoundError:
            from app.api.routes.delivery_qc import create_delivery_qc
            qc = await create_delivery_qc(approved_master.job_id, self.settings)
            return self._message(record, "Deterministic final delivery QC completed.")
        if qc.overall_status == DeliveryQcOverallStatus.BLOCKED:
            return self._quarantine(record, program, "DELIVERY_QC", "Deterministic Final Delivery QC found a blocking technical failure. AI cannot override it.", "TECHNICAL")
        if qc.overall_status == DeliveryQcOverallStatus.REVIEW:
            from app.api.routes.ai_review import ai_review_qc_warnings
            await ai_review_qc_warnings(approved_master.job_id, self.settings)
            return self._message(record, "AI reviewer evaluated non-blocking delivery-QC warnings.")

        # Package.
        package = delivery_package_store.latest_for_audio_job(approved_master.job_id)
        if not package or package.qc_report_id != qc.report_id:
            from app.api.routes.delivery_package import build_delivery_package
            package = await build_delivery_package(approved_master.job_id, self.settings)
            return self._save(record, currentDeliveryPackageId=package.package_id, message="QC passed. Created the versioned delivery package.")
        if record.session.currentDeliveryPackageId != package.package_id:
            record = self._save(record, currentDeliveryPackageId=package.package_id)

        # Publishing copy.
        draft = publishing_draft_store.latest_for_audio_job(approved_master.job_id)
        if not draft:
            from app.api.routes.publishing_assistant import create_publishing_draft
            draft = await create_publishing_draft(approved_master.job_id, self.settings)
            return self._save(record, currentPublishingDraftId=draft.draft_id, message="Delivery package is ready. Generated creator-editable publishing copy.")
        if draft.status != PublishingDraftStatus.APPROVED or "[AI_REVIEW_APPROVED]" not in (draft.generation_note or ""):
            from app.api.routes.ai_review import ai_review_publishing_copy
            draft = await ai_review_publishing_copy(draft.draft_id, self.settings)
            return self._save(record, currentPublishingDraftId=draft.draft_id, message="AI publishing critic reviewed titles, captions, hashtags, accessibility text, and consistency.")
        if record.session.currentPublishingDraftId != draft.draft_id:
            record = self._save(record, currentPublishingDraftId=draft.draft_id)

        if package.publishing_draft_id != draft.draft_id:
            from app.api.routes.publishing_assistant import add_publishing_to_delivery_package
            package = await add_publishing_to_delivery_package(draft.draft_id, self.settings)
            return self._save(record, currentDeliveryPackageId=package.package_id, message="Publishing copy passed AI review and was added to the final delivery package.")

        # Fail closed before final human approval unless every AI gate is verifiable.
        final_detail = _detail(production_job.detail)
        final_plan_review = _detail(final_detail.get("ai_plan_review"))
        final_plan_review_current = (
            str(final_detail.get("ai_plan_review_for_generated_at") or "")
            == str(brief.model_dump(mode="json").get("generated_at") or "")
        )
        plan_ok = (
            brief.review_status == ProductionReviewStatus.APPROVED
            and str(final_detail.get("approval_actor") or "").upper() == "AI"
            and final_plan_review_current
            and _ai_pass(final_plan_review)
        )
        all_gates = all([
            plan_ok,
            _reference_ai_passed(media_job),
            _keyframes_ai_passed(media_job),
            _clips_ai_passed(media_job),
            _visual_master_ai_passed(assembly_job, media_job),
            _audio_master_ai_passed(approved_master, assembly_job),
            qc.overall_status == DeliveryQcOverallStatus.READY,
            draft.status == PublishingDraftStatus.APPROVED,
            package.publishing_draft_id == draft.draft_id,
        ])
        if not all_gates:
            return self._quarantine(record, program, "FAILURE", "Final handoff verification found an incomplete AI review gate. Final approval remains locked.", "TECHNICAL")

        autonomous_final_approval = bool(
            self.settings.autopilot_autonomous_final_approval_enabled
        )
        policy = channel_policy_store.get(program.channel_id)
        if approved_master.result and approved_master.result.total_duration_seconds > policy.max_final_video_duration_seconds:
            return self._save(record, status="NEEDS_ATTENTION", attentionStage="FINAL_VIDEO", message="Final video exceeds the channel maximum duration. Adjust production and re-render before publishing.")
        autonomous_publish = bool(self.settings.autopilot_autonomous_publish_enabled) and policy.autonomous_publishing_enabled

        if autonomous_final_approval:
            existing_publication = youtube_publishing_service.latest_for_recommendation(recommendation_id)

            if not autonomous_publish:
                # Support a controlled rollout where ReviveAI may approve the final
                # master autonomously without being allowed to publish it yet.
                # PAUSED is deliberate: enabling publishing later requires an explicit
                # Resume action, so a configuration change alone cannot trigger upload.
                try:
                    already_logged = any(
                        event.action == "AUTONOMOUS_FINAL_APPROVAL"
                        and event.recommendation_id == recommendation_id
                        for event in autonomous_activity_store.list(limit=500)
                    )
                    if not already_logged:
                        autonomous_activity_store.append(
                            phase="FINAL_VIDEO",
                            action="AUTONOMOUS_FINAL_APPROVAL",
                            status="SUCCESS",
                            message="Autonomous final approval granted after all required AI review gates and deterministic delivery QC passed.",
                            recommendation_id=recommendation_id,
                            production_job_id=production_job.job_id,
                            media_job_id=media_job.job_id,
                            assembly_job_id=assembly_job.job_id,
                            audio_job_id=approved_master.job_id,
                            package_id=package.package_id,
                            publishing_draft_id=draft.draft_id,
                            details={
                                "approval_actor": "AI_AUTOPILOT",
                                "qc_status": qc.overall_status.value,
                                "publishing_enabled": False,
                            },
                        )
                except Exception:
                    logger.exception("Could not log autonomous final approval")
                return self._save(
                    record,
                    status="PAUSED",
                    attentionStage=None,
                    message=(
                        "Autonomous final approval passed. YouTube publishing is still disabled, "
                        "so ReviveAI paused before upload. Enable autonomous publishing and resume "
                        "when you are ready."
                    ),
                )

            if not youtube_publishing_service.connection().connected:
                return self._save(
                    record,
                    status="NEEDS_ATTENTION",
                    attentionStage="PUBLISHING_COPY",
                    message="Autonomous production is ready to publish, but no YouTube channel is connected. Connect YouTube once, then resume Autopilot.",
                )

            if existing_publication is None:
                publications = youtube_publishing_service.list()
                latest_snapshots = {p.publication_id: youtube_publishing_service.latest_snapshot(p.publication_id) for p in publications}
                plan = self._publish_planner.choose(publications=publications, latest_snapshots=latest_snapshots, channel_id=program.channel_id)
                try:
                    autonomous_activity_store.append(
                        phase="FINAL_VIDEO",
                        action="AUTONOMOUS_FINAL_APPROVAL",
                        status="SUCCESS",
                        message="Autonomous final approval granted after all required AI review gates and deterministic delivery QC passed.",
                        recommendation_id=recommendation_id,
                        production_job_id=production_job.job_id,
                        media_job_id=media_job.job_id,
                        assembly_job_id=assembly_job.job_id,
                        audio_job_id=approved_master.job_id,
                        package_id=package.package_id,
                        publishing_draft_id=draft.draft_id,
                        details={
                            "approval_actor": "AI_AUTOPILOT",
                            "qc_status": qc.overall_status.value,
                            "scheduled_public_at": plan.publish_at.isoformat(),
                            "schedule_reason": plan.reason,
                        },
                    )
                except Exception:
                    logger.exception("Could not log autonomous final approval")
                from app.services.autopilot_side_effect_fence import require_supervisor_lease
                require_supervisor_lease("autonomous YouTube publish request")
                existing_publication = await youtube_publishing_service.publish(
                    YouTubePublishRequest(
                        package_id=package.package_id,
                        publishing_draft_id=draft.draft_id,
                        recommendation_id=recommendation_id,
                        program_id=record.session.programId,
                        production_job_id=production_job.job_id,
                        media_job_id=media_job.job_id,
                        assembly_job_id=assembly_job.job_id,
                        audio_job_id=approved_master.job_id,
                        privacy_status="private",
                        publish_at=plan.publish_at,
                        recommended_public_date=plan.publish_at.date().isoformat(),
                        made_for_kids=bool(self.settings.autopilot_youtube_made_for_kids),
                        contains_synthetic_media=bool(self.settings.autopilot_youtube_contains_synthetic_media),
                        schedule_reason=plan.reason,
                        autonomous=True,
                    )
                )
                record = self._save(
                    record,
                    currentPublicationId=existing_publication.publication_id,
                    message=(
                        f"Autonomous final approval passed. Uploading the master to YouTube now and scheduling public release for "
                        f"{plan.publish_at.isoformat()} UTC."
                    ),
                )
            elif getattr(record.session, "currentPublicationId", None) != existing_publication.publication_id:
                record = self._save(record, currentPublicationId=existing_publication.publication_id)

            if existing_publication.status == YouTubePublishStatus.UPLOADING:
                existing_publication = await youtube_publishing_service.retry(existing_publication.publication_id)
                if existing_publication.status == YouTubePublishStatus.UPLOADING:
                    return self._message(record, "YouTube upload is in progress. ReviveAI will resume the persisted upload session automatically if interrupted.")
            if existing_publication.status == YouTubePublishStatus.FAILED:
                return self._save(
                    record,
                    status="NEEDS_ATTENTION",
                    attentionStage="FINAL_VIDEO",
                    message=existing_publication.error or "Autonomous YouTube publishing failed and was stopped to prevent a duplicate upload.",
                )
            if existing_publication.status not in {YouTubePublishStatus.SCHEDULED, YouTubePublishStatus.PUBLISHED}:
                return self._message(record, "Waiting for YouTube to accept the autonomous publication.")
        elif not _human_final_approved(approved_master):
            return self._save(
                record,
                status="WAITING_FOR_FINAL_APPROVAL",
                attentionStage="FINAL_VIDEO",
                message="Production complete. Every required AI review gate passed. Watch the finished picture + sound and approve the final video.",
            )

        completed = list(dict.fromkeys([*record.session.completedRecommendationIds, recommendation_id]))
        blocked = [item for item in record.session.blockedProductions if item.recommendationId != recommendation_id]

        if bool(self.settings.autopilot_continuous_campaign_enabled) and getattr(record.session, "currentPublicationId", None):
            try:
                self._ensure_learning_workspace(program, recovery_job)
            except Exception:
                logger.exception("Could not bootstrap continuous learning workspace")
            required = str(self.settings.autopilot_next_production_checkpoint or "6H").upper()
            return self._save(
                record,
                scope="CAMPAIGN",
                status="WAITING_FOR_LEARNING",
                attentionStage=None,
                completedRecommendationIds=completed,
                blockedProductions=blocked,
                learningCheckpointRequired=required,
                learningWaitStartedAt=_now_iso(),
                message=(
                    f"Production and autonomous publication handoff are complete. Continuous Autopilot will wait for the {required} learning checkpoint before choosing the next idea."
                ),
            )

        if record.session.scope == "PRODUCTION":
            return self._save(record, status="COMPLETED", attentionStage=None, completedRecommendationIds=completed, blockedProductions=blocked, message="Individual production complete. AI Autopilot finished this video and will not start another production.")
        return self._save(
            record,
            status="RUNNING",
            attentionStage=None,
            currentRecommendationId=None,
            currentTitle=None,
            currentStartedAt=None,
            currentProductionJobId=None,
            currentMediaJobId=None,
            currentAssemblyJobId=None,
            currentAudioJobId=None,
            currentDeliveryPackageId=None,
            currentPublishingDraftId=None,
            currentPublicationId=None,
            completedRecommendationIds=completed,
            blockedProductions=blocked,
            message="Production complete. Moving to the next revival idea.",
        )

    async def advance_current_tenant(self) -> AutopilotStateRecord | None:
        record = autopilot_state_store.get()
        if not record or not self._status_is_actionable(record.session):
            return record
        try:
            return await self.advance(record)
        except AutopilotStateConflictError:
            # The creator may have paused/resumed in another tab while this tick was
            # running. Never overwrite the newer state; the next queue tick reconciles.
            logger.info("Autopilot supervisor state changed concurrently; skipping stale tick")
            return autopilot_state_store.get()
        except HTTPException as exc:
            logger.warning("Autopilot supervisor endpoint action failed: %s", exc.detail)
            try:
                latest = autopilot_state_store.get()
                if latest and self._status_is_actionable(latest.session):
                    return self._save(latest, status="NEEDS_ATTENTION", attentionStage="FAILURE", message=str(exc.detail))
            except AutopilotStateConflictError:
                return autopilot_state_store.get()
            return autopilot_state_store.get()
        except Exception as exc:
            logger.exception("Autopilot supervisor tick failed")
            try:
                latest = autopilot_state_store.get()
                if latest and self._status_is_actionable(latest.session):
                    return self._save(latest, status="NEEDS_ATTENTION", attentionStage="FAILURE", message=f"Headless Autopilot paused after an unexpected backend error: {exc}")
            except AutopilotStateConflictError:
                return autopilot_state_store.get()
            return autopilot_state_store.get()


autopilot_supervisor_service = AutopilotSupervisorService()
