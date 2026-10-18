from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace


class FirestoreJobRepository:
    """Tenant-scoped durable JSON repository for ReviveAI job documents.

    Small Pydantic payloads are stored inline as JSON for simple reads. Large
    payloads (notably Channel Analysis snapshots) are gzip-compressed and split
    across chunk documents so they stay safely below Firestore's per-document
    size limit. The public repository API remains unchanged for callers.

    Existing schema-v1 inline documents remain readable.
    """

    ROOT_COLLECTION = "reviveai_tenants"
    SCHEMA_VERSION = 2

    STORAGE_INLINE = "inline-json-v1"
    STORAGE_CHUNKED = "gzip-chunks-v1"
    CHUNK_SUBCOLLECTION = "_payload_chunks"

    # Firestore documents have a ~1 MiB maximum encoded size. Keep both inline
    # JSON and individual binary chunks well below that boundary so field-name
    # and protocol overhead cannot push a document over the limit.
    INLINE_JSON_LIMIT_BYTES = 700 * 1024
    CHUNK_SIZE_BYTES = 600 * 1024

    def __init__(self, collection_name: str):
        name = (collection_name or "").strip()
        if not name:
            raise ValueError("collection_name is required")
        self.collection_name = name

    def _collection(self, namespace: Optional[str] = None):
        ns = (namespace or tenant_namespace()).strip()
        if not ns:
            raise ValueError("tenant namespace is required")
        return (
            get_runtime_firestore_client()
            .collection(self.ROOT_COLLECTION)
            .document(ns)
            .collection(self.collection_name)
        )

    @staticmethod
    def _encode(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_inline(data: dict[str, Any] | None) -> Optional[dict[str, Any]]:
        if not data:
            return None
        raw = data.get("payload_json")
        if not isinstance(raw, str) or not raw:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def _chunk_bytes(cls, data: bytes) -> list[bytes]:
        return [
            data[offset : offset + cls.CHUNK_SIZE_BYTES]
            for offset in range(0, len(data), cls.CHUNK_SIZE_BYTES)
        ]

    def _decode_document(self, document_ref, data: dict[str, Any] | None) -> Optional[dict[str, Any]]:
        if not data:
            return None

        # Backward compatibility: schema-v1 documents and current small payloads
        # both expose payload_json directly.
        inline = self._decode_inline(data)
        if inline is not None:
            return inline

        if data.get("storage_mode") != self.STORAGE_CHUNKED:
            return None

        generation = str(data.get("chunk_generation") or "").strip()
        chunk_count = data.get("chunk_count")
        expected_compressed_sha = str(data.get("compressed_sha256") or "").strip()
        expected_payload_sha = str(data.get("payload_sha256") or "").strip()

        if not generation or not isinstance(chunk_count, int) or chunk_count <= 0:
            return None

        chunks: list[bytes] = []
        chunk_collection = document_ref.collection(self.CHUNK_SUBCOLLECTION)
        for index in range(chunk_count):
            snapshot = chunk_collection.document(f"{generation}_{index:06d}").get()
            if not snapshot.exists:
                return None
            chunk_data = snapshot.to_dict() or {}
            raw = chunk_data.get("payload_bytes")
            if not isinstance(raw, (bytes, bytearray)):
                return None
            chunks.append(bytes(raw))

        compressed = b"".join(chunks)
        if expected_compressed_sha and self._sha256(compressed) != expected_compressed_sha:
            raise ValueError("Firestore payload chunk integrity check failed")

        raw_json = gzip.decompress(compressed)
        if expected_payload_sha and self._sha256(raw_json) != expected_payload_sha:
            raise ValueError("Firestore payload integrity check failed")

        value = json.loads(raw_json.decode("utf-8"))
        return value if isinstance(value, dict) else None

    def _cleanup_chunks(self, document_ref, *, keep_generation: Optional[str] = None) -> None:
        """Delete stale payload chunks after the new authoritative document is saved."""
        try:
            for snapshot in document_ref.collection(self.CHUNK_SUBCOLLECTION).stream():
                if keep_generation and snapshot.id.startswith(f"{keep_generation}_"):
                    continue
                snapshot.reference.delete()
        except Exception:
            # Chunk cleanup is best-effort. Old chunks are unreachable because the
            # parent manifest names the active generation, so a cleanup failure must
            # never make a successful job save fail.
            return

    def save(self, item_id: str, payload: dict[str, Any], *, namespace: Optional[str] = None) -> None:
        item_id = (item_id or "").strip()
        if not item_id:
            raise ValueError("item_id is required")

        document_ref = self._collection(namespace).document(item_id)
        payload_json = self._encode(payload)
        raw_json = payload_json.encode("utf-8")
        persisted_at = datetime.now(timezone.utc)

        if len(raw_json) <= self.INLINE_JSON_LIMIT_BYTES:
            document_ref.set(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "storage_mode": self.STORAGE_INLINE,
                    "payload_json": payload_json,
                    "payload_size_bytes": len(raw_json),
                    "payload_sha256": self._sha256(raw_json),
                    "persisted_at": persisted_at,
                }
            )
            self._cleanup_chunks(document_ref)
            return

        compressed = gzip.compress(raw_json, compresslevel=6)
        chunks = self._chunk_bytes(compressed)
        generation = uuid.uuid4().hex
        chunk_collection = document_ref.collection(self.CHUNK_SUBCOLLECTION)

        # Write a new generation first. The old parent manifest remains readable
        # until the new generation is complete, avoiding partially-written reads.
        for index, chunk in enumerate(chunks):
            chunk_collection.document(f"{generation}_{index:06d}").set(
                {
                    "schema_version": self.SCHEMA_VERSION,
                    "chunk_generation": generation,
                    "chunk_index": index,
                    "payload_bytes": chunk,
                }
            )

        document_ref.set(
            {
                "schema_version": self.SCHEMA_VERSION,
                "storage_mode": self.STORAGE_CHUNKED,
                "compression": "gzip",
                "chunk_generation": generation,
                "chunk_count": len(chunks),
                "payload_size_bytes": len(raw_json),
                "compressed_size_bytes": len(compressed),
                "payload_sha256": self._sha256(raw_json),
                "compressed_sha256": self._sha256(compressed),
                "persisted_at": persisted_at,
            }
        )

        self._cleanup_chunks(document_ref, keep_generation=generation)

    def load(self, item_id: str, *, namespace: Optional[str] = None) -> Optional[dict[str, Any]]:
        item_id = (item_id or "").strip()
        if not item_id:
            return None
        snapshot = self._collection(namespace).document(item_id).get()
        if not snapshot.exists:
            return None
        return self._decode_document(snapshot.reference, snapshot.to_dict() or {})

    def delete(self, item_id: str, *, namespace: Optional[str] = None) -> None:
        item_id = (item_id or "").strip()
        if not item_id:
            return
        document_ref = self._collection(namespace).document(item_id)
        self._cleanup_chunks(document_ref)
        document_ref.delete()

    def stream(self, *, namespace: Optional[str] = None) -> Iterable[tuple[str, dict[str, Any]]]:
        for snapshot in self._collection(namespace).stream():
            payload = self._decode_document(snapshot.reference, snapshot.to_dict() or {})
            if payload is not None:
                yield snapshot.id, payload
