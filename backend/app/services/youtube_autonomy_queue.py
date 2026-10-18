from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.task_execution import in_internal_task
from app.core.tenant import tenant_namespace


@dataclass(frozen=True)
class YouTubeAutonomyQueueItem:
    namespace: str
    next_run_at: datetime | None


class YouTubeAutonomyQueue:
    COLLECTION = "reviveai_youtube_autonomy"

    def _collection(self):
        return get_runtime_firestore_client().collection(self.COLLECTION)

    def _dispatch(self, namespace: str, run_at: datetime, reason: str) -> bool:
        settings = get_settings()
        if not settings.autopilot_event_driven_enabled:
            return False
        from app.services.cloud_task_dispatcher import cloud_task_dispatcher
        return cloud_task_dispatcher.schedule_youtube(namespace, schedule_at=run_at, reason=reason)

    def sync(self, *, active: bool = True, next_run_seconds: float = 0.0) -> None:
        ns = tenant_namespace()
        now = datetime.now(timezone.utc)
        run_at = now + timedelta(seconds=max(0.0, float(next_run_seconds)))
        self._collection().document(ns).set({"namespace": ns, "active": bool(active), "next_run_at": run_at, "updated_at": now}, merge=True)
        if active and not in_internal_task():
            self._dispatch(ns, run_at, "publication-state-changed")

    def defer(self, namespace: str, seconds: float, *, reason: str = "defer") -> None:
        now = datetime.now(timezone.utc)
        run_at = now + timedelta(seconds=max(0.0, float(seconds)))
        self._collection().document(namespace).set({"next_run_at": run_at, "updated_at": now}, merge=True)
        self._dispatch(namespace, run_at, reason)

    def deactivate(self, namespace: str) -> None:
        self._collection().document(namespace).set({"active": False, "updated_at": datetime.now(timezone.utc)}, merge=True)

    def bootstrap(self) -> int:
        """Repair missing tenant queue documents without resetting future wake-ups.

        Queue documents are authoritative after evidence and release-clock upgrades.
        Normal recovery sweeps create missing documents as immediately due and
        leave existing future wake-ups unchanged.
        """
        client = get_runtime_firestore_client()
        found: set[str] = set()
        try:
            snapshots = client.collection_group("youtube_publications").stream()
        except Exception:
            return 0
        now = datetime.now(timezone.utc)
        for snap in snapshots:
            try:
                tenant_doc = snap.reference.parent.parent
                ns = str(tenant_doc.id if tenant_doc else "").strip()
                if not ns or ns in found:
                    continue
                found.add(ns)
                ref = self._collection().document(ns)
                existing = ref.get()
                data = (existing.to_dict() or {}) if existing.exists else {}
                # One wake-up after this upgrade repairs old completed-zero
                # checkpoints, even if their tenant queue was deactivated.
                # Later sweeps keep the stored next_run_at authoritative.
                if (not existing.exists or int(data.get("performance_evidence_version") or 0) < 2
                        or int(data.get("publication_clock_version") or 0) < 2):
                    ref.set({
                        "namespace": ns,
                        "active": True,
                        "next_run_at": now,
                        "updated_at": now,
                        "performance_evidence_version": 2,
                        "publication_clock_version": 2,
                    }, merge=True)
            except Exception:
                continue
        return len(found)

    def get_due(self, namespace: str) -> YouTubeAutonomyQueueItem | None:
        snap = self._collection().document(namespace).get()
        if not snap.exists: return None
        data = snap.to_dict() or {}
        if not bool(data.get("active", False)): return None
        next_run_at = data.get("next_run_at")
        now = datetime.now(timezone.utc)
        if isinstance(next_run_at, datetime) and next_run_at > now + timedelta(seconds=2): return None
        return YouTubeAutonomyQueueItem(str(data.get("namespace") or snap.id), next_run_at if isinstance(next_run_at, datetime) else None)

    def list_due(self, *, limit: int = 25) -> list[YouTubeAutonomyQueueItem]:
        now = datetime.now(timezone.utc)
        out: list[YouTubeAutonomyQueueItem] = []
        for snap in self._collection().stream():
            data = snap.to_dict() or {}
            if not bool(data.get("active", False)): continue
            next_run_at = data.get("next_run_at")
            if isinstance(next_run_at, datetime) and next_run_at > now: continue
            out.append(YouTubeAutonomyQueueItem(str(data.get("namespace") or snap.id), next_run_at if isinstance(next_run_at, datetime) else None))
            if len(out) >= max(1, int(limit)): break
        return out

    def schedule_pending(self) -> int:
        """Schedule only active queue entries that are already due.

        defer()/sync() own normal future scheduling. The hourly recovery sweep only
        repairs work whose due time has passed, which avoids duplicate future Cloud Tasks.
        """
        now = datetime.now(timezone.utc)
        count = 0
        for snap in self._collection().stream():
            data = snap.to_dict() or {}
            if not bool(data.get("active", False)):
                continue
            run_at = data.get("next_run_at")
            if isinstance(run_at, datetime) and run_at > now:
                continue
            if self._dispatch(str(data.get("namespace") or snap.id), now, "recovery-sweep-due"):
                count += 1
        return count

    def acquire_lease(self, *, namespace: str, owner: str, lease_seconds: int) -> bool:
        from google.cloud import firestore
        ref = self._collection().document(namespace)
        tx = get_runtime_firestore_client().transaction()
        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=max(30, int(lease_seconds)))
        @firestore.transactional
        def _acquire(transaction):
            snap = ref.get(transaction=transaction)
            if not snap.exists: return False
            data = snap.to_dict() or {}
            if not bool(data.get("active", False)): return False
            current_owner = str(data.get("lease_owner") or "")
            expiry = data.get("lease_expires_at")
            if current_owner and current_owner != owner and isinstance(expiry, datetime) and expiry > now: return False
            transaction.set(ref, {"lease_owner": owner, "lease_expires_at": expires, "lease_acquired_at": now}, merge=True)
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


youtube_autonomy_queue = YouTubeAutonomyQueue()
