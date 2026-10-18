from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.services.firestore_job_repository import FirestoreJobRepository


class AutopilotOperationLeaseError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class AutopilotOperationStore:
    """Small tenant-scoped durable lease store for long AI reviewer operations.

    Reviewer heartbeats intentionally live outside the normal job documents. Updating a
    heartbeat therefore does not mutate ``job.updated_at`` and cannot masquerade as a
    durable production checkpoint in the frontend ETA/watchdog logic.
    """

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "autopilot_operations"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cloud = FirestoreJobRepository("autopilot_operations")

    @staticmethod
    def _safe_key(job_id: str, operation_key: str) -> str:
        digest = hashlib.sha256(operation_key.encode("utf-8")).hexdigest()[:16]
        safe_job = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in job_id)[:96]
        return f"{safe_job}__{digest}.json"

    @classmethod
    def _cloud_key(cls, job_id: str, operation_key: str) -> str:
        return cls._safe_key(job_id, operation_key).removesuffix(".json")

    def _path(self, job_id: str, operation_key: str) -> Path:
        root = tenant_scoped_root(self._root)
        return root / self._safe_key(job_id, operation_key)

    def _load_local(self, job_id: str, operation_key: str) -> Optional[dict[str, Any]]:
        path = self._path(job_id, operation_key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if value.get("job_id") != job_id or value.get("operation_key") != operation_key:
            return None
        return value

    def _load(self, job_id: str, operation_key: str) -> Optional[dict[str, Any]]:
        cloud_key = self._cloud_key(job_id, operation_key)
        try:
            value = self._cloud.load(cloud_key)
            if value and value.get("job_id") == job_id and value.get("operation_key") == operation_key:
                return value
        except Exception:
            pass
        local = self._load_local(job_id, operation_key)
        if local is not None:
            try:
                self._cloud.save(cloud_key, local)
            except Exception:
                pass
        return local

    def _save(self, value: dict[str, Any]) -> dict[str, Any]:
        job_id = str(value["job_id"])
        operation_key = str(value["operation_key"])
        cloud_error: Exception | None = None
        try:
            self._cloud.save(self._cloud_key(job_id, operation_key), value)
        except Exception as exc:
            cloud_error = exc
        path = self._path(job_id, operation_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the Autopilot operation lease") from cloud_error
        return dict(value)

    def get(self, job_id: str, operation_key: str) -> Optional[dict[str, Any]]:
        with self._lock:
            value = self._load(job_id, operation_key)
            return dict(value) if value else None

    def begin(
        self,
        job_id: str,
        operation_key: str,
        *,
        timeout_seconds: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        with self._lock:
            previous = self._load(job_id, operation_key)
            attempt = int((previous or {}).get("attempt") or 0) + 1
            now = _utc_now().isoformat()
            value: dict[str, Any] = {
                "lease_id": f"lease_{uuid4().hex}",
                "job_id": job_id,
                "operation_key": operation_key,
                "status": "RUNNING",
                "attempt": attempt,
                "started_at": now,
                "heartbeat_at": now,
                "finished_at": None,
                "timeout_seconds": int(timeout_seconds),
                "metadata": dict(metadata or {}),
                "error": None,
            }
            return self._save(value)

    def heartbeat(self, job_id: str, operation_key: str, lease_id: str) -> bool:
        with self._lock:
            value = self._load(job_id, operation_key)
            if not value or value.get("lease_id") != lease_id or value.get("status") != "RUNNING":
                return False
            value["heartbeat_at"] = _utc_now().isoformat()
            self._save(value)
            return True

    def finish(
        self,
        job_id: str,
        operation_key: str,
        lease_id: str,
        *,
        status: str,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            value = self._load(job_id, operation_key)
            if not value or value.get("lease_id") != lease_id:
                return None
            now = _utc_now().isoformat()
            value["status"] = status
            value["heartbeat_at"] = now
            value["finished_at"] = now
            value["error"] = error
            if metadata:
                value["metadata"] = {**dict(value.get("metadata") or {}), **metadata}
            return self._save(value)

    def is_stale(self, lease: Optional[dict[str, Any]], *, heartbeat_grace_seconds: int) -> bool:
        if not lease or lease.get("status") != "RUNNING":
            return False
        heartbeat = _parse_dt(lease.get("heartbeat_at")) or _parse_dt(lease.get("started_at"))
        if heartbeat is None:
            return True
        return (_utc_now() - heartbeat).total_seconds() >= heartbeat_grace_seconds


autopilot_operation_store = AutopilotOperationStore(get_settings().content_dna_checkpoint_dir)
