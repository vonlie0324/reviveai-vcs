from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.models.autonomous_activity import AutonomousActivityEvent
from app.services.firestore_job_repository import FirestoreJobRepository

logger = logging.getLogger(__name__)

# Never allow capability URLs/tokens/secrets into the creator-readable audit trail.
_SENSITIVE_DETAIL_KEYS = {
    "access_token", "refresh_token", "authorization", "token", "secret",
    "upload_session_uri", "oauth_state", "cookie", "password",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): ("[REDACTED]" if str(k).lower() in _SENSITIVE_DETAIL_KEYS else _sanitize(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, tuple):
        return [_sanitize(v) for v in value]
    return value


class AutonomousActivityStore:
    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "autonomous_activity"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cloud = FirestoreJobRepository("autonomous_activity_events")

    def _tenant_dir(self) -> Path:
        path = tenant_scoped_root(self._root)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def append(
        self,
        *,
        phase: str,
        action: str,
        message: str,
        status: str = "INFO",
        details: Optional[dict[str, Any]] = None,
        recommendation_id: Optional[str] = None,
        production_job_id: Optional[str] = None,
        media_job_id: Optional[str] = None,
        assembly_job_id: Optional[str] = None,
        audio_job_id: Optional[str] = None,
        package_id: Optional[str] = None,
        publishing_draft_id: Optional[str] = None,
        publication_id: Optional[str] = None,
    ) -> AutonomousActivityEvent:
        event = AutonomousActivityEvent(
            event_id=f"activity_{uuid4().hex}",
            occurred_at=datetime.now(timezone.utc),
            phase=str(phase or "AUTOPILOT"),
            action=str(action or "UPDATE"),
            status=str(status or "INFO").upper(),
            message=str(message or ""),
            details=_sanitize(details or {}),
            recommendation_id=recommendation_id,
            production_job_id=production_job_id,
            media_job_id=media_job_id,
            assembly_job_id=assembly_job_id,
            audio_job_id=audio_job_id,
            package_id=package_id,
            publishing_draft_id=publishing_draft_id,
            publication_id=publication_id,
        )
        payload = event.model_dump(mode="json")
        cloud_error: Exception | None = None
        try:
            self._cloud.save(event.event_id, payload)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist autonomous activity event to Firestore")
        with self._lock:
            path = self._tenant_dir() / f"{event.event_id}.json"
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable activity-log persistence failed") from cloud_error
        return event

    @staticmethod
    def _validate(payload: dict | None) -> Optional[AutonomousActivityEvent]:
        if not payload:
            return None
        try:
            return AutonomousActivityEvent.model_validate(payload)
        except Exception:
            return None

    def list(self, *, limit: int = 200) -> list[AutonomousActivityEvent]:
        items: dict[str, AutonomousActivityEvent] = {}
        try:
            for doc_id, payload in self._cloud.stream():
                event = self._validate(payload)
                if event:
                    items[doc_id] = event
        except Exception:
            logger.exception("Could not list autonomous activity from Firestore; using local mirror")
        with self._lock:
            for path in self._tenant_dir().glob("activity_*.json"):
                try:
                    event = AutonomousActivityEvent.model_validate_json(path.read_text(encoding="utf-8"))
                    items[event.event_id] = event
                except Exception:
                    continue
        ordered = sorted(items.values(), key=lambda x: x.occurred_at, reverse=True)
        return ordered[: max(1, min(int(limit), 1000))]


autonomous_activity_store = AutonomousActivityStore(get_settings().content_dna_checkpoint_dir)
