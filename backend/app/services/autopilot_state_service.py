from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.config import get_settings
from app.core.tenant import tenant_namespace, tenant_scoped_root
from app.services.firestore_job_repository import FirestoreJobRepository
from app.core.firebase_clients import get_runtime_firestore_client


logger = logging.getLogger(__name__)


AutopilotStatus = Literal[
    "IDLE",
    "RUNNING",
    "PAUSED",
    "NEEDS_ATTENTION",
    "WAITING_FOR_FINAL_APPROVAL",
    "WAITING_FOR_LEARNING",
    "COMPLETED",
]

AutopilotBlockedResolution = Literal["RETRYABLE", "ARCHIVED", "BLOCKING"]


AutopilotAttentionStage = Optional[Literal[
    "PRODUCTION_DIRECTION",
    "REFERENCE",
    "KEYFRAMES",  # Historical persisted attention stage; preserve legacy checkpoints.
    "KEYFRAME_ADAPTATION",
    "CLIPS",
    "VISUAL_MASTER",
    "AUDIO_MASTER",
    "DELIVERY_QC",
    "PUBLISHING_COPY",
    "FINAL_VIDEO",
    "FAILURE",
]]


class AutopilotBlockedProduction(BaseModel):
    model_config = ConfigDict(extra="allow")

    recommendationId: str
    title: str
    message: str
    attentionStage: AutopilotAttentionStage = None
    blockedAt: str
    kind: Literal["INFRASTRUCTURE", "CONTENT", "TECHNICAL"]
    # Durable lineage captured at quarantine time. These fields make retry
    # deterministic even after Recovery Intelligence is rerun or the campaign
    # advances to another production. They are optional for backward compatibility
    # with sessions created before this schema existed.
    productionJobId: Optional[str] = None
    recoveryJobId: Optional[str] = None
    analysisJobId: Optional[str] = None
    # Resolution metadata separates historical production failures from true
    # campaign-level blockers. Legacy sessions hydrate with these fields unset and
    # are reconciled safely by the backend supervisor / current frontend.
    resolutionStatus: Optional[AutopilotBlockedResolution] = None
    resolutionReason: Optional[str] = None
    resolvedAt: Optional[str] = None
    blocksAutonomy: Optional[bool] = None


class AutopilotSessionPayload(BaseModel):
    """Server-persisted campaign supervisor state.

    Field names intentionally match the frontend payload. Existing job stores remain
    authoritative for actual generated assets; this document only persists orchestration
    intent/progress that used to live in localStorage.
    """

    model_config = ConfigDict(extra="allow")

    version: int = 2
    scope: Literal["CAMPAIGN", "PRODUCTION"] = "CAMPAIGN"
    status: AutopilotStatus = "IDLE"
    executionOwner: Literal["FRONTEND", "BACKEND"] = "FRONTEND"
    executionVersion: int = 1
    recoveryJobId: Optional[str] = None
    programId: Optional[str] = None
    currentProductionJobId: Optional[str] = None
    currentMediaJobId: Optional[str] = None
    currentAssemblyJobId: Optional[str] = None
    currentAudioJobId: Optional[str] = None
    currentDeliveryPackageId: Optional[str] = None
    currentPublishingDraftId: Optional[str] = None
    currentPublicationId: Optional[str] = None
    learningCheckpointRequired: Optional[str] = None
    learningWaitStartedAt: Optional[str] = None
    lastSupervisorHeartbeatAt: Optional[str] = None
    currentRecommendationId: Optional[str] = None
    currentTitle: Optional[str] = None
    currentStartedAt: Optional[str] = None
    completedRecommendationIds: list[str] = Field(default_factory=list)
    blockedProductions: list[AutopilotBlockedProduction] = Field(default_factory=list)
    attempts: dict[str, int] = Field(default_factory=dict)
    attentionStage: AutopilotAttentionStage = None
    message: str = "Ready to produce the revival slate sequentially."
    startedAt: Optional[str] = None
    updatedAt: str


class AutopilotStateRecord(BaseModel):
    revision: int
    saved_at: datetime
    session: AutopilotSessionPayload


class AutopilotStateConflictError(RuntimeError):
    def __init__(self, current: Optional[AutopilotStateRecord]):
        super().__init__("Autopilot state changed on another client.")
        self.current = current


class AutopilotStateStore:
    DOCUMENT_ID = "active_session"

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "autopilot_state"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cloud = FirestoreJobRepository("autopilot_state")
        self._archives = FirestoreJobRepository("autopilot_session_archives")

    def _path(self) -> Path:
        root = tenant_scoped_root(self._root)
        root.mkdir(parents=True, exist_ok=True)
        return root / "active_session.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[AutopilotStateRecord]:
        if not payload:
            return None
        try:
            return AutopilotStateRecord.model_validate(payload)
        except Exception:
            return None

    def _load_cloud_unlocked(self) -> Optional[AutopilotStateRecord]:
        # A transport / permission / decoding failure is NOT an absent session.
        # Fail closed instead of resurrecting a stale local checkpoint.
        payload = self._cloud.load(self.DOCUMENT_ID)
        if payload is None:
            return None
        record = self._validate_payload(payload)
        if record is None:
            raise RuntimeError("Stored Autopilot state is invalid; refusing to reset it")
        return record

    def _load_local_unlocked(self) -> Optional[AutopilotStateRecord]:
        path = self._path()
        if not path.exists():
            return None
        try:
            return AutopilotStateRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _persist_local_unlocked(self, record: AutopilotStateRecord) -> None:
        path = self._path()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud_unlocked(self, record: AutopilotStateRecord) -> None:
        """Commit a revision with a Firestore transaction, across backend processes.

        The active-session payload is small and remains repository-compatible
        inline JSON. Never replace a document if its revision changed.
        """
        payload = record.model_dump(mode="json")
        raw = self._cloud._encode(payload)
        encoded = raw.encode("utf-8")
        if len(encoded) > self._cloud.INLINE_JSON_LIMIT_BYTES:
            raise RuntimeError("Autopilot session exceeds atomic Firestore size limit")
        ref = self._cloud._collection().document(self.DOCUMENT_ID)
        transaction = get_runtime_firestore_client().transaction()

        from google.cloud import firestore

        @firestore.transactional
        def commit(tx):
            snapshot = ref.get(transaction=tx)
            if snapshot.exists:
                existing = self._cloud._decode_document(ref, snapshot.to_dict() or {})
                current = self._validate_payload(existing)
                if current is None:
                    raise RuntimeError("Existing Firestore Autopilot state is invalid")
                if current.revision != record.revision - 1:
                    raise AutopilotStateConflictError(current)
            elif record.revision != 1:
                # Cannot silently re-create a missing persisted production history.
                raise AutopilotStateConflictError(None)
            tx.set(ref, {
                "schema_version": self._cloud.SCHEMA_VERSION,
                "storage_mode": self._cloud.STORAGE_INLINE,
                "payload_json": raw,
                "payload_size_bytes": len(encoded),
                "payload_sha256": self._cloud._sha256(encoded),
                "persisted_at": datetime.now(timezone.utc),
            })

        commit(transaction)

    def _load_unlocked(self) -> Optional[AutopilotStateRecord]:
        # Firestore is the authority. A local checkpoint can be consulted for
        # diagnostics, but never silently backfilled into a missing cloud record.
        cloud = self._load_cloud_unlocked()
        if cloud is not None:
            return cloud
        local = self._load_local_unlocked()
        if local is not None:
            raise RuntimeError(
                "Autopilot cloud session is missing while a local checkpoint exists; "
                "manual reconciliation is required before any write"
            )
        return None

    def _sync_supervisor_queue_unlocked(self, record: AutopilotStateRecord) -> None:
        try:
            from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue

            autopilot_supervisor_queue.sync(
                namespace=tenant_namespace(),
                status=record.session.status,
                revision=record.revision,
                execution_owner=record.session.executionOwner,
                has_current_publication=bool(record.session.currentPublicationId),
            )
        except Exception:
            # State durability remains authoritative. A transient queue write failure is
            # recoverable on the next client/server save and must not corrupt the session.
            logger.exception("Could not synchronize the Autopilot supervisor queue")

    def _persist_unlocked(self, record: AutopilotStateRecord) -> None:
        # Successful durable commit is required in every environment. Publishing
        # local-only success creates divergent revisions on subsequent restarts.
        self._persist_cloud_unlocked(record)
        try:
            self._persist_local_unlocked(record)
        except Exception:
            logger.exception("Cloud state committed, but local Autopilot cache update failed")
        self._sync_supervisor_queue_unlocked(record)

    def get(self) -> Optional[AutopilotStateRecord]:
        with self._lock:
            record = self._load_unlocked()
            return record.model_copy(deep=True) if record else None

    def save(
        self,
        session: AutopilotSessionPayload,
        *,
        expected_revision: Optional[int] = None,
    ) -> AutopilotStateRecord:
        with self._lock:
            current = self._load_unlocked()
            current_revision = current.revision if current else 0
            # A brand new client may initialize state when no server checkpoint exists.
            # Only enforce revision matching when a checkpoint already exists.
            if current is not None and expected_revision is not None and expected_revision != current_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True))

            if current is not None and expected_revision is None:
                raise AutopilotStateConflictError(current.model_copy(deep=True))

            # Never allow a generic session PUT to discard the active production
            # lineage. Explicit trial restoration has its own guarded endpoint.
            if (current is not None and current.session.scope == "PRODUCTION"
                    and session.scope != "PRODUCTION"
                    and current.session.currentProductionJobId):
                raise AutopilotStateConflictError(current.model_copy(deep=True))

            # Cross-production replacement requires the explicit archive-and-switch
            # transition. Generic PUT can resume the same production, not lose its lineage.
            if (current is not None and current.session.scope == "PRODUCTION"
                    and current.session.currentProductionJobId
                    and (session.currentProductionJobId != current.session.currentProductionJobId)):
                raise AutopilotStateConflictError(current.model_copy(deep=True))

            # Guard against an older browser tab overwriting a newer supervisor snapshot.
            if current is not None:
                try:
                    incoming_updated = datetime.fromisoformat(session.updatedAt.replace("Z", "+00:00"))
                    current_updated = datetime.fromisoformat(current.session.updatedAt.replace("Z", "+00:00"))
                    if incoming_updated < current_updated:
                        raise AutopilotStateConflictError(current.model_copy(deep=True))
                except ValueError:
                    # The payload is already schema validated; malformed timestamps should
                    # not make persistence unavailable. Revision control still protects it.
                    pass

            record = AutopilotStateRecord(
                revision=current_revision + 1,
                saved_at=datetime.now(timezone.utc),
                session=session,
            )
            self._persist_unlocked(record)
            return record.model_copy(deep=True)

    def switch_to_production(self, *, expected_revision: int, production_job_id: str,
                             confirm: str) -> AutopilotStateRecord:
        """Archive the inactive previous session, then activate a verified saved brief.

        A revision conflict never replaces the authoritative session. The archive is
        written first so a failed archive cannot destroy existing orchestration state.
        """
        if confirm != "ARCHIVE_CURRENT_AND_START_SELECTED_PRODUCTION":
            raise ValueError("Explicit confirmation to archive the current session is required")
        from app.services.autopilot_readiness import production_readiness
        readiness = production_readiness()
        if not readiness["ready"]:
            missing = ", ".join(item["key"] for item in readiness["checks"] if not item["ready"])
            raise ValueError(f"Autopilot production preflight failed: {missing}. Check production-readiness before starting.")
        from app.services.production_brief_job_service import production_brief_job_store
        from app.services.recovery_job_service import recovery_job_store
        from app.models.recovery import RecoveryJobStage

        with self._lock:
            current = self._load_unlocked()
            if current is None or current.revision != expected_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True) if current else None)
            old = current.session
            if old.executionOwner != "BACKEND":
                raise ValueError("A backend-owned Autopilot session is required")
            if old.status not in {"IDLE", "PAUSED", "NEEDS_ATTENTION", "COMPLETED"}:
                raise ValueError("Autopilot is active; pause or take control before starting another production")
            if not production_job_id or len(production_job_id) > 160:
                raise ValueError("Invalid target production")
            brief = production_brief_job_store.get(production_job_id)
            if brief.job_id != production_job_id or not brief.recovery_job_id or not brief.recommendation_id:
                raise ValueError("Selected production has incomplete persisted lineage")
            recovery = recovery_job_store.get(brief.recovery_job_id)
            if recovery.stage != RecoveryJobStage.COMPLETED or not recovery.result:
                raise ValueError("Selected production's Recovery Intelligence is not complete")
            saved_recommendation = next(
                (item for item in recovery.result.recommendations
                 if item.recommendation_id == brief.recommendation_id), None,
            )
            if saved_recommendation is None:
                # AI-enhanced custom directions are legitimate creator-selected
                # sources, but are not members of Recovery Intelligence's ranked
                # recommendation list. Verify immutable provenance instead of
                # trusting a browser-supplied recommendation ID or title.
                snapshot = brief.source_snapshot
                detail = brief.detail or {}
                source_rec = snapshot.recommendation
                if not (
                    brief.recommendation_id.startswith("direction_")
                    and snapshot.immutable is True
                    and snapshot.recovery_job_id == recovery.job_id
                    and snapshot.channel_id == brief.channel_id
                    and source_rec.recommendation_id == brief.recommendation_id
                    and bool(source_rec.title.strip())
                    and bool(source_rec.concept.strip())
                    and bool(snapshot.source_hash)
                    and detail.get("source_snapshot_id") == snapshot.snapshot_id
                    and detail.get("source_snapshot_hash") == snapshot.source_hash
                    and brief.analysis_job_id == recovery.analysis_job_id
                    and brief.content_dna_job_id == recovery.content_dna_job_id
                ):
                    raise ValueError("Selected custom direction has inconsistent saved source lineage")
            else:
                # Standard recovery recommendations must match the saved source
                # recommendation as well as the Recovery Intelligence job.
                if (brief.source_snapshot.recovery_job_id != recovery.job_id
                        or brief.source_snapshot.channel_id != brief.channel_id
                        or brief.source_snapshot.recommendation.recommendation_id != brief.recommendation_id):
                    raise ValueError("Selected production's recovery source snapshot is inconsistent")
            # Never replace another channel's Autopilot session.
            if old.currentProductionJobId:
                existing = production_brief_job_store.get(old.currentProductionJobId)
                if existing.channel_id != brief.channel_id:
                    raise ValueError("Current and selected productions belong to different channels")
            elif old.recoveryJobId:
                previous_recovery = recovery_job_store.get(old.recoveryJobId)
                if previous_recovery.channel_id != recovery.channel_id:
                    raise ValueError("The selected production belongs to another channel")
            if old.currentProductionJobId == production_job_id and old.status == "RUNNING":
                raise ValueError("Selected production is already running")

            archive_id = "switch_" + uuid4().hex
            archived_at = datetime.now(timezone.utc).isoformat()
            self._archives.save(archive_id, {
                "archive_id": archive_id,
                "source_revision": current.revision,
                "saved_at": archived_at,
                "reason": "USER_SWITCHED_PRODUCTION",
                "target_production_job_id": production_job_id,
                "session": old.model_dump(mode="json"),
            })
            # Preserve saved artifacts through immutable job stores; do not copy the
            # previous production's media, publication, counters or recovery state.
            next_session = old.model_copy(deep=True)
            next_session.scope = "PRODUCTION"
            next_session.status = "RUNNING"
            next_session.executionOwner = "BACKEND"
            next_session.executionVersion = 1
            next_session.recoveryJobId = brief.recovery_job_id
            next_session.programId = f"production:{brief.recovery_job_id}"
            next_session.currentProductionJobId = production_job_id
            next_session.currentMediaJobId = None
            next_session.currentAssemblyJobId = None
            next_session.currentAudioJobId = None
            next_session.currentDeliveryPackageId = None
            next_session.currentPublishingDraftId = None
            next_session.currentPublicationId = None
            next_session.currentRecommendationId = brief.recommendation_id
            next_session.currentTitle = (
                (brief.result.creative_direction.working_title or "").strip()
                if brief.result and brief.result.creative_direction else ""
            ) or brief.source_snapshot.recommendation.title
            next_session.currentStartedAt = archived_at
            next_session.startedAt = archived_at
            next_session.updatedAt = archived_at
            next_session.lastSupervisorHeartbeatAt = None
            next_session.learningCheckpointRequired = None
            next_session.learningWaitStartedAt = None
            next_session.completedRecommendationIds = []
            next_session.blockedProductions = []
            next_session.attempts = {}
            next_session.attentionStage = None
            next_session.message = "Autopilot switched to the selected saved production; previous session archived."
            next_session.__pydantic_extra__ = {"previousSessionArchiveId": archive_id}
            result = AutopilotStateRecord(revision=current.revision + 1,
                                          saved_at=datetime.now(timezone.utc), session=next_session)
            self._persist_unlocked(result)
            return result.model_copy(deep=True)

    def reconcile_brief_config_replacement(self, *, expected_revision: int,
                                           failed_production_job_id: str,
                                           replacement_production_job_id: str,
                                           confirm: str) -> AutopilotStateRecord:
        """Adopt an existing replacement brief after a claimed config repair.

        This is orchestration-only: NEVER creates a brief or spends provider budget.
        Strict CAS and lineage checks prevent an unrelated job from being adopted.
        """
        if confirm != "ADOPT_EXISTING_BRIEF_NO_REGENERATION":
            raise ValueError("Explicit existing-brief reconciliation confirmation required")
        from app.services.production_brief_job_service import production_brief_job_store

        if (not failed_production_job_id or not replacement_production_job_id
                or failed_production_job_id == replacement_production_job_id):
            raise ValueError("Distinct failed and replacement production IDs are required")
        with self._lock:
            current = self._load_unlocked()
            if current is None or current.revision != expected_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True) if current else None)
            session = current.session
            claim_key = f"brief-config-repair:{failed_production_job_id}"
            # Taking control can transition an otherwise unchanged failed brief
            # from NEEDS_ATTENTION to IDLE and clear its recommendation. Only these
            # two exact shapes are eligible. No generic override of active work.
            paused_failure = (session.status == "NEEDS_ATTENTION"
                              and session.attentionStage == "FAILURE"
                              and bool(session.currentRecommendationId))
            creator_idle = (session.status == "IDLE"
                            and session.attentionStage is None
                            and session.currentRecommendationId is None
                            and session.currentTitle is None)
            if (session.scope != "PRODUCTION" or session.executionOwner != "BACKEND"
                    or not (paused_failure or creator_idle)
                    or session.currentProductionJobId != failed_production_job_id
                    or session.attempts.get(claim_key) != 1
                    or not session.recoveryJobId
                    or any((session.currentMediaJobId, session.currentAssemblyJobId,
                            session.currentAudioJobId, session.currentDeliveryPackageId,
                            session.currentPublishingDraftId, session.currentPublicationId))):
                raise ValueError("Autopilot is not at the claimed failed-brief recovery checkpoint")
            failed = production_brief_job_store.get(failed_production_job_id)
            replacement = production_brief_job_store.get(replacement_production_job_id)
            if (failed.job_id != failed_production_job_id
                    or replacement.job_id != replacement_production_job_id
                    or str(getattr(failed.stage, 'value', failed.stage)) != 'FAILED'
                    or failed.error != 'Configure REVIVEAI_GEMINI_BRIEF_RESERVATION_USD'
                    or str(getattr(replacement.stage, 'value', replacement.stage)) == 'FAILED'
                    or replacement.recovery_job_id != failed.recovery_job_id
                    or replacement.recommendation_id != failed.recommendation_id
                    or replacement.channel_id != failed.channel_id
                    or replacement.analysis_job_id != failed.analysis_job_id
                    or replacement.recovery_job_id != session.recoveryJobId
                    or (paused_failure and replacement.recommendation_id != session.currentRecommendationId)
                    or (creator_idle and not replacement.recommendation_id)):
                raise ValueError("Saved replacement brief is failed, unrelated, or has inconsistent lineage")
            now = datetime.now(timezone.utc).isoformat()
            updated = session.model_copy(deep=True)
            updated.currentProductionJobId = replacement.job_id
            # Recover the identity from trusted persisted job lineage, never from
            # browser input. Creator Mode intentionally clears these fields.
            updated.currentRecommendationId = replacement.recommendation_id
            source_recommendation = getattr(getattr(replacement, "source_snapshot", None), "recommendation", None)
            updated.currentTitle = (getattr(source_recommendation, "title", None)
                                    or getattr(source_recommendation, "working_title", None)
                                    or "Recovered production")
            updated.currentStartedAt = now
            updated.status = 'RUNNING'
            updated.attentionStage = None
            updated.attempts = {**session.attempts, claim_key: 2}
            updated.lastSupervisorHeartbeatAt = None
            updated.message = 'Existing configuration-recovery brief adopted; backend Autopilot resuming from the saved job.'
            updated.updatedAt = now
            result = AutopilotStateRecord(revision=current.revision + 1,
                                          saved_at=datetime.now(timezone.utc), session=updated)
            self._persist_unlocked(result)
            return result.model_copy(deep=True)

    def start_single_trial(self, *, expected_revision: int, recommendation_id: str, recovery_job_id: str, title: str) -> AutopilotStateRecord:
        """Safely archive an IDLE or PAUSED campaign before starting one PRODUCTION trial.

        This endpoint deliberately requires autonomous publishing to be disabled;
        it never modifies provider budgets or the existing production jobs.
        """
        with self._lock:
            current = self._load_unlocked()
            if current is None or current.revision != expected_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True) if current else None)
            if current.session.scope != "CAMPAIGN" or current.session.status not in {"IDLE", "PAUSED"}:
                raise ValueError("Only an idle or paused campaign may start a single-production trial")
            if get_settings().autopilot_autonomous_publish_enabled:
                raise ValueError("Disable AUTOPILOT_AUTONOMOUS_PUBLISH_ENABLED before running an unlisted-only trial")
            from app.services.recovery_job_service import recovery_job_store
            from app.models.recovery import RecoveryJobStage
            recovery = recovery_job_store.get(recovery_job_id)
            if recovery.stage != RecoveryJobStage.COMPLETED or not recovery.result:
                raise ValueError("The selected Recovery Intelligence run is not complete")
            if not any(r.recommendation_id == recommendation_id for r in recovery.result.recommendations):
                raise ValueError("Selected idea does not belong to the verified recovery checkpoint")
            if current.session.recoveryJobId and current.session.recoveryJobId != recovery_job_id:
                raise ValueError("Selected idea does not belong to the campaign's recovery checkpoint")
            if recommendation_id in current.session.completedRecommendationIds:
                raise ValueError("The selected idea is already complete in this campaign")
            archive_id = "campaign_" + uuid4().hex
            # Durable archive MUST succeed before changing the active session.
            self._archives.save(archive_id, {"archive_id": archive_id, "source_revision": current.revision,
                                             "saved_at": datetime.now(timezone.utc).isoformat(),
                                             "session": current.session.model_dump(mode="json")})
            now = datetime.now(timezone.utc).isoformat()
            trial = current.session.model_copy(update={
                "scope": "PRODUCTION", "status": "RUNNING", "executionOwner": "BACKEND",
                "recoveryJobId": recovery_job_id,
                "executionVersion": 1, "currentRecommendationId": recommendation_id, "currentTitle": title,
                "currentStartedAt": now, "startedAt": now, "updatedAt": now,
                "currentProductionJobId": None, "currentMediaJobId": None,
                "currentAssemblyJobId": None, "currentAudioJobId": None,
                "currentDeliveryPackageId": None, "currentPublishingDraftId": None,
                "currentPublicationId": None, "attentionStage": None,
                "learningCheckpointRequired": None, "learningWaitStartedAt": None,
                "completedRecommendationIds": [], "blockedProductions": [], "attempts": {},
                "message": "Single-production trial started. Automatic YouTube publishing is disabled; final human review is required.",
            })
            trial.__pydantic_extra__ = dict(trial.__pydantic_extra__ or {}, campaignArchiveId=archive_id)
            new_record = AutopilotStateRecord(revision=current.revision + 1, saved_at=datetime.now(timezone.utc), session=trial)
            self._persist_unlocked(new_record)
            return new_record.model_copy(deep=True)

    def restore_trial_campaign(self, *, expected_revision: int) -> AutopilotStateRecord:
        with self._lock:
            current = self._load_unlocked()
            if current is None or current.revision != expected_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True) if current else None)
            archive_id = getattr(current.session, "campaignArchiveId", None)
            if not archive_id or current.session.scope != "PRODUCTION":
                raise ValueError("No trial campaign archive is associated with this session")
            if current.session.status not in {"PAUSED", "COMPLETED", "IDLE"}:
                raise ValueError("Pause or complete the single-production trial before restoring the campaign")
            archive = self._archives.load(archive_id)
            if not archive:
                raise ValueError("The original campaign archive is unavailable; restoration refused")
            original = AutopilotSessionPayload.model_validate(archive["session"])
            if original.scope != "CAMPAIGN" or original.status not in {"IDLE", "PAUSED"}:
                raise ValueError("Stored archive is not an idle or paused campaign")
            original.updatedAt = datetime.now(timezone.utc).isoformat()
            restored = AutopilotStateRecord(revision=current.revision + 1, saved_at=datetime.now(timezone.utc), session=original)
            self._persist_unlocked(restored)
            return restored.model_copy(deep=True)

    def clear(self, *, expected_revision: Optional[int] = None) -> None:
        with self._lock:
            current = self._load_unlocked()
            current_revision = current.revision if current else 0
            if expected_revision is None or expected_revision != current_revision:
                raise AutopilotStateConflictError(current.model_copy(deep=True) if current else None)
            if current is not None and current.session.scope == "PRODUCTION" and current.session.status in {
                "RUNNING", "NEEDS_ATTENTION", "WAITING_FOR_FINAL_APPROVAL"
            }:
                raise ValueError("Pause or finish the production trial before deleting its session")

            # CAS delete; a second worker may have saved a newer revision between
            # the above read and the removal attempt.
            from google.cloud import firestore
            ref = self._cloud._collection().document(self.DOCUMENT_ID)
            transaction = get_runtime_firestore_client().transaction()

            @firestore.transactional
            def commit(tx):
                snapshot = ref.get(transaction=tx)
                if snapshot.exists:
                    actual = self._validate_payload(self._cloud._decode_document(ref, snapshot.to_dict() or {}))
                    if actual is None or actual.revision != expected_revision:
                        raise AutopilotStateConflictError(actual)
                    tx.delete(ref)
                elif current is not None:
                    raise AutopilotStateConflictError(None)

            commit(transaction)
            path = self._path()
            if path.exists():
                path.unlink()
            try:
                from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue
                autopilot_supervisor_queue.clear(tenant_namespace())
            except Exception:
                logger.exception("Could not clear the Autopilot supervisor queue")


_settings = get_settings()
autopilot_state_store = AutopilotStateStore(_settings.content_dna_checkpoint_dir)
