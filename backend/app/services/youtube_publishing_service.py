from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import current_tenant_id, tenant_context, tenant_scoped_root
from app.models.youtube_publishing import (
    YouTubeConnection,
    YouTubePerformanceSnapshot,
    YouTubePublication,
    YouTubePublishRequest,
    YouTubePublishStatus,
)
from app.services.autonomous_activity_service import autonomous_activity_store
from app.services.delivery_package_service import delivery_package_store
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.publishing_assistant_service import publishing_draft_store
from app.services.revival_learning_service import PerformanceObservation, revival_learning_store
from app.services.youtube_performance_service import (
    ANALYTICS_FIELDS, analytics_dates, decode_analytics, decode_statistics,
    release_anchor, resolve_release_time, select_primary_learning_snapshot,
)
from app.services.youtube_autonomy_queue import youtube_autonomy_queue
from app.services.youtube_publication_claim_service import youtube_publication_claim_service
from app.services.youtube_upload_recovery_policy import parse_committed_bytes

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",  # videos.update: transfer scheduled releases
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
CHECKPOINTS = [("1H", 1), ("6H", 6), ("24H", 24), ("72H", 72), ("7D", 168), ("28D", 672)]
RETRIABLE_HTTP = {500, 502, 503, 504}


def now() -> datetime:
    return datetime.now(timezone.utc)


class YouTubePublishingError(RuntimeError):
    pass


class YouTubeAuthorizationRequiredError(YouTubePublishingError):
    """The stored Google refresh token can no longer be used.

    This is deliberately separate from transient YouTube/API failures so the
    autonomous monitor can pause instead of waking Cloud Run every few minutes.
    """

    pass


class _AsyncFileByteStream(httpx.AsyncByteStream):
    """HTTPX-native async file stream for resumable YouTube uploads.

    Using an explicit AsyncByteStream avoids HTTPX treating a file body as a
    synchronous request stream when the upload runs through AsyncClient.
    """

    def __init__(self, path: Path, *, offset: int = 0, chunk_size: int = 8 * 1024 * 1024):
        self.path = path
        self.offset = max(0, int(offset))
        self.chunk_size = max(64 * 1024, int(chunk_size))

    async def __aiter__(self):
        handle = await asyncio.to_thread(self.path.open, "rb")
        try:
            if self.offset:
                await asyncio.to_thread(handle.seek, self.offset)
            while True:
                chunk = await asyncio.to_thread(handle.read, self.chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def aclose(self) -> None:
        return None


class YouTubePublishingService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = Path(settings.content_dna_checkpoint_dir) / "youtube_publishing"
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = Lock()
        self._connections = FirestoreJobRepository("youtube_connections")
        self._publications = FirestoreJobRepository("youtube_publications")
        self._snapshots = FirestoreJobRepository("youtube_performance_snapshots")

    def _root(self):
        p = tenant_scoped_root(self.root)
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _fernet(self):
        raw = self.settings.youtube_oauth_token_encryption_key.strip()
        if not raw:
            raise YouTubePublishingError("YOUTUBE_OAUTH_TOKEN_ENCRYPTION_KEY is required before connecting YouTube.")
        try:
            return Fernet(raw.encode())
        except Exception:
            return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))

    def _token_path(self):
        return self._root() / "oauth.json"

    def _state_dir(self):
        p = self.root / "oauth_states"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _state_key(self, state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    def _state_path(self, state: str):
        return self._state_dir() / f"{self._state_key(state)}.json"

    def _state_ref(self, state: str):
        return get_runtime_firestore_client().collection("reviveai_youtube_oauth_states").document(self._state_key(state))

    def _pub_dir(self):
        p = self._root() / "publications"
        p.mkdir(exist_ok=True)
        return p

    def _require_oauth(self):
        if not self.settings.youtube_oauth_client_id or not self.settings.youtube_oauth_client_secret or not self.settings.youtube_oauth_redirect_uri:
            raise YouTubePublishingError(
                "YouTube OAuth is not configured. Set YOUTUBE_OAUTH_CLIENT_ID, YOUTUBE_OAUTH_CLIENT_SECRET, and YOUTUBE_OAUTH_REDIRECT_URI."
            )

    def authorization_url(self):
        self._require_oauth()
        state = secrets.token_urlsafe(32)
        state_payload = {"tenant_id": current_tenant_id(), "created_at": now().isoformat()}
        encrypted = self._fernet().encrypt(json.dumps(state_payload).encode()).decode()
        wrapper = {"payload": encrypted, "created_at": now().isoformat()}
        self._state_path(state).write_text(json.dumps(wrapper), encoding="utf-8")
        try:
            self._state_ref(state).set(wrapper)
        except Exception:
            logger.exception("Could not persist YouTube OAuth state to Firestore; local mirror retained")
        q = {
            "client_id": self.settings.youtube_oauth_client_id,
            "redirect_uri": self.settings.youtube_oauth_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q)

    def _consume_oauth_state(self, state: str):
        if not state or len(state) > 256:
            raise YouTubePublishingError("Invalid YouTube authorization state.")
        path = self._state_path(state)
        saved = None
        try:
            snap = self._state_ref(state).get()
            if snap.exists:
                saved = snap.to_dict()
        except Exception:
            logger.exception("Could not read YouTube OAuth state from Firestore")
        if not saved and path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
        try:
            if not saved:
                raise YouTubePublishingError("YouTube authorization state expired or is invalid. Start the connection again.")
            decrypted = self._fernet().decrypt(str(saved["payload"]).encode())
            payload = json.loads(decrypted)
            created = datetime.fromisoformat(payload["created_at"])
            created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
            if now() - created > timedelta(minutes=10):
                raise YouTubePublishingError("YouTube authorization state expired. Start the connection again.")
            tenant_id = str(payload["tenant_id"]).strip()
            if not tenant_id:
                raise YouTubePublishingError("Invalid YouTube authorization state.")
            return tenant_id
        except YouTubePublishingError:
            raise
        except Exception as exc:
            raise YouTubePublishingError("YouTube authorization state expired or is invalid. Start the connection again.") from exc
        finally:
            path.unlink(missing_ok=True)
            try:
                self._state_ref(state).delete()
            except Exception:
                pass

    def _persist_connection(self, payload: dict) -> None:
        self._connections.save("connection", payload)
        self._token_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _authorization_reconnect_required(self) -> bool:
        payload = self._load_connection()
        return bool(payload and str(payload.get("authorization_state") or "CONNECTED").upper() == "RECONNECT_REQUIRED")

    def authorization_reconnect_required(self) -> bool:
        """Public read used by Autopilot scheduling to avoid pointless wake-ups."""
        return self._authorization_reconnect_required()

    @staticmethod
    def _credential_marker(payload: dict | None) -> str:
        """Opaque comparison key, never logged or persisted separately."""
        if not payload:
            return ""
        value = f"{payload.get('refresh_token') or ''}\0{payload.get('connected_at') or ''}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _mark_authorization_required(
        self, *, error_code: str | None = None,
        error_description: str | None = None,
        expected_marker: str,
    ) -> None:
        """Mark only the SAME credential that failed, using a Firestore CAS.

        A monitor holding old credentials must never invalidate a newer OAuth
        reconnect. No local-disk fallback is used for this security-critical write.
        """
        from google.cloud import firestore

        if not expected_marker:
            logger.warning("Skipping OAuth invalidation without credential identity")
            return
        document = self._connections._collection().document("connection")
        transaction = get_runtime_firestore_client().transaction()
        timestamp = now()

        @firestore.transactional
        def update(tx):
            snapshot = document.get(transaction=tx)
            if not snapshot.exists:
                return None
            wrapper = snapshot.to_dict() or {}
            payload = self._connections._decode_inline(wrapper)
            if not payload or self._credential_marker(payload) != expected_marker:
                return None
            blocked = str(payload.get("authorization_state") or "").upper() == "RECONNECT_REQUIRED"
            if blocked:
                return None
            updated = dict(payload)
            updated["authorization_state"] = "RECONNECT_REQUIRED"
            updated["authorization_failed_at"] = timestamp.isoformat()
            updated["authorization_error_code"] = (error_code or "youtube_api_unauthenticated")[:128]
            updated["authorization_error_description"] = (error_description or "Google rejected authorization.")[:500]
            encoded = self._connections._encode(updated)
            raw = encoded.encode("utf-8")
            tx.set(document, {
                "schema_version": self._connections.SCHEMA_VERSION,
                "storage_mode": self._connections.STORAGE_INLINE,
                "payload_json": encoded,
                "payload_size_bytes": len(raw),
                "payload_sha256": hashlib.sha256(raw).hexdigest(),
                "persisted_at": timestamp,
            })
            return updated

        changed = update(transaction)
        if changed:
            autonomous_activity_store.append(
                phase="YOUTUBE", action="AUTH_RECONNECT_REQUIRED", status="WARNING",
                message="YouTube authorization requires attention; autonomous publishing is paused.",
                details={
                    "channel_id": changed.get("channel_id"),
                    "channel_title": changed.get("channel_title"),
                    "error_code": changed.get("authorization_error_code"),
                },
            )

    def _resume_after_reconnect(self) -> None:
        """Wake the paused event-driven queues immediately after OAuth succeeds."""
        try:
            youtube_autonomy_queue.sync(active=True, next_run_seconds=0.0)
        except Exception:
            logger.exception("Could not resume YouTube autonomy after reconnect")
        try:
            from app.core.tenant import tenant_namespace
            from app.services.autopilot_state_service import autopilot_state_store
            from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue

            record = autopilot_state_store.get()
            if record is not None:
                autopilot_supervisor_queue.sync(
                    namespace=tenant_namespace(),
                    status=record.session.status,
                    revision=record.revision,
                    execution_owner=record.session.executionOwner,
                    has_current_publication=bool(record.session.currentPublicationId),
                )
        except Exception:
            logger.exception("Could not resume Autopilot after YouTube reconnect")

    def _load_connection(self) -> dict | None:
        try:
            payload = self._connections.load("connection")
            if payload:
                return payload
        except Exception:
            logger.exception("Could not read YouTube connection from Firestore")
        if self._token_path().exists():
            try:
                payload = json.loads(self._token_path().read_text(encoding="utf-8"))
                self._connections.save("connection", payload)
                return payload
            except Exception:
                pass
        return None

    async def exchange_code(self, code, state):
        self._require_oauth()
        tenant_id = self._consume_oauth_state(state)
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": self.settings.youtube_oauth_client_id,
                    "client_secret": self.settings.youtube_oauth_client_secret,
                    "redirect_uri": self.settings.youtube_oauth_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if r.status_code >= 400:
                error_code = ""
                error_description = ""
                try:
                    body = r.json()
                    error_code = str(body.get("error") or "")
                    error_description = str(body.get("error_description") or "")
                except Exception:
                    body = None

                logger.error(
                    "YouTube OAuth authorization-code exchange failed: "
                    "status=%s error=%s description=%s redirect_uri=%s client_id=%s",
                    r.status_code,
                    error_code or "unknown",
                    error_description or "not provided",
                    self.settings.youtube_oauth_redirect_uri,
                    self.settings.youtube_oauth_client_id,
                )

                if error_code == "invalid_client":
                    raise YouTubePublishingError(
                        "Google rejected the configured YouTube OAuth client credentials. "
                        "Verify YOUTUBE_OAUTH_CLIENT_ID and YOUTUBE_OAUTH_CLIENT_SECRET, then restart the backend."
                    )

                if error_code == "invalid_grant":
                    raise YouTubePublishingError(
                        "Google rejected the OAuth authorization grant. "
                        "Verify that the redirect URI exactly matches the OAuth client configuration and start the connection again."
                    )

                if error_code == "redirect_uri_mismatch":
                    raise YouTubePublishingError(
                        "Google rejected the OAuth redirect URI. "
                        f"Expected redirect URI: {self.settings.youtube_oauth_redirect_uri}"
                    )

                if error_code in {"unauthorized_client", "deleted_client"}:
                    raise YouTubePublishingError(
                        "The configured Google OAuth client is not authorized for this grant. "
                        "Verify the OAuth client in Google Cloud, then reconnect YouTube."
                    )

                raise YouTubePublishingError(
                    f"Google rejected the YouTube authorization request ({error_code or r.status_code})."
                )

            token = r.json()
            refresh = token.get("refresh_token")
            if not refresh:
                logger.error(
                    "YouTube OAuth token response did not include a refresh token: "
                    "token_type=%s scope=%s expires_in=%s",
                    token.get("token_type"),
                    token.get("scope"),
                    token.get("expires_in"),
                )
                raise YouTubePublishingError(
                    "Google did not return a refresh token. Reconnect YouTube and grant offline access."
                )
            access = token["access_token"]
            logger.info(
                "YouTube OAuth token exchange accepted: type_bearer=%s expires_in=%s granted_scope_count=%s required_scopes_present=%s",
                str(token.get("token_type") or "").lower() == "bearer",
                token.get("expires_in"),
                len(str(token.get("scope") or "").split()),
                set(SCOPES).issubset(set(str(token.get("scope") or "").split())),
            )
            channel = await self._channel(access, client)
        with tenant_context(tenant_id):
            # Reconnect must never silently move an existing publishing tenant to
            # a different YouTube channel. Do not persist tokens on mismatch.
            existing = self._load_connection()
            previous_channel_id = str((existing or {}).get("channel_id") or "").strip()
            resolved_channel_id = str(channel.get("id") or "").strip()
            if previous_channel_id and previous_channel_id != resolved_channel_id:
                logger.warning(
                    "YouTube OAuth channel mismatch; tenant connection not changed: prior_channel_id=%s resolved_channel_id=%s",
                    previous_channel_id, resolved_channel_id,
                )
                raise YouTubePublishingError(
                    "Google authorized a different YouTube channel from the one already connected to ReviveAI. "
                    "Select the existing channel and reconnect; no credentials were changed."
                )
            payload = {
                "refresh_token": self._fernet().encrypt(refresh.encode()).decode(),
                "channel_id": channel["id"],
                "channel_title": channel["snippet"]["title"],
                "connected_at": now().isoformat(),
                "scopes": SCOPES,
                "authorization_state": "CONNECTED",
                "authorization_error_code": None,
                "authorization_error_description": None,
                "authorization_failed_at": None,
            }
            self._persist_connection(payload)
            self._resume_after_reconnect()
            autonomous_activity_store.append(
                phase="YOUTUBE",
                action="CHANNEL_CONNECTED",
                status="SUCCESS",
                message=f"Connected YouTube channel {payload['channel_title']} for autonomous publishing.",
                details={"channel_id": payload["channel_id"]},
            )
            return self.connection()

    def connection(self):
        d = self._load_connection()
        if not d:
            return YouTubeConnection()
        try:
            return YouTubeConnection(
                connected=str(d.get("authorization_state") or "CONNECTED").upper() != "RECONNECT_REQUIRED",
                channel_id=d.get("channel_id"),
                channel_title=d.get("channel_title"),
                connected_at=d.get("connected_at"),
                scopes=d.get("scopes", []),
            )
        except Exception:
            return YouTubeConnection()

    def disconnect(self):
        self._token_path().unlink(missing_ok=True)
        try:
            get_runtime_firestore_client().collection("reviveai_tenants").document(__import__('app.core.tenant', fromlist=['tenant_namespace']).tenant_namespace()).collection("youtube_connections").document("connection").delete()
        except Exception:
            logger.exception("Could not remove YouTube connection from Firestore")
        autonomous_activity_store.append(
            phase="YOUTUBE", action="CHANNEL_DISCONNECTED", status="WARNING", message="YouTube channel disconnected; autonomous publishing is paused until reconnected."
        )
        return YouTubeConnection()

    async def _access_token(self, *, return_marker: bool = False):
        self._require_oauth()
        d = self._load_connection()
        try:
            if not d:
                raise KeyError("connection")
            refresh = self._fernet().decrypt(str(d["refresh_token"]).encode()).decode()
        except (KeyError, InvalidToken) as exc:
            raise YouTubePublishingError("Connect the YouTube channel before publishing or reading analytics.") from exc
        marker = self._credential_marker(d)
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            r = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": self.settings.youtube_oauth_client_id,
                    "client_secret": self.settings.youtube_oauth_client_secret,
                    "refresh_token": refresh,
                    "grant_type": "refresh_token",
                },
            )
        if r.status_code >= 400:
            error_code = ""
            error_description = ""
            try:
                body = r.json()
                error_code = str(body.get("error") or "")
                error_description = str(body.get("error_description") or "")
            except Exception:
                body = None
            terminal_oauth_errors = {
                "invalid_grant",
                "invalid_client",
                "deleted_client",
                "unauthorized_client",
            }
            if error_code in terminal_oauth_errors:
                if error_code == "invalid_grant":
                    fallback_description = "The Google refresh token expired or was revoked."
                    user_message = "Unable to refresh YouTube authorization. Reconnect the channel."
                elif error_code == "invalid_client":
                    fallback_description = "Google rejected the configured OAuth client ID or client secret."
                    user_message = (
                        "Unable to refresh YouTube authorization because Google rejected the OAuth client "
                        "credentials. Verify YOUTUBE_OAUTH_CLIENT_ID/YOUTUBE_OAUTH_CLIENT_SECRET, then reconnect "
                        "the channel."
                    )
                elif error_code == "deleted_client":
                    fallback_description = "The configured Google OAuth client was deleted."
                    user_message = (
                        "Unable to refresh YouTube authorization because the configured OAuth client was deleted. "
                        "Restore or replace the OAuth client, then reconnect the channel."
                    )
                else:
                    fallback_description = "The configured OAuth client is not authorized for this token grant."
                    user_message = (
                        "Unable to refresh YouTube authorization because the OAuth client is not authorized for "
                        "this grant. Correct the OAuth client configuration, then reconnect the channel."
                    )

                self._mark_authorization_required(
                    error_code=error_code,
                    error_description=error_description or fallback_description,
                    expected_marker=marker,
                )
                raise YouTubeAuthorizationRequiredError(user_message)

            raise YouTubePublishingError(
                f"Unable to refresh YouTube authorization ({error_code or r.status_code})."
            )
        access = r.json()["access_token"]
        return (access, marker) if return_marker else access

    async def _authenticated_get(self, client: httpx.AsyncClient, url: str, *, params: dict) -> httpx.Response:
        """Retry an authorization failure with a newly refreshed access token once.

        A second authentication failure is not a transient monitor problem:
        pause this tenant until OAuth is repaired, without altering publications.
        """
        for attempt in range(2):
            token, marker = await self._access_token(return_marker=True)
            response = await client.get(
                url, params=params, headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 401:
                return response
            if attempt == 0:
                logger.warning("YouTube API returned 401; refreshing authorization and retrying once")
                continue
            await self._diagnose_access_token(client, token, source="monitor")
            self._mark_authorization_required(
                error_code="youtube_api_unauthenticated",
                error_description="YouTube rejected a freshly refreshed access token. Check OAuth diagnostics.",
                expected_marker=marker,
            )
            raise YouTubeAuthorizationRequiredError(
                "YouTube authorization was rejected after token refresh. Reconnect the channel."
            )
        raise AssertionError("Unreachable YouTube authentication retry state")

    async def _diagnose_access_token(self, client: httpx.AsyncClient, token: str, *, source: str) -> None:
        """Google tokeninfo probe on failure only; never print token or raw response.

        Tokeninfo is a diagnostic endpoint, not a replacement for authorization.
        Google's endpoint requires the token in an HTTPS query parameter; do not
        enable HTTPX DEBUG request URL logging during this diagnostic.
        """
        try:
            probe = await client.get(
                "https://oauth2.googleapis.com/tokeninfo", params={"access_token": token},
            )
            payload = probe.json() if probe.status_code < 500 else {}
            if not isinstance(payload, dict):
                payload = {}
            granted = set(str(payload.get("scope") or "").split())
            audience = str(payload.get("aud") or payload.get("issued_to") or "")
            logger.warning(
                "YouTube OAuth diagnostic: source=%s tokeninfo_http=%s google_error=%s audience_matches=%s scopes_match=%s expires_in=%s",
                source, probe.status_code,
                str(payload.get("error") or "none")[:48],
                audience == self.settings.youtube_oauth_client_id,
                set(SCOPES).issubset(granted),
                str(payload.get("expires_in") or "unknown")[:20],
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("YouTube OAuth diagnostic unavailable: source=%s category=%s", source, type(exc).__name__)

    async def _channel(self, token, client=None):
        """Resolve the OAuth-selected channel without hiding upstream API failures.

        HTTP 401/403 and malformed responses must not be described as 'no channel'.
        Never include OAuth tokens or complete Google response bodies in logs.
        """
        own = client is None
        client = client or httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds)
        try:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            if own:
                await client.aclose()

        try:
            body = response.json()
        except (ValueError, TypeError):
            body = None
        if response.status_code >= 400:
            google_error = body.get("error") if isinstance(body, dict) else None
            if not isinstance(google_error, dict):
                google_error = {}
            details = google_error.get("errors") or []
            first_detail = details[0] if isinstance(details, list) and details and isinstance(details[0], dict) else {}
            reason = str(first_detail.get("reason") or google_error.get("status") or "unknown")[:100]
            logger.warning(
                "YouTube OAuth channel discovery failed: http_status=%s google_reason=%s",
                response.status_code, reason,
            )
            if response.status_code == 401:
                await self._diagnose_access_token(client, token, source="oauth_callback")
                raise YouTubePublishingError(
                    "Google rejected the newly authorized YouTube access token (HTTP 401). "
                    "Confirm the selected YouTube identity and OAuth permissions, then try reconnecting."
                )
            if response.status_code == 403:
                raise YouTubePublishingError(
                    f"Google denied YouTube channel discovery (HTTP 403; reason: {reason}). "
                    "Check that the YouTube Data API v3 is enabled and the selected channel has access."
                )
            raise YouTubePublishingError(
                f"YouTube channel discovery failed (HTTP {response.status_code}; reason: {reason})."
            )
        if not isinstance(body, dict) or not isinstance(body.get("items"), list):
            logger.warning("YouTube OAuth channel discovery returned an invalid response structure")
            raise YouTubePublishingError("Google returned an invalid YouTube channel response. Please try reconnecting.")
        items = body["items"]
        if not items:
            logger.warning("YouTube OAuth channel discovery returned zero channels (HTTP 200)")
            raise YouTubePublishingError(
                "Google returned no YouTube channel for the selected identity (HTTP 200). "
                "Select the intended YouTube channel in Google's account chooser and try again."
            )
        first = items[0]
        if not isinstance(first, dict) or not first.get("id") or not isinstance(first.get("snippet"), dict) or not first["snippet"].get("title"):
            logger.warning("YouTube OAuth channel discovery returned incomplete channel identity")
            raise YouTubePublishingError("Google returned incomplete channel information. Please try reconnecting.")
        return first

    async def _stream_file(self, path: Path, *, offset: int = 0, chunk_size: int = 8 * 1024 * 1024):
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            if offset:
                await asyncio.to_thread(handle.seek, offset)
            while True:
                chunk = await asyncio.to_thread(handle.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    def _persist_pub_local(self, pub: YouTubePublication) -> None:
        (self._pub_dir() / f"{pub.publication_id}.json").write_text(
            json.dumps(pub.model_dump(mode="json"), indent=2, default=str), encoding="utf-8"
        )

    def _save_pub(self, pub: YouTubePublication):
        pub.updated_at = now()
        payload = pub.model_dump(mode="json")
        self._publications.save(pub.publication_id, payload)
        self._persist_pub_local(pub)
        youtube_autonomy_queue.sync(active=True, next_run_seconds=0)
        return pub

    @staticmethod
    def _validate_pub(payload: dict | None) -> YouTubePublication | None:
        if not payload:
            return None
        try:
            return YouTubePublication.model_validate(payload)
        except Exception:
            return None

    def get(self, pid: str):
        try:
            loaded = self._validate_pub(self._publications.load(pid))
            if loaded:
                return loaded
        except Exception:
            logger.exception("Could not read YouTube publication %s from Firestore", pid)
        path = self._pub_dir() / f"{pid}.json"
        if not path.exists():
            raise YouTubePublishingError("YouTube publication not found.")
        pub = YouTubePublication.model_validate_json(path.read_text(encoding="utf-8"))
        self._publications.save(pub.publication_id, pub.model_dump(mode="json"))
        return pub

    def list(self, *, include_superseded: bool = False):
        items: dict[str, YouTubePublication] = {}
        try:
            for doc_id, payload in self._publications.stream():
                pub = self._validate_pub(payload)
                if pub:
                    items[doc_id] = pub
        except Exception:
            logger.exception("Could not list YouTube publications from Firestore; using local mirror")
        for p in self._pub_dir().glob("*.json"):
            try:
                pub = YouTubePublication.model_validate_json(p.read_text(encoding="utf-8"))
                # Firestore is authoritative. Local JSON is only a recovery mirror and
                # must not overwrite a newer cloud record (for example v3.4
                # supersession/idempotency metadata).
                if pub.publication_id not in items:
                    items[pub.publication_id] = pub
            except Exception:
                pass
        for publication in items.values():
            if not publication.video_title:
                try:
                    publication.video_title = publishing_draft_store.get(publication.publishing_draft_id).content.youtube.title
                except Exception:
                    pass
        values = list(items.values())
        if not include_superseded:
            values = [item for item in values if not item.superseded_by_publication_id]
        return sorted(values, key=lambda x: x.created_at, reverse=True)

    def latest_for_recommendation(self, recommendation_id: str) -> YouTubePublication | None:
        matches = [p for p in self.list() if p.recommendation_id == recommendation_id]
        return max(matches, key=lambda x: x.created_at) if matches else None

    def _validate_publish_assets(self, package_id: str, publishing_draft_id: str):
        package = delivery_package_store.get(package_id)
        draft = publishing_draft_store.get(publishing_draft_id)
        if draft.status.value != "APPROVED":
            raise YouTubePublishingError("Approve the publishing copy before publishing to YouTube.")
        if package.publishing_draft_id != draft.draft_id:
            raise YouTubePublishingError("Rebuild the delivery package with this approved publishing copy before publishing.")
        return package, draft

    async def _create_upload_session(self, pub: YouTubePublication, video_path: Path, draft) -> None:
        token = await self._access_token()
        body = {
            "snippet": {
                "title": draft.content.youtube.title[:100],
                "description": draft.content.youtube.description,
                "tags": draft.content.youtube.tags,
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": pub.privacy_status,
                "selfDeclaredMadeForKids": bool(pub.made_for_kids),
                "containsSyntheticMedia": bool(pub.contains_synthetic_media),
            },
        }
        if pub.publish_at:
            body["status"]["privacyStatus"] = "private"
            body["status"]["publishAt"] = pub.publish_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(video_path.stat().st_size),
        }
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            init = await client.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=headers,
                json=body,
            )
        if init.status_code >= 400:
            raise YouTubePublishingError(f"YouTube upload initialization failed: {init.text[:1000]}")
        location = init.headers.get("Location")
        if not location:
            raise YouTubePublishingError("YouTube did not return a resumable upload URL.")
        pub.upload_session_uri = location
        pub.upload_bytes_total = video_path.stat().st_size
        pub.upload_bytes_committed = 0
        pub.upload_started_at = pub.upload_started_at or now()
        pub.status = YouTubePublishStatus.UPLOADING
        pub.error = None
        self._save_pub(pub)
        autonomous_activity_store.append(
            phase="YOUTUBE",
            action="UPLOAD_SESSION_CREATED",
            status="INFO",
            message="Created a resumable YouTube upload session and began uploading the approved master.",
            recommendation_id=pub.recommendation_id,
            package_id=pub.package_id,
            publishing_draft_id=pub.publishing_draft_id,
            publication_id=pub.publication_id,
            details={"video_title": pub.video_title, "bytes_total": pub.upload_bytes_total, "publish_at": pub.publish_at.isoformat() if pub.publish_at else None},
        )

    @staticmethod
    def _committed_from_range(value: str | None) -> int:
        if not value:
            return 0
        match = re.search(r"(\d+)-(\d+)$", value)
        return int(match.group(2)) + 1 if match else 0

    async def _upload_from_offset(self, pub: YouTubePublication, video_path: Path, offset: int):
        token = await self._access_token()
        total = video_path.stat().st_size
        if offset >= total:
            offset = total
        remaining = total - offset
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
            "Content-Length": str(remaining),
            "Content-Range": f"bytes {offset}-{total - 1}/{total}",
        }
        async with httpx.AsyncClient(timeout=None) as client:
            return await client.put(
                str(pub.upload_session_uri),
                headers=headers,
                content=_AsyncFileByteStream(video_path, offset=offset),
            )

    async def _query_upload_status(self, pub: YouTubePublication, total: int):
        token = await self._access_token()
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            return await client.put(
                str(pub.upload_session_uri),
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": "0",
                    "Content-Range": f"bytes */{total}",
                },
                content=b"",
            )

    def _finish_upload_response(self, pub: YouTubePublication, response: httpx.Response) -> YouTubePublication:
        try:
            video_id = response.json()["id"]
        except (ValueError, KeyError, TypeError) as exc:
            raise YouTubePublishingError("YouTube accepted the upload but did not return a video id. Check YouTube Studio before retrying.") from exc
        pub.youtube_video_id = video_id
        pub.youtube_url = f"https://www.youtube.com/watch?v={video_id}"
        pub.upload_bytes_committed = pub.upload_bytes_total
        pub.upload_completed_at = now()
        pub.status = YouTubePublishStatus.SCHEDULED if pub.publish_at else (
            YouTubePublishStatus.PUBLISHED if pub.privacy_status == "public" else YouTubePublishStatus.SCHEDULED
        )
        pub.published_at = None if pub.publish_at else now()
        pub.error = None
        self._save_pub(pub)
        autonomous_activity_store.append(
            phase="YOUTUBE",
            action="UPLOAD_COMPLETED",
            status="SUCCESS",
            message=(
                f"Uploaded the approved master to YouTube. Public release is scheduled for {pub.publish_at.isoformat()} UTC."
                if pub.publish_at else "Uploaded the approved master to YouTube."
            ),
            recommendation_id=pub.recommendation_id,
            package_id=pub.package_id,
            publishing_draft_id=pub.publishing_draft_id,
            publication_id=pub.publication_id,
            details={"video_title": pub.video_title, "youtube_video_id": video_id, "publish_at": pub.publish_at.isoformat() if pub.publish_at else None},
        )
        return pub

    async def _upload_publication_unlocked(self, pub: YouTubePublication):
        if pub.youtube_video_id:
            return pub
        package, draft = self._validate_publish_assets(pub.package_id, pub.publishing_draft_id)
        video_path, _, _ = delivery_package_store.asset_path(package.package_id, "master_video")
        total = video_path.stat().st_size
        try:
            if not pub.upload_session_uri:
                await self._create_upload_session(pub, video_path, draft)
            else:
                status = await self._query_upload_status(pub, total)
                pub.last_reconciled_at = now()
                if status.status_code in {200, 201}:
                    return self._finish_upload_response(pub, status)
                if status.status_code == 308:
                    try:
                        progress = parse_committed_bytes(status.headers.get("Range"), total)
                    except ValueError as exc:
                        pub.status = YouTubePublishStatus.FAILED
                        pub.error = f"YouTube upload reconciliation returned an invalid range: {exc}. Automatic upload is blocked."
                        return self._save_pub(pub)
                    pub.upload_bytes_committed = progress.committed
                    if progress.complete_without_video_id:
                        pub.status = YouTubePublishStatus.FAILED
                        pub.error = (
                            "YouTube reports the entire file committed but has not confirmed a video ID. "
                            "Automatic re-upload is blocked; reconcile the existing upload in YouTube Studio."
                        )
                        return self._save_pub(pub)
                    self._save_pub(pub)
                elif status.status_code == 404:
                    pub.status = YouTubePublishStatus.FAILED
                    pub.error = "The YouTube resumable upload session expired before ReviveAI could prove whether the remote upload completed. Automatic re-upload is blocked to prevent a duplicate video."
                    self._save_pub(pub)
                    autonomous_activity_store.append(
                        phase="YOUTUBE", action="UPLOAD_SESSION_EXPIRED", status="ERROR", message=pub.error,
                        recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                        details={"video_title": pub.video_title},
                    )
                    return pub
                elif status.status_code >= 400:
                    raise YouTubePublishingError(f"Unable to reconcile YouTube upload: {status.text[:500]}")

            offset = max(0, int(pub.upload_bytes_committed or 0))
            response = await self._upload_from_offset(pub, video_path, offset)
            if response.status_code in {200, 201}:
                return self._finish_upload_response(pub, response)
            if response.status_code == 308:
                try:
                    progress = parse_committed_bytes(response.headers.get("Range"), total)
                except ValueError as exc:
                    pub.status = YouTubePublishStatus.FAILED
                    pub.error = f"YouTube returned an invalid upload range: {exc}. Automatic upload is blocked."
                    return self._save_pub(pub)
                pub.upload_bytes_committed = progress.committed
                if progress.complete_without_video_id:
                    pub.status = YouTubePublishStatus.UPLOADING
                    pub.error = "All upload bytes acknowledged; awaiting YouTube video ID reconciliation."
                else:
                    pub.status = YouTubePublishStatus.UPLOADING
                    pub.error = None
                return self._save_pub(pub)
            if response.status_code in RETRIABLE_HTTP:
                pub.status = YouTubePublishStatus.UPLOADING
                pub.retry_count += 1
                pub.error = f"Temporary YouTube upload error HTTP {response.status_code}; ReviveAI will reconcile and resume automatically."
                self._save_pub(pub)
                autonomous_activity_store.append(
                    phase="YOUTUBE", action="UPLOAD_RETRY_SCHEDULED", status="WARNING", message=pub.error,
                    recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                    details={"video_title": pub.video_title, "retry_count": pub.retry_count},
                )
                return pub
            pub.status = YouTubePublishStatus.FAILED
            pub.error = f"YouTube video upload failed: {response.text[:1000]}"
            self._save_pub(pub)
            autonomous_activity_store.append(
                phase="YOUTUBE", action="UPLOAD_FAILED", status="ERROR", message=pub.error,
                recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                details={"video_title": pub.video_title},
            )
            return pub
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            pub.status = YouTubePublishStatus.UPLOADING
            pub.retry_count += 1
            pub.error = f"Temporary YouTube transport interruption; ReviveAI will resume from the persisted upload session. {type(exc).__name__}"
            self._save_pub(pub)
            autonomous_activity_store.append(
                phase="YOUTUBE", action="UPLOAD_INTERRUPTED", status="WARNING", message=pub.error,
                recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                details={"video_title": pub.video_title, "retry_count": pub.retry_count},
            )
            return pub
        except RuntimeError as exc:
            # Older HTTPX combinations can reject a body that is not explicitly
            # typed as AsyncByteStream. Preserve the resumable session and retry
            # rather than marking the publication failed or creating a duplicate.
            if "sync request with an AsyncClient" not in str(exc):
                raise
            pub.status = YouTubePublishStatus.UPLOADING
            pub.retry_count += 1
            pub.error = "YouTube upload stream compatibility interruption; ReviveAI will reconcile and resume the persisted upload session."
            self._save_pub(pub)
            autonomous_activity_store.append(
                phase="YOUTUBE", action="UPLOAD_RETRY_SCHEDULED", status="WARNING", message=pub.error,
                recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                details={"video_title": pub.video_title, "retry_count": pub.retry_count},
            )
            return pub

    async def _upload_publication(self, pub: YouTubePublication):
        # The supervisor and the YouTube autonomy worker can observe the same
        # UPLOADING publication at nearly the same time. A Firestore lease makes
        # upload/session mutation single-writer across processes and instances.
        owner = f"upload:{uuid4().hex}"
        acquired = youtube_publication_claim_service.acquire_upload_lease(
            publication_id=pub.publication_id,
            owner=owner,
            lease_seconds=int(self.settings.autopilot_publication_claim_lease_seconds),
        )
        if not acquired:
            # Another worker owns this upload right now. Return the latest durable
            # state and let the next supervisor/monitor tick reconcile it.
            try:
                return self.get(pub.publication_id)
            except Exception:
                return pub
        try:
            return await self._upload_publication_unlocked(pub)
        finally:
            try:
                youtube_publication_claim_service.release_upload_lease(
                    publication_id=pub.publication_id, owner=owner
                )
            except Exception:
                logger.exception("Could not release YouTube publication upload lease")

    async def publish(self, req: YouTubePublishRequest):
        package, draft = self._validate_publish_assets(req.package_id, req.publishing_draft_id)

        # Fast path for an already-known recommendation. This remains useful for
        # legacy publications created before v3.4 master fingerprints existed.
        existing = self.latest_for_recommendation(req.recommendation_id)
        if existing and (
            existing.youtube_video_id
            or existing.status in {YouTubePublishStatus.UPLOADING, YouTubePublishStatus.SCHEDULED, YouTubePublishStatus.PUBLISHED}
        ):
            return existing

        privacy = req.privacy_status.lower()
        if privacy not in {"private", "unlisted", "public"}:
            raise YouTubePublishingError("privacy_status must be private, unlisted, or public.")
        publish_at = req.publish_at
        if publish_at:
            if publish_at.tzinfo is None:
                publish_at = publish_at.replace(tzinfo=timezone.utc)
            if publish_at <= now() + timedelta(minutes=1):
                raise YouTubePublishingError("Scheduled publish time must be in the future.")
            privacy = "private"

        master_fingerprint = youtube_publication_claim_service.master_fingerprint(
            audio_job_id=package.audio_job_id,
            audio_version=package.audio_version,
            delivery_asset_id=package.delivery_asset_id,
        )
        claim_owner = f"claim:{uuid4().hex}"
        claim = youtube_publication_claim_service.claim_master(
            master_fingerprint=master_fingerprint,
            owner=claim_owner,
            lease_seconds=int(self.settings.autopilot_publication_claim_lease_seconds),
        )

        if not claim.acquired:
            # A concurrent supervisor/worker already owns this exact approved master.
            # Wait briefly for its durable publication record rather than creating a
            # second YouTube resumable session.
            for _ in range(20):
                try:
                    return self.get(claim.publication_id)
                except Exception:
                    await asyncio.sleep(0.25)
            raise YouTubePublishingError(
                "This approved master already has an active publication claim. ReviveAI will reconcile it on the next supervisor tick."
            )

        # A stale claim may be reclaimed after its creator dies before persisting.
        # Reuse the deterministic publication id if the record already appeared.
        try:
            recovered = self.get(claim.publication_id)
            youtube_publication_claim_service.mark_persisted(
                master_fingerprint=master_fingerprint, publication_id=recovered.publication_id
            )
            return recovered
        except Exception:
            pass

        pub = YouTubePublication(
            publication_id=claim.publication_id,
            package_id=req.package_id,
            publishing_draft_id=req.publishing_draft_id,
            recommendation_id=req.recommendation_id,
            program_id=req.program_id,
            production_job_id=req.production_job_id,
            media_job_id=req.media_job_id,
            assembly_job_id=req.assembly_job_id,
            audio_job_id=req.audio_job_id,
            video_title=draft.content.youtube.title,
            master_fingerprint=master_fingerprint,
            status=YouTubePublishStatus.UPLOADING,
            privacy_status=privacy,
            publish_at=publish_at,
            recommended_public_date=req.recommended_public_date,
            autonomous=bool(req.autonomous),
            autonomous_final_approved_at=now() if req.autonomous else None,
            schedule_reason=req.schedule_reason,
            made_for_kids=bool(req.made_for_kids),
            contains_synthetic_media=bool(req.contains_synthetic_media),
        )
        self._save_pub(pub)
        youtube_publication_claim_service.mark_persisted(
            master_fingerprint=master_fingerprint, publication_id=pub.publication_id
        )
        return await self._upload_publication(pub)

    async def retry(self, pid: str):
        pub = self.get(pid)
        if pub.youtube_video_id:
            return pub
        if pub.status not in {YouTubePublishStatus.FAILED, YouTubePublishStatus.UPLOADING}:
            raise YouTubePublishingError("Only an interrupted or failed YouTube upload can be retried.")
        # If a failed upload still has a resumable session, reconcile it. Never create
        # a second upload automatically after an ambiguous expired session.
        if pub.status == YouTubePublishStatus.FAILED and not pub.upload_session_uri:
            raise YouTubePublishingError("This failed upload has no resumable session. Start a new publication only after checking YouTube Studio for duplicates.")
        pub.status = YouTubePublishStatus.UPLOADING
        return await self._upload_publication(pub)

    async def reconcile_remote_status(self, pid: str):
        pub = self.get(pid)
        if not pub.youtube_video_id:
            if pub.status == YouTubePublishStatus.UPLOADING:
                return await self._upload_publication(pub)
            return pub
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            r = await self._authenticated_get(
                client,
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "snippet,status", "id": pub.youtube_video_id},
            )
        if r.status_code >= 400:
            raise YouTubePublishingError(f"Unable to verify YouTube visibility: {r.text[:500]}")
        items = r.json().get("items") or []
        if not items:
            raise YouTubePublishingError("YouTube could not find this uploaded video yet.")
        video = next((item for item in items if item.get("id") == pub.youtube_video_id), None)
        if video is None:
            raise YouTubePublishingError("YouTube did not return the requested video.")
        snippet = video.get("snippet") or {}
        connected = self.connection()
        if not connected.channel_id or snippet.get("channelId") != connected.channel_id:
            raise YouTubePublishingError("Video channel does not match the connected YouTube channel.")
        status = video.get("status") or {}
        privacy = str(status.get("privacyStatus") or "").lower()
        upload_status = str(status.get("uploadStatus") or "").lower()
        pub.last_reconciled_at = now()
        if upload_status in {"failed", "rejected"}:
            pub.status = YouTubePublishStatus.FAILED
            pub.error = f"YouTube reported upload status {upload_status}."
        elif privacy == "public":
            first_public = pub.public_confirmed_at is None
            pub.privacy_status = "public"

            observed_public_at = now()
            prior_anchor = release_anchor(pub)
            effective_public_at, source = resolve_release_time(pub, snippet, observed_public_at)
            pub.public_confirmed_at = pub.public_confirmed_at or observed_public_at
            pub.public_release_at = effective_public_at
            pub.public_release_time_source = source
            pub.release_clock_version = 2
            pub.published_at = effective_public_at
            pub.status = YouTubePublishStatus.PUBLISHED
            pub.error = None
            if first_public:
                autonomous_activity_store.append(
                    phase="YOUTUBE", action="VIDEO_PUBLIC", status="SUCCESS",
                    message="YouTube confirmed that the scheduled video is now public.",
                    recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                    details={"video_title": pub.video_title, "youtube_video_id": pub.youtube_video_id,
                             "published_at": pub.published_at.isoformat(), "release_time_source": source},
                )
            elif prior_anchor != effective_public_at:
                autonomous_activity_store.append(
                    phase="LEARNING", action="RELEASE_CLOCK_REPAIRED", status="INFO",
                    message="Updated the performance clock from YouTube release metadata; the first public verification time was retained.",
                    recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                    details={"video_title": pub.video_title, "published_at": effective_public_at.isoformat(),
                             "release_time_source": source},
                )
        else:
            pub.privacy_status = privacy or pub.privacy_status
            if pub.youtube_video_id:
                pub.status = YouTubePublishStatus.SCHEDULED
        return self._save_pub(pub)

    async def confirm_public(self, pid: str):
        pub = await self.reconcile_remote_status(pid)
        if pub.status != YouTubePublishStatus.PUBLISHED:
            raise YouTubePublishingError(f"This video is still {pub.privacy_status or 'not public'} on YouTube.")
        return pub

    def _save_snapshot(self, publication_id: str, snap: YouTubePerformanceSnapshot) -> None:
        key = f"{publication_id}:{snap.checkpoint}"
        self._snapshots.save(key, {"publication_id": publication_id, "snapshot": snap.model_dump(mode="json")})
        path = self._pub_dir() / f"{publication_id}.snapshots.json"
        rows = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        rows = [x for x in rows if x.get("checkpoint") != snap.checkpoint] + [snap.model_dump(mode="json")]
        tmp = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        tmp.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def snapshots(self, pid: str):
        items: dict[str, YouTubePerformanceSnapshot] = {}
        try:
            for _doc_id, payload in self._snapshots.stream():
                if payload.get("publication_id") != pid:
                    continue
                snap = YouTubePerformanceSnapshot.model_validate(payload.get("snapshot") or {})
                items[snap.checkpoint] = snap
        except Exception:
            logger.exception("Could not list YouTube performance snapshots from Firestore")
        path = self._pub_dir() / f"{pid}.snapshots.json"
        if path.exists():
            try:
                for row in json.loads(path.read_text(encoding="utf-8")):
                    snap = YouTubePerformanceSnapshot.model_validate(row)
                    items.setdefault(snap.checkpoint, snap)
            except Exception:
                pass
        return sorted(items.values(), key=lambda x: (dict(CHECKPOINTS).get(x.checkpoint, 0), x.observed_at))

    def latest_snapshot(self, pid: str) -> YouTubePerformanceSnapshot | None:
        items = self.snapshots(pid)
        return items[-1] if items else None

    @staticmethod
    def _needs_reconciliation(snap: YouTubePerformanceSnapshot) -> bool:
        return (not snap.statistics_ready or snap.analytics_status != "READY"
                or bool(snap.statistics_error) or bool(snap.analytics_error) or not snap.learning_synced)

    def _retry_delay(self, snap: YouTubePerformanceSnapshot) -> float:
        if snap.retry_count >= 8:
            return 24.0 * 3600
        return min(6.0 * 3600, 3600.0 * (2 ** min(snap.retry_count, 3)))

    def _retry_due_at(self, pub: YouTubePublication, snap: YouTubePerformanceSnapshot):
        if not self._needs_reconciliation(snap):
            return None
        # Legacy records get one repair even when their original window ended.
        # Subsequent retries use a durable deadline; explicit refresh still works.
        if snap.evidence_version < 2:
            return now()
        anchor = release_anchor(pub)
        deadline = snap.retry_deadline_at or (anchor + timedelta(days=35) if anchor else None)
        if deadline is not None and now() >= deadline:
            return None
        return snap.next_retry_at or now()

    def due_checkpoint(self, pub: YouTubePublication) -> str | None:
        anchor = release_anchor(pub)
        if not anchor:
            return None
        age = (now() - anchor).total_seconds() / 3600.0
        snapshots = self.snapshots(pub.publication_id)
        highest = max((dict(CHECKPOINTS).get(x.checkpoint, 0) for x in snapshots), default=0)
        due = [name for name, hours in CHECKPOINTS if age >= hours and hours > highest]
        if due:
            return due[-1]
        # Reconcile the most mature pending record first, then historical ones.
        for snap in reversed(snapshots):
            due_at = self._retry_due_at(pub, snap)
            if due_at is not None and due_at <= now():
                return snap.checkpoint
        return None

    def _sync_learning(self, pub: YouTubePublication) -> None:
        # Autonomous decisions compare releases at the same maturity whenever
        # possible. Prefer the configured primary checkpoint (24H by default),
        # while allowing 1H/6H evidence to guide the next production until 24H
        # exists. Later 72H/7D/28D snapshots remain durable reporting evidence
        # and no longer silently replace the primary decision cohort.
        snapshots = self.snapshots(pub.publication_id)
        snap = select_primary_learning_snapshot(
            snapshots,
            getattr(self.settings, "autopilot_primary_performance_checkpoint", "24H"),
        )
        if snap is None:
            return
        if pub.program_id:
            try:
                revival_learning_store.add_observation(
                    pub.program_id,
                    PerformanceObservation(
                        recommendation_id=pub.recommendation_id,
                        publication_id=pub.publication_id,
                        checkpoint=snap.checkpoint,
                        evidence_source="YOUTUBE_APIS",
                        statistics_status=snap.statistics_status,
                        analytics_status=snap.analytics_status,
                        observed_at=(snap.statistics_observed_at or snap.observed_at).isoformat(),
                        views=snap.views,
                        analytics_views=snap.analytics_views,
                        average_percentage_viewed=snap.average_percentage_viewed,
                        average_view_duration_seconds=snap.average_view_duration_seconds,
                        likes=snap.likes, comments=snap.comments, shares=snap.shares,
                        subscribers_gained=snap.subscribers_gained,
                        subscribers_lost=snap.subscribers_lost,
                    ),
                )
            except KeyError:
                # The supervisor will bootstrap a workspace later; keep this
                # snapshot retryable instead of silently losing learning evidence.
                return
        snap.learning_synced = True
        if not self._needs_reconciliation(snap):
            snap.next_retry_at = None
        self._save_snapshot(pub.publication_id, snap)

    def _wake_learning_supervisor(self, pub: YouTubePublication, snap: YouTubePerformanceSnapshot) -> None:
        """Replace an old confirmation-based future wake when evidence is ready."""
        if not snap.statistics_ready:
            return
        try:
            from app.core.task_execution import internal_task_context
            from app.core.tenant import tenant_namespace
            from app.services.autopilot_state_service import autopilot_state_store
            from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue

            record = autopilot_state_store.get()
            if record is None or record.session.status != "WAITING_FOR_LEARNING" or record.session.executionOwner != "BACKEND":
                return
            session = record.session
            matches = session.currentPublicationId == pub.publication_id or (
                not session.currentPublicationId and session.currentRecommendationId == pub.recommendation_id
            )
            # Use the current next-production gate instead of stale durable state.
            # Sessions created before the daily-learning migration may still contain
            # 24H here even though 6H should now wake production.
            required = str(getattr(self.settings, "autopilot_next_production_checkpoint", "6H") or "6H").upper()
            hours = dict(CHECKPOINTS).get(required)
            anchor = release_anchor(pub)
            if (not matches or hours is None or anchor is None or dict(CHECKPOINTS).get(snap.checkpoint, 0) < hours
                    or (snap.observed_at - anchor).total_seconds() < hours * 3600):
                return
            ns = tenant_namespace()
            # Queue metadata is synchronized without recursive dispatch, then
            # explicitly scheduled even when this capture runs inside a YouTube task.
            with internal_task_context():
                autopilot_supervisor_queue.sync(
                    namespace=ns, status=session.status, revision=record.revision,
                    execution_owner=session.executionOwner, has_current_publication=bool(session.currentPublicationId),
                )
            autopilot_supervisor_queue.defer(ns, 30.0, reason="verified-learning-checkpoint")
        except Exception:
            logger.exception("Could not wake Autopilot after verified YouTube statistics")

    async def refresh_analytics(self, pid, *, checkpoint: str | None = None):
        pub = self.get(pid)
        if not pub.youtube_video_id:
            raise YouTubePublishingError("This publication does not have a YouTube video id yet.")
        if pub.status == YouTubePublishStatus.PUBLISHED and (pub.release_clock_version < 2 or not pub.public_release_at):
            pub = await self.reconcile_remote_status(pid)
        if pub.status != YouTubePublishStatus.PUBLISHED or not pub.public_confirmed_at:
            raise YouTubePublishingError("Wait until YouTube confirms that the video is public before collecting performance evidence.")
        captured_at = now()
        anchor = release_anchor(pub)
        age = (captured_at - anchor).total_seconds() / 3600
        eligible = [name for name, hours in CHECKPOINTS if age >= hours]
        checkpoint = checkpoint or (eligible[-1] if eligible else "EARLY")
        if checkpoint not in {"EARLY", *dict(CHECKPOINTS)}:
            raise YouTubePublishingError("Unknown YouTube performance checkpoint.")
        if checkpoint != "EARLY" and age < dict(CHECKPOINTS)[checkpoint]:
            raise YouTubePublishingError("This YouTube performance checkpoint is not due yet.")
        previous = next((x for x in self.snapshots(pid) if x.checkpoint == checkpoint), None)
        snap = YouTubePerformanceSnapshot(
            checkpoint=checkpoint, evidence_version=2,
            observed_at=previous.observed_at if previous else captured_at,
            age_hours=round(((previous.observed_at if previous else captured_at) - anchor).total_seconds() / 3600, 1),
            public_release_at=anchor,
            statistics_status="PENDING", analytics_status="PENDING",
            statistics_source="YOUTUBE_DATA_API", analytics_source="YOUTUBE_ANALYTICS_API",
            statistics_is_late=bool(previous) or (checkpoint != "EARLY" and age > dict(CHECKPOINTS)[checkpoint] + 1),
            retry_count=(previous.retry_count + 1) if previous else 0,
            reconciled_at=captured_at if previous else None,
            analytics_last_checked_at=captured_at,
            retry_deadline_at=(previous.retry_deadline_at if previous and previous.public_release_at == anchor and previous.retry_deadline_at
                               else max(anchor + timedelta(days=35), captured_at + timedelta(days=7))),
        )
        # Analytics remains tied to the original capture's Pacific-calendar window.
        # This is daily aggregate evidence, not an exact elapsed-hour report.
        try:
            start, end = analytics_dates(anchor, snap.observed_at)
        except Exception as exc:
            raise YouTubePublishingError("YouTube Analytics needs timezone data. Install the tzdata package and restart the backend.") from exc
        snap.analytics_start_date, snap.analytics_end_date = start, end
        same_analytics_window = bool(previous and previous.analytics_start_date == start and previous.analytics_end_date == end)
        connected = self.connection()
        params = {
            "ids": f"channel=={connected.channel_id}" if connected.channel_id else "channel==MINE",
            "startDate": start, "endDate": end,
            "metrics": ",".join(ANALYTICS_FIELDS),
            "filters": f"video=={pub.youtube_video_id}",
        }
        async with httpx.AsyncClient(timeout=self.settings.youtube_request_timeout_seconds) as client:
            results = await asyncio.gather(
                self._authenticated_get(client, "https://www.googleapis.com/youtube/v3/videos",
                                        params={"part": "snippet,statistics", "id": pub.youtube_video_id}),
                self._authenticated_get(client, "https://youtubeanalytics.googleapis.com/v2/reports",
                                        params=params),
                return_exceptions=True,
            )
        for result in results:
            if isinstance(result, YouTubeAuthorizationRequiredError):
                raise result
        channel_verified = False
        for api, result in zip(("statistics", "analytics"), results):
            try:
                if isinstance(result, Exception):
                    raise ValueError(f"{api} request failed ({type(result).__name__}).")
                if result.status_code >= 400:
                    # Log status/reason, never OAuth headers or capability URLs.
                    body = result.json()
                    errors = (body.get("error") or {}).get("errors") or []
                    reason = str(errors[0].get("reason") or "request_failed") if errors else "request_failed"
                    raise ValueError(f"YouTube {api} HTTP {result.status_code}: {reason[:100]}")
                body = result.json()
                if api == "statistics":
                    values, status = decode_statistics(body, pub.youtube_video_id, connected.channel_id)
                    channel_verified = True
                    # Keep only the counters and video/channel identity, not snippet metadata.
                    snap.statistics_response = {"video_id": pub.youtube_video_id,
                                                "channel_id": connected.channel_id, "values": values,
                                                "statistics": (body["items"][0].get("statistics") or {})}
                    snap.statistics_observed_at = captured_at
                else:
                    if not channel_verified:
                        raise ValueError("Analytics withheld until the video's connected channel is verified.")
                    values, status = decode_analytics(body)
                    snap.analytics_response = {"columnHeaders": body.get("columnHeaders") or [],
                                               "rows": (body.get("rows") or [])[:1]}
                    if status in {"READY", "PARTIAL"}:
                        snap.analytics_observed_at = captured_at
                    if status != "READY" and same_analytics_window and previous.evidence_version >= 2 and previous.analytics_status == "READY":
                        raise ValueError("Analytics report is incomplete; retaining the last verified report.")
                for name, value in values.items():
                    setattr(snap, name, value)
                setattr(snap, f"{api}_status", status)
            except Exception as exc:
                setattr(snap, f"{api}_status", "ERROR")
                setattr(snap, f"{api}_error", str(exc)[:300])
                # A temporary failure must not erase an earlier verified response.
                can_retain = (channel_verified and same_analytics_window if api == "analytics" else
                              bool(previous and previous.statistics_response
                                   and previous.statistics_response.get("channel_id") == connected.channel_id
                                   and "channel does not match" not in str(exc)))
                if can_retain and previous and previous.evidence_version >= 2 and getattr(previous, f"{api}_status") == "READY":
                    if api == "statistics":
                        names = ("views", "likes", "comments", "statistics_observed_at", "statistics_response")
                    else:
                        names = tuple(field for field, _ in ANALYTICS_FIELDS.values()) + ("analytics_observed_at", "analytics_response")
                    for name in names:
                        setattr(snap, name, getattr(previous, name))
                    setattr(snap, f"{api}_status", "READY")
        # Keep retries active until delayed analytics AND the learning write succeed.
        snap.next_retry_at = captured_at + timedelta(seconds=self._retry_delay(snap))
        self._save_snapshot(pid, snap)
        self._sync_learning(pub)
        # Historical repairs are synced through the latest record above.
        if self.latest_snapshot(pid).checkpoint != snap.checkpoint:
            snap.learning_synced = True
            if not self._needs_reconciliation(snap):
                snap.next_retry_at = None
            self._save_snapshot(pid, snap)
        else:
            snap = next(x for x in self.snapshots(pid) if x.checkpoint == checkpoint)
        complete = snap.statistics_ready and snap.analytics_status == "READY" and not snap.statistics_error and not snap.analytics_error
        autonomous_activity_store.append(
            phase="LEARNING", action="ANALYTICS_CAPTURED" if complete else "ANALYTICS_PENDING",
            status="SUCCESS" if complete else ("INFO" if snap.statistics_ready else "WARNING"),
            message=(f"Captured YouTube {checkpoint} statistics and processed analytics."
                     if complete else f"YouTube {checkpoint}: public statistics {snap.statistics_status.lower()}; analytics {snap.analytics_status.lower()}. Pending evidence will be retried."),
            recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
            details={"video_title": pub.video_title, "youtube_video_id": pub.youtube_video_id,
                     "checkpoint": checkpoint, "views": snap.views, "likes": snap.likes,
                     "published_at": anchor.isoformat(), "checkpoint_at": snap.observed_at.isoformat(),
                     "statistics_source": snap.statistics_source, "analytics_source": snap.analytics_source,
                     "comments": snap.comments, "average_percentage_viewed": snap.average_percentage_viewed,
                     "shares": snap.shares, "subscribers_gained": snap.subscribers_gained,
                     "subscribers_lost": snap.subscribers_lost,
                     "statistics_status": snap.statistics_status, "analytics_status": snap.analytics_status,
                     "statistics_observed_at": snap.statistics_observed_at.isoformat() if snap.statistics_observed_at else None,
                     "statistics_is_late": snap.statistics_is_late,
                     "analytics_start_date": start, "analytics_end_date": end,
                     "statistics_error": snap.statistics_error, "analytics_error": snap.analytics_error},
        )
        # Manual refreshes must also schedule retries for a previously inactive queue.
        next_delay = self._next_analytics_delay(pub)
        if next_delay is not None:
            youtube_autonomy_queue.sync(active=True, next_run_seconds=next_delay)
        self._wake_learning_supervisor(pub, snap)
        return snap

    def _next_analytics_delay(self, pub: YouTubePublication) -> float | None:
        anchor = release_anchor(pub)
        if not anchor:
            return None
        snapshots = self.snapshots(pub.publication_id)
        highest = max((dict(CHECKPOINTS).get(x.checkpoint, 0) for x in snapshots), default=0)
        current = now()
        grace = float(self.settings.autopilot_task_analytics_grace_seconds)
        delays = []
        for _name, hours in CHECKPOINTS:
            if hours > highest:
                due_at = anchor + timedelta(hours=hours)
                delays.append(max(30.0, (due_at - current).total_seconds() + grace))
                break
        for snap in snapshots:
            due_at = self._retry_due_at(pub, snap)
            if due_at is not None:
                delays.append(max(30.0, (due_at - current).total_seconds()))
        return min(delays) if delays else None

    async def autonomy_tick(self) -> tuple[bool, float]:
        """Reconcile uploads/releases and collect due analytics for this tenant.

        A revoked/expired OAuth refresh token is a human-action condition, not a
        transient provider error. Once detected, pause the queue until the user
        reconnects the channel instead of paying for 5-minute Cloud Run wake-ups.
        """
        if self._authorization_reconnect_required():
            return False, 0.0
        active = False
        soonest = (
            35.0 * 24.0 * 3600.0
            if self.settings.autopilot_event_driven_enabled
            else float(self.settings.youtube_autonomy_monitor_interval_seconds)
        )
        publications = self.list()
        for pub in publications:
            if pub.superseded_by_publication_id:
                continue
            try:
                if (
                    pub.status == YouTubePublishStatus.FAILED
                    and pub.upload_session_uri
                    and pub.error
                    and "sync request with an AsyncClient" in pub.error
                ):
                    # v3.3.1 could persist this HTTPX stream-type failure even though
                    # a valid resumable session already existed. Adopt that session
                    # instead of creating a second YouTube upload.
                    pub.status = YouTubePublishStatus.UPLOADING
                    pub.error = None
                    self._save_pub(pub)
                    autonomous_activity_store.append(
                        phase="YOUTUBE", action="UPLOAD_RECOVERY_ADOPTED", status="INFO",
                        message="Recovered the existing resumable YouTube upload after the v3.3.1 async-stream compatibility error.",
                        recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                        details={"video_title": pub.video_title},
                    )
                    active = True
                    await self._upload_publication(pub)
                    soonest = min(soonest, 60.0)
                    continue
                if pub.status == YouTubePublishStatus.UPLOADING:
                    active = True
                    await self._upload_publication(pub)
                    soonest = min(soonest, 60.0)
                    continue
                if pub.status == YouTubePublishStatus.SCHEDULED:
                    active = True
                    updated = await self.reconcile_remote_status(pub.publication_id)
                    if updated.status == YouTubePublishStatus.PUBLISHED:
                        soonest = min(soonest, 300.0)
                    elif updated.publish_at:
                        seconds = (updated.publish_at - now()).total_seconds() + float(self.settings.autopilot_task_public_probe_grace_seconds)
                        soonest = min(soonest, max(30.0, seconds))
                    continue
                if pub.status == YouTubePublishStatus.PUBLISHED:
                    # Published rows from older deployments also need migration.
                    # They no longer enter the SCHEDULED visibility-check branch.
                    if pub.release_clock_version < 2 or not pub.public_release_at:
                        pub = await self.reconcile_remote_status(pub.publication_id)
                        if pub.status != YouTubePublishStatus.PUBLISHED:
                            active = True
                            soonest = min(soonest, 300.0)
                            continue
                    checkpoint = self.due_checkpoint(pub)
                    if checkpoint:
                        active = True
                        await self.refresh_analytics(pub.publication_id, checkpoint=checkpoint)
                        pub = self.get(pub.publication_id)
                    next_delay = self._next_analytics_delay(pub)
                    if next_delay is not None:
                        active = True
                        soonest = min(soonest, next_delay)
            except YouTubeAuthorizationRequiredError:
                # The refresh token cannot recover by retrying. Stop after the first
                # affected publication; the worker will deactivate this tenant queue.
                return False, 0.0
            except Exception as exc:
                active = True
                soonest = min(soonest, 300.0)
                autonomous_activity_store.append(
                    phase="YOUTUBE", action="MONITOR_RETRY", status="WARNING",
                    message=f"Autonomous YouTube monitor will retry after a temporary error: {exc}",
                    recommendation_id=pub.recommendation_id, publication_id=pub.publication_id,
                    details={"video_title": pub.video_title},
                )
        return active, max(30.0, soonest)


youtube_publishing_service = YouTubePublishingService(get_settings())
