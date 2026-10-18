from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Optional

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.models.trend_direction import TrendDirection, TrendDirectionSet
from app.services.firestore_job_repository import FirestoreJobRepository


logger = logging.getLogger(__name__)


class TrendDirectionStore:
    """Tenant-scoped direction snapshots with Firestore durability.

    A recovery job is the stable intelligence lineage for a channel workspace.
    Firestore lets localhost and Cloud Run restore the same saved direction set
    without repeating YouTube discovery and Gemini analysis.
    """

    def __init__(self, checkpoint_root: str = ".reviveai_checkpoints") -> None:
        self._root = Path(checkpoint_root) / "trend_directions"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cloud = FirestoreJobRepository("trend_directions")

    @staticmethod
    def _safe_id(recovery_job_id: str) -> str:
        return "".join(ch for ch in recovery_job_id if ch.isalnum() or ch in {"-", "_"})

    def _path(self, recovery_job_id: str) -> Path:
        return tenant_scoped_root(self._root) / f"{self._safe_id(recovery_job_id)}.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[TrendDirectionSet]:
        if not payload:
            return None
        try:
            return TrendDirectionSet.model_validate(payload)
        except Exception:
            return None

    def _load_cloud(self, recovery_job_id: str) -> Optional[TrendDirectionSet]:
        try:
            return self._validate_payload(self._cloud.load(self._safe_id(recovery_job_id)))
        except Exception:
            logger.exception("Could not read trend directions %s from Firestore", recovery_job_id)
            return None

    def _load_local(self, recovery_job_id: str) -> Optional[TrendDirectionSet]:
        path = self._path(recovery_job_id)
        if not path.exists():
            return None
        try:
            return TrendDirectionSet.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _persist_local(self, snapshot: TrendDirectionSet) -> None:
        path = self._path(snapshot.recovery_job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, snapshot: TrendDirectionSet) -> None:
        self._cloud.save(
            self._safe_id(snapshot.recovery_job_id),
            snapshot.model_dump(mode="json"),
        )

    def _backfill_cloud(self, snapshot: TrendDirectionSet) -> None:
        try:
            self._persist_cloud(snapshot)
        except Exception:
            logger.exception("Could not backfill local trend directions %s to Firestore", snapshot.recovery_job_id)

    def get(self, recovery_job_id: str) -> Optional[TrendDirectionSet]:
        cloud = self._load_cloud(recovery_job_id)
        if cloud is not None:
            return cloud.model_copy(deep=True)

        local = self._load_local(recovery_job_id)
        if local is not None:
            self._backfill_cloud(local)
            return local.model_copy(deep=True)
        return None

    def save(self, snapshot: TrendDirectionSet) -> TrendDirectionSet:
        with self._lock:
            cloud_error: Exception | None = None
            try:
                self._persist_cloud(snapshot)
            except Exception as exc:
                cloud_error = exc
                logger.exception("Could not persist trend directions %s to Firestore", snapshot.recovery_job_id)

            self._persist_local(snapshot)

            if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
                raise RuntimeError("Durable Firestore persistence failed for trend directions") from cloud_error

        return snapshot.model_copy(deep=True)

    def prepend_custom(self, recovery_job_id: str, direction: TrendDirection) -> Optional[TrendDirectionSet]:
        current = self.get(recovery_job_id)
        if current is None:
            return None
        current.directions = [direction, *[item for item in current.directions if item.lane != "CUSTOM"]]
        return self.save(current)


_settings = get_settings()
trend_direction_store = TrendDirectionStore(_settings.content_dna_checkpoint_dir)
