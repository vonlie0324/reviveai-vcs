from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class CloudTaskDispatchError(RuntimeError):
    pass


class CloudTaskDispatcher:
    """Small Cloud Tasks REST client without adding another runtime dependency.

    Firestore remains the source of truth. Cloud Tasks is the wake-up transport for
    request-driven Cloud Run work such as Autopilot, YouTube autonomy, recovery, and
    channel analysis.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._credentials = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.autopilot_event_driven_enabled)

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.settings.effective_autopilot_tasks_project_id
            and self.settings.autopilot_tasks_location
            and self.settings.autopilot_tasks_queue
            and self.settings.autopilot_tasks_target_base_url
            and self.settings.autopilot_tasks_service_account_email
        )

    def _access_token(self) -> str:
        if self._credentials is None:
            credentials, _ = google_auth_default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            self._credentials = credentials
        if (
            not self._credentials.valid
            or self._credentials.expired
            or not self._credentials.token
        ):
            self._credentials.refresh(GoogleAuthRequest())
        return str(self._credentials.token)

    def _queue_url(self) -> str:
        s = self.settings
        return (
            "https://cloudtasks.googleapis.com/v2/"
            f"projects/{s.effective_autopilot_tasks_project_id}/"
            f"locations/{s.autopilot_tasks_location}/"
            f"queues/{s.autopilot_tasks_queue}/tasks"
        )

    def _target_url(self, kind: str) -> str:
        base = self.settings.autopilot_tasks_target_base_url.rstrip("/")
        if kind == "autopilot":
            return f"{base}/internal/tasks/autopilot"
        if kind == "youtube":
            return f"{base}/internal/tasks/youtube"
        if kind == "analysis":
            return f"{base}/internal/tasks/analysis"
        if kind == "recovery":
            return f"{base}/internal/tasks/recovery-sweep"
        raise ValueError(f"Unsupported task kind: {kind}")

    def schedule(
        self,
        *,
        kind: str,
        namespace: str = "",
        delay_seconds: float = 0.0,
        schedule_at: datetime | None = None,
        reason: str = "",
        extra_payload: dict[str, object] | None = None,
    ) -> bool:
        if not self.configured:
            if self.enabled:
                logger.warning(
                    "Event-driven autonomy is enabled but Cloud Tasks is not fully configured"
                )
            return False

        run_at = schedule_at or (
            datetime.now(timezone.utc)
            + timedelta(seconds=max(0.0, float(delay_seconds)))
        )
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=timezone.utc)
        run_at = run_at.astimezone(timezone.utc)

        payload_data: dict[str, object] = {
            "namespace": namespace,
            "reason": reason,
        }
        if extra_payload:
            payload_data.update(extra_payload)

        payload = json.dumps(payload_data, separators=(",", ":")).encode("utf-8")
        audience = (
            self.settings.autopilot_tasks_oidc_audience
            or self.settings.autopilot_tasks_target_base_url
        ).rstrip("/")

        body = {
            "task": {
                "httpRequest": {
                    "httpMethod": "POST",
                    "url": self._target_url(kind),
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(payload).decode("ascii"),
                    "oidcToken": {
                        "serviceAccountEmail": self.settings.autopilot_tasks_service_account_email,
                        "audience": audience,
                    },
                },
                "scheduleTime": run_at.isoformat().replace("+00:00", "Z"),
                "dispatchDeadline": (
                    f"{int(self.settings.autopilot_tasks_dispatch_deadline_seconds)}s"
                ),
            }
        }

        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    self._queue_url(),
                    headers={
                        "Authorization": f"Bearer {self._access_token()}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
            if response.status_code >= 400:
                raise CloudTaskDispatchError(
                    f"Cloud Tasks create failed ({response.status_code}): "
                    f"{response.text[:500]}"
                )
            return True
        except Exception:
            # Existing Autopilot/YouTube queue state can be repaired by the recovery
            # sweep. Direct channel-analysis creation handles False explicitly so a
            # newly-created analysis job cannot remain silently QUEUED forever.
            logger.exception(
                "Could not schedule %s task for namespace %s",
                kind,
                namespace,
            )
            return False

    def schedule_autopilot(
        self,
        namespace: str,
        *,
        delay_seconds: float = 0.0,
        schedule_at: datetime | None = None,
        reason: str = "",
    ) -> bool:
        return self.schedule(
            kind="autopilot",
            namespace=namespace,
            delay_seconds=delay_seconds,
            schedule_at=schedule_at,
            reason=reason,
        )

    def schedule_youtube(
        self,
        namespace: str,
        *,
        delay_seconds: float = 0.0,
        schedule_at: datetime | None = None,
        reason: str = "",
    ) -> bool:
        return self.schedule(
            kind="youtube",
            namespace=namespace,
            delay_seconds=delay_seconds,
            schedule_at=schedule_at,
            reason=reason,
        )

    def schedule_analysis(
        self,
        namespace: str,
        job_id: str,
        *,
        delay_seconds: float = 0.0,
        schedule_at: datetime | None = None,
        reason: str = "",
    ) -> bool:
        return self.schedule(
            kind="analysis",
            namespace=namespace,
            delay_seconds=delay_seconds,
            schedule_at=schedule_at,
            reason=reason,
            extra_payload={"job_id": job_id},
        )

    def verify_oidc(self, authorization: str | None) -> dict:
        if not self.configured:
            raise CloudTaskDispatchError("Cloud Tasks is not configured.")

        raw = str(authorization or "").strip()
        if not raw.lower().startswith("bearer "):
            raise CloudTaskDispatchError("Missing Cloud Tasks OIDC bearer token.")

        token = raw.split(" ", 1)[1].strip()
        audience = (
            self.settings.autopilot_tasks_oidc_audience
            or self.settings.autopilot_tasks_target_base_url
        ).rstrip("/")

        try:
            claims = id_token.verify_oauth2_token(
                token,
                GoogleAuthRequest(),
                audience=audience,
            )
        except Exception as exc:
            raise CloudTaskDispatchError("Invalid Cloud Tasks OIDC token.") from exc

        email = str(claims.get("email") or "").lower()
        expected = self.settings.autopilot_tasks_service_account_email.strip().lower()
        if (
            not expected
            or email != expected
            or claims.get("email_verified") is False
        ):
            raise CloudTaskDispatchError(
                "Cloud Tasks OIDC identity is not authorized."
            )
        return claims


cloud_task_dispatcher = CloudTaskDispatcher()
