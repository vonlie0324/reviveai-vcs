from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.task_execution import in_internal_task


@dataclass(frozen=True)
class AutopilotQueueItem:
    namespace: str
    status: str
    revision: int
    execution_owner: str
    next_run_at: Optional[datetime]


class AutopilotSupervisorQueue:
    COLLECTION = "reviveai_autopilot_supervisor"

    def _collection(self):
        return get_runtime_firestore_client().collection(self.COLLECTION)

    @staticmethod
    def _allowed_statuses() -> set[str]:
        settings = get_settings()
        statuses = {"RUNNING"}
        if settings.autopilot_autonomous_final_approval_enabled:
            statuses.add("WAITING_FOR_FINAL_APPROVAL")
        if settings.autopilot_continuous_campaign_enabled:
            statuses.update({"WAITING_FOR_LEARNING", "COMPLETED"})
        return statuses

    def _dispatch(self, namespace: str, run_at: datetime, reason: str) -> bool:
        settings = get_settings()
        if not settings.autopilot_event_driven_enabled:
            return False
        from app.services.cloud_task_dispatcher import cloud_task_dispatcher
        return cloud_task_dispatcher.schedule_autopilot(namespace, schedule_at=run_at, reason=reason)

    def bootstrap_from_persisted_states(self) -> int:
        """Repair queue documents from durable Autopilot state without disturbing future wake-ups.

        v3.5 originally called sync() here, which resets next_run_at to "now" for
        actionable sessions. An hourly recovery sweep (or a Cloud Run cold start) could
        therefore create redundant tasks even when an exact future wake-up already
        existed. v3.5.2 preserves a queue document whose revision already matches the
        durable state and only makes the item due immediately when the queue is missing
        or stale.
        """
        from app.services.firestore_job_repository import FirestoreJobRepository

        client = get_runtime_firestore_client()
        repository = FirestoreJobRepository("autopilot_state")
        seen: set[str] = set()
        count = 0
        now = datetime.now(timezone.utc)
        try:
            snapshots = client.collection_group("autopilot_state").stream()
        except Exception:
            return 0
        for snapshot in snapshots:
            if snapshot.id != "active_session":
                continue
            try:
                tenant_doc = snapshot.reference.parent.parent
                namespace = str(tenant_doc.id if tenant_doc else "").strip()
                if not namespace or namespace in seen:
                    continue
                seen.add(namespace)
                payload = repository.load("active_session", namespace=namespace)
                session = payload.get("session") if isinstance(payload, dict) else None
                if not isinstance(session, dict):
                    continue

                status = str(session.get("status") or "IDLE")
                revision = int(payload.get("revision") or 0)
                owner = str(session.get("executionOwner") or "FRONTEND").upper()
                has_publication = bool(session.get("currentPublicationId"))
                actionable = (
                    status in self._allowed_statuses()
                    and owner == "BACKEND"
                    and (status != "COMPLETED" or has_publication or get_settings().autopilot_auto_replenish_enabled)
                )

                ref = self._collection().document(namespace)
                existing = ref.get()
                existing_data = existing.to_dict() or {} if existing.exists else {}
                same_state = (
                    existing.exists
                    and int(existing_data.get("revision") or 0) == revision
                    and str(existing_data.get("status") or "") == status
                    and str(existing_data.get("execution_owner") or "FRONTEND").upper() == owner
                    and bool(existing_data.get("has_current_publication", False)) == has_publication
                )
                queue_payload = {
                    "namespace": namespace,
                    "status": status,
                    "revision": revision,
                    "execution_owner": owner,
                    "has_current_publication": has_publication,
                    "state_updated_at": now,
                }
                if actionable and not same_state:
                    queue_payload["next_run_at"] = now
                ref.set(queue_payload, merge=True)
                count += 1
            except Exception:
                continue
        return count

    def sync(self, *, namespace: str, status: str, revision: int, execution_owner: str = "FRONTEND", has_current_publication: bool = False) -> None:
        now = datetime.now(timezone.utc)
        owner = str(execution_owner or "FRONTEND").upper()
        payload = {"namespace": namespace, "status": status, "revision": int(revision), "execution_owner": owner, "state_updated_at": now}
        actionable = status in self._allowed_statuses() and owner == "BACKEND" and (status != "COMPLETED" or bool(has_current_publication) or get_settings().autopilot_auto_replenish_enabled)
        payload["has_current_publication"] = bool(has_current_publication)
        if actionable:
            payload["next_run_at"] = now
        self._collection().document(namespace).set(payload, merge=True)
        # External/browser saves kick the first task. Saves produced inside a task are
        # followed by an explicit defer() and must not recursively enqueue an immediate task.
        if actionable and not in_internal_task():
            self._dispatch(namespace, now, f"state:{status}:revision:{revision}")

    def clear(self, namespace: str) -> None:
        self._collection().document(namespace).delete()

    def defer(self, namespace: str, seconds: float, *, reason: str = "defer") -> bool:
        """Persist the wake-up and report whether its Cloud Task was dispatched.

        A persisted next_run_at alone is not proof of an actual task enqueue;
        an hourly recovery sweep is only a fallback. Callers needing guaranteed
        delivery can return a retryable non-2xx response if this returns False.
        """
        run_at = datetime.now(timezone.utc) + timedelta(seconds=max(0.0, float(seconds)))
        self._collection().document(namespace).set({"next_run_at": run_at}, merge=True)
        if not get_settings().autopilot_event_driven_enabled:
            return True
        return bool(self._dispatch(namespace, run_at, reason))

    @staticmethod
    def _maintenance_active(data: dict, now: datetime) -> bool:
        """Recovery maintenance is authoritative only while its lease is active."""
        maintenance = data.get("recovery_maintenance") or {}
        expires = maintenance.get("expires_at")
        if not isinstance(expires, datetime) or not maintenance.get("owner"):
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > now

    def acquire_recovery_maintenance(self, *, namespace: str, audio_job_id: str,
                                     owner: str, expected_revision: int,
                                     lease_seconds: int = 120) -> int:
        """Claim tenant supervisor exclusion; 0 means claim refused.

        Does not modify the audio job or represent a production recovery commit.
        """
        from google.cloud import firestore
        if not namespace or not audio_job_id or not owner or lease_seconds < 10:
            raise ValueError("Valid namespace, job, owner and lease_seconds >= 10 required")
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        @firestore.transactional
        def _claim(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return 0
            data = snap.to_dict() or {}
            now = datetime.now(timezone.utc)
            if (int(data.get("revision") or 0) != int(expected_revision)
                    or str(data.get("status") or "") != "RUNNING"
                    or str(data.get("execution_owner") or "").upper() != "BACKEND"):
                return 0
            if self._maintenance_active(data, now): return 0
            worker_expiry = data.get("lease_expires_at")
            if isinstance(worker_expiry, datetime):
                if worker_expiry.tzinfo is None:
                    worker_expiry = worker_expiry.replace(tzinfo=timezone.utc)
                # Even if lease_owner has not been stored, fail closed on a live lease.
                if worker_expiry > now: return 0
            current = data.get("recovery_maintenance") or {}
            generation = int(current.get("generation") or 0) + 1
            transaction.set(ref, {"recovery_maintenance": {
                "owner": owner, "audio_job_id": audio_job_id,
                "generation": generation, "expected_revision": int(expected_revision),
                "claimed_at": now,
                "expires_at": now + timedelta(seconds=int(lease_seconds)),
            }}, merge=True)
            return generation
        return int(_claim(tx))

    def renew_recovery_maintenance(self, *, namespace: str, owner: str,
                                   generation: int, lease_seconds: int = 120) -> bool:
        """Renew only the currently active, generation-fenced maintenance claim."""
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        @firestore.transactional
        def _renew(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return False
            data = snap.to_dict() or {}
            now = datetime.now(timezone.utc)
            m = data.get("recovery_maintenance") or {}
            if (not self._maintenance_active(data, now)
                    or m.get("owner") != owner
                    or int(m.get("generation") or 0) != int(generation)
                    or int(data.get("revision") or 0) != int(m.get("expected_revision") or -1)):
                return False
            transaction.set(ref, {"recovery_maintenance": {**m,
                "expires_at": now + timedelta(seconds=max(10, int(lease_seconds))),
                "renewed_at": now}}, merge=True)
            return True
        return bool(_renew(tx))

    def release_recovery_maintenance(self, *, namespace: str, owner: str,
                                     generation: int) -> bool:
        """Release without resetting generation; stale owners cannot release it."""
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        @firestore.transactional
        def _release(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return False
            data = snap.to_dict() or {}
            m = data.get("recovery_maintenance") or {}
            if m.get("owner") != owner or int(m.get("generation") or 0) != int(generation):
                return False
            now = datetime.now(timezone.utc)
            transaction.set(ref, {"recovery_maintenance": {**m,
                "owner": None, "expires_at": now, "released_at": now}}, merge=True)
            return True
        return bool(_release(tx))

    def assert_supervisor_lease(self, *, namespace: str, owner: str) -> bool:
        """Read-only side-effect boundary; fail closed on missing/expired lease or maintenance.

        Not a replacement for fencing within each irreversible service operation.
        """
        if not namespace or not owner:
            return False
        snap = self._collection().document(namespace).get()
        if not snap.exists:
            return False
        data = snap.to_dict() or {}
        now = datetime.now(timezone.utc)
        if self._maintenance_active(data, now):
            return False
        expiry = data.get("lease_expires_at")
        if not isinstance(expiry, datetime):
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return (data.get("lease_owner") == owner and expiry > now
                and str(data.get("execution_owner") or "").upper() == "BACKEND")

    def renew_lease(self, *, namespace: str, owner: str, lease_seconds: int) -> bool:
        """Renew only an unexpired lease still held by this owner."""
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        @firestore.transactional
        def _renew(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists:
                return False
            data = snap.to_dict() or {}
            now = datetime.now(timezone.utc)
            if self._maintenance_active(data, now): return False
            expires = data.get("lease_expires_at")
            if (data.get("lease_owner") != owner or not isinstance(expires, datetime)
                    or expires <= now):
                return False
            transaction.set(ref, {"lease_expires_at": now + timedelta(seconds=max(10, int(lease_seconds))),
                                  "lease_renewed_at": now}, merge=True)
            return True
        return bool(_renew(tx))

    def get_due(self, namespace: str) -> AutopilotQueueItem | None:
        snap = self._collection().document(namespace).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        if self._maintenance_active(data, datetime.now(timezone.utc)): return None
        status = str(data.get("status") or "")
        if status not in self._allowed_statuses():
            return None
        if status == "COMPLETED" and not bool(data.get("has_current_publication", False)) and not get_settings().autopilot_auto_replenish_enabled:
            return None
        if str(data.get("execution_owner") or "FRONTEND").upper() != "BACKEND":
            return None
        next_run_at = data.get("next_run_at")
        now = datetime.now(timezone.utc)
        if isinstance(next_run_at, datetime) and next_run_at > now + timedelta(seconds=2):
            return None
        return AutopilotQueueItem(str(data.get("namespace") or snap.id), status, int(data.get("revision") or 0), "BACKEND", next_run_at if isinstance(next_run_at, datetime) else None)

    def list_running(self, *, limit: int = 25, include_waiting_final_approval: bool = False, include_waiting_learning: bool = False, include_completed: bool = False) -> list[AutopilotQueueItem]:
        now = datetime.now(timezone.utc)
        statuses = {"RUNNING"}
        if include_waiting_final_approval: statuses.add("WAITING_FOR_FINAL_APPROVAL")
        if include_waiting_learning: statuses.add("WAITING_FOR_LEARNING")
        if include_completed: statuses.add("COMPLETED")
        out: list[AutopilotQueueItem] = []
        for snap in self._collection().stream():
            data = snap.to_dict() or {}
            if self._maintenance_active(data, now): continue
            status = str(data.get("status") or "")
            if status not in statuses or str(data.get("execution_owner") or "FRONTEND").upper() != "BACKEND": continue
            if status == "COMPLETED" and not bool(data.get("has_current_publication", False)) and not get_settings().autopilot_auto_replenish_enabled: continue
            next_run_at = data.get("next_run_at")
            if isinstance(next_run_at, datetime) and next_run_at > now: continue
            out.append(AutopilotQueueItem(str(data.get("namespace") or snap.id), status, int(data.get("revision") or 0), "BACKEND", next_run_at if isinstance(next_run_at, datetime) else None))
            if len(out) >= max(1, int(limit)): break
        return out

    def schedule_pending(self) -> int:
        """Schedule only queue items that are already due.

        Normal state transitions/defer() create the exact future Cloud Task. The recovery
        sweep is a safety net for a missing task, not a second scheduler for every future
        item. If a future task was lost, it is recreated on the first hourly sweep after
        it becomes due.
        """
        now = datetime.now(timezone.utc)
        count = 0
        for snap in self._collection().stream():
            data = snap.to_dict() or {}
            if self._maintenance_active(data, now): continue
            status = str(data.get("status") or "")
            if status not in self._allowed_statuses():
                continue
            if status == "COMPLETED" and not bool(data.get("has_current_publication", False)) and not get_settings().autopilot_auto_replenish_enabled:
                continue
            if str(data.get("execution_owner") or "FRONTEND").upper() != "BACKEND":
                continue
            run_at = data.get("next_run_at")
            if isinstance(run_at, datetime) and run_at > now:
                continue
            if self._dispatch(str(data.get("namespace") or snap.id), now, "recovery-sweep-due"):
                count += 1
        return count

    def acquire_lease(self, *, namespace: str, owner: str, lease_seconds: int, include_waiting_final_approval: bool = False, include_waiting_learning: bool = False, include_completed: bool = False) -> bool:
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(10, int(lease_seconds)))
        statuses = {"RUNNING"}
        if include_waiting_final_approval: statuses.add("WAITING_FOR_FINAL_APPROVAL")
        if include_waiting_learning: statuses.add("WAITING_FOR_LEARNING")
        if include_completed: statuses.add("COMPLETED")
        @firestore.transactional
        def _acquire(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return False
            data = snap.to_dict() or {}
            if self._maintenance_active(data, datetime.now(timezone.utc)): return False
            status = str(data.get("status") or "")
            if status not in statuses: return False
            if status == "COMPLETED" and not bool(data.get("has_current_publication", False)) and not get_settings().autopilot_auto_replenish_enabled: return False
            if str(data.get("execution_owner") or "FRONTEND").upper() != "BACKEND": return False
            current_owner = str(data.get("lease_owner") or "")
            expiry = data.get("lease_expires_at")
            if current_owner and current_owner != owner and isinstance(expiry, datetime) and expiry > now: return False
            transaction.set(ref, {"lease_owner": owner, "lease_acquired_at": now, "lease_expires_at": expires}, merge=True)
            return True
        return bool(_acquire(tx))

    def release_lease(self, *, namespace: str, owner: str) -> None:
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        now = datetime.now(timezone.utc)
        @firestore.transactional
        def _release(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return
            data = snap.to_dict() or {}
            if str(data.get("lease_owner") or "") != owner: return
            transaction.set(ref, {"lease_owner": "", "lease_expires_at": now, "lease_released_at": now}, merge=True)
        _release(tx)


autopilot_supervisor_queue = AutopilotSupervisorQueue()
