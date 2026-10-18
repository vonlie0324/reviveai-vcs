from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PublicationClaim:
    publication_id: str
    master_fingerprint: str
    acquired: bool


class YouTubePublicationClaimService:
    """Cross-instance idempotency + upload leases for YouTube publication.

    A final approved master may be observed by both the Autopilot supervisor and
    the YouTube autonomy worker. Firestore transactions ensure only one initial
    publication claim exists for that exact master, and only one process may
    mutate/upload one publication at a time.
    """

    ROOT_COLLECTION = "reviveai_tenants"
    CLAIMS_COLLECTION = "youtube_publication_claims"
    UPLOAD_LEASES_COLLECTION = "youtube_upload_leases"

    def _tenant_doc(self):
        return (
            get_runtime_firestore_client()
            .collection(self.ROOT_COLLECTION)
            .document(tenant_namespace())
        )

    @staticmethod
    def master_fingerprint(*, audio_job_id: str, audio_version: int, delivery_asset_id: Optional[str]) -> str:
        raw = f"{audio_job_id}|{int(audio_version)}|{delivery_asset_id or ''}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def deterministic_publication_id(master_fingerprint: str) -> str:
        return f"ytpub_{master_fingerprint[:20]}"

    def claim_master(
        self,
        *,
        master_fingerprint: str,
        owner: str,
        lease_seconds: int = 300,
    ) -> PublicationClaim:
        from google.cloud import firestore

        publication_id = self.deterministic_publication_id(master_fingerprint)
        ref = self._tenant_doc().collection(self.CLAIMS_COLLECTION).document(master_fingerprint)
        transaction = get_runtime_firestore_client().transaction()
        now = _now()
        expires = now + timedelta(seconds=max(60, int(lease_seconds)))

        @firestore.transactional
        def _claim(txn):
            snap = ref.get(transaction=txn)
            if not snap.exists:
                txn.set(
                    ref,
                    {
                        "master_fingerprint": master_fingerprint,
                        "publication_id": publication_id,
                        "status": "CLAIMED",
                        "claim_owner": owner,
                        "lease_expires_at": expires,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                return True, publication_id

            data = snap.to_dict() or {}
            persisted_publication_id = str(data.get("publication_id") or publication_id)
            if str(data.get("status") or "").upper() == "PERSISTED":
                return False, persisted_publication_id

            current_owner = str(data.get("claim_owner") or "")
            current_expiry = data.get("lease_expires_at")
            if (
                current_owner
                and current_owner != owner
                and isinstance(current_expiry, datetime)
                and current_expiry > now
            ):
                return False, persisted_publication_id

            # Recover a claim whose creator died before persisting the publication.
            txn.set(
                ref,
                {
                    "publication_id": persisted_publication_id,
                    "status": "CLAIMED",
                    "claim_owner": owner,
                    "lease_expires_at": expires,
                    "updated_at": now,
                    "reclaimed_at": now,
                },
                merge=True,
            )
            return True, persisted_publication_id

        acquired, resolved_publication_id = _claim(transaction)
        return PublicationClaim(
            publication_id=str(resolved_publication_id or publication_id),
            master_fingerprint=master_fingerprint,
            acquired=bool(acquired),
        )

    def mark_persisted(self, *, master_fingerprint: str, publication_id: str) -> None:
        self._tenant_doc().collection(self.CLAIMS_COLLECTION).document(master_fingerprint).set(
            {
                "publication_id": publication_id,
                "status": "PERSISTED",
                "claim_owner": "",
                "lease_expires_at": _now(),
                "persisted_at": _now(),
                "updated_at": _now(),
            },
            merge=True,
        )

    def acquire_upload_lease(self, *, publication_id: str, owner: str, lease_seconds: int = 300) -> bool:
        from google.cloud import firestore

        ref = self._tenant_doc().collection(self.UPLOAD_LEASES_COLLECTION).document(publication_id)
        transaction = get_runtime_firestore_client().transaction()
        now = _now()
        expires = now + timedelta(seconds=max(60, int(lease_seconds)))

        @firestore.transactional
        def _acquire(txn):
            snap = ref.get(transaction=txn)
            data = snap.to_dict() if snap.exists else {}
            current_owner = str((data or {}).get("lease_owner") or "")
            current_expiry = (data or {}).get("lease_expires_at")
            if (
                current_owner
                and current_owner != owner
                and isinstance(current_expiry, datetime)
                and current_expiry > now
            ):
                return False
            txn.set(
                ref,
                {
                    "publication_id": publication_id,
                    "lease_owner": owner,
                    "lease_acquired_at": now,
                    "lease_expires_at": expires,
                    "updated_at": now,
                },
                merge=True,
            )
            return True

        return bool(_acquire(transaction))

    def release_upload_lease(self, *, publication_id: str, owner: str) -> None:
        from google.cloud import firestore

        ref = self._tenant_doc().collection(self.UPLOAD_LEASES_COLLECTION).document(publication_id)
        transaction = get_runtime_firestore_client().transaction()
        now = _now()

        @firestore.transactional
        def _release(txn):
            snap = ref.get(transaction=txn)
            if not snap.exists:
                return
            data = snap.to_dict() or {}
            if str(data.get("lease_owner") or "") != owner:
                return
            txn.set(
                ref,
                {
                    "lease_owner": "",
                    "lease_expires_at": now,
                    "lease_released_at": now,
                    "updated_at": now,
                },
                merge=True,
            )

        _release(transaction)


youtube_publication_claim_service = YouTubePublicationClaimService()
