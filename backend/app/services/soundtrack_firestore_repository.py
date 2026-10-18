from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.tenant import tenant_namespace


class SoundtrackFirestoreRepository:
    """Tenant-scoped Firestore registry for reusable soundtrack metadata.

    Audio binaries live in Cloud Storage. Firestore is the durable source of truth
    for the searchable catalog and the pointer to each Cloud Storage object.
    """

    ROOT_COLLECTION = "reviveai_tenants"
    SUBCOLLECTION = "soundtracks"

    def __init__(self, db=None):
        self.db = db

    def _collection(self):
        if self.db is None:
            return None
        return (
            self.db.collection(self.ROOT_COLLECTION)
            .document(tenant_namespace())
            .collection(self.SUBCOLLECTION)
        )

    def create(self, track_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        document = {
            "track_id": track_id,
            **payload,
            "created_at": payload.get("created_at") or now,
            "updated_at": now,
        }

        collection = self._collection()
        if collection is None:
            raise RuntimeError("Firestore soundtrack repository is not initialized.")

        collection.document(track_id).set(document, merge=True)
        return document

    def get(self, track_id: str) -> Optional[dict[str, Any]]:
        collection = self._collection()
        if collection is None:
            raise RuntimeError("Firestore soundtrack repository is not initialized.")

        snapshot = collection.document(track_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def list(self, channel_id: Optional[str] = None) -> list[dict[str, Any]]:
        collection = self._collection()
        if collection is None:
            raise RuntimeError("Firestore soundtrack repository is not initialized.")

        # The soundtrack shelf is tenant reusable by default. channel_id remains
        # supported for callers that intentionally maintain channel-specific tracks.
        query = collection
        if channel_id:
            query = query.where("channel_id", "==", channel_id)

        documents = [doc.to_dict() for doc in query.stream()]

        def sort_key(item: dict[str, Any]) -> datetime:
            value = item.get("imported_at") or item.get("created_at")
            if isinstance(value, datetime):
                result = value
            else:
                try:
                    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                except Exception:
                    result = datetime.min.replace(tzinfo=timezone.utc)
            if result.tzinfo is None:
                result = result.replace(tzinfo=timezone.utc)
            return result

        documents.sort(key=sort_key, reverse=True)
        return documents

    def delete(self, track_id: str) -> None:
        collection = self._collection()
        if collection is None:
            raise RuntimeError("Firestore soundtrack repository is not initialized.")
        collection.document(track_id).delete()

    def with_preview_url(self, track: dict[str, Any], storage_service) -> dict[str, Any]:
        result = dict(track)
        storage_path = result.get("storage_path")
        if storage_path:
            result["preview_url"] = storage_service.generate_signed_url(storage_path)
        return result
