from __future__ import annotations

import hashlib
import logging
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import Optional

from app.core.config import Settings, get_settings
from app.core.firebase_clients import get_storage_client
from app.core.tenant import tenant_namespace
from app.services.gcs_uri_service import parse_gcs_uri

logger = logging.getLogger(__name__)


class RuntimeArtifactStore:
    """Tenant-scoped GCS mirror for runtime-generated binary/text artifacts.

    Job metadata remains in Firestore. Files stay locally cached for ffmpeg/FileResponse,
    but every durable artifact is mirrored to GCS and can be lazily restored after a
    Cloud Run instance replacement.
    """

    def __init__(self, category: str, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.category = self._safe_component(category)
        self._lock = Lock()
        self._digest_cache: dict[tuple[str, int, int], str] = {}

        uri = (self.settings.effective_runtime_asset_gcs_uri or "").strip()
        self.enabled = bool(uri)
        self.bucket_name = ""
        self.prefix = ""
        if self.enabled:
            parsed = parse_gcs_uri(uri)
            self.bucket_name = parsed["bucket"]
            self.prefix = parsed["prefix"].strip("/")

    @staticmethod
    def _safe_component(value: str) -> str:
        raw = (value or "").strip()
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)
        if not safe or safe in {".", ".."}:
            raise ValueError("artifact path component is invalid")
        return safe[:180]

    @classmethod
    def _safe_relative(cls, value: str) -> str:
        raw = (value or "").replace("\\", "/").strip("/")
        parts = [cls._safe_component(part) for part in PurePosixPath(raw).parts if part not in {"", "."}]
        if not parts or any(part == ".." for part in parts):
            raise ValueError("artifact relative path is invalid")
        return "/".join(parts)

    def _object_name(self, owner_id: str, relative_path: str) -> str:
        owner = self._safe_component(owner_id)
        relative = self._safe_relative(relative_path)
        parts = [part for part in [self.prefix, "tenants", tenant_namespace(), self.category, owner, relative] if part]
        return "/".join(parts)

    @staticmethod
    def _parse_explicit_uri(uri: str) -> tuple[str, str]:
        parsed = parse_gcs_uri(uri)
        return parsed["bucket"], parsed["prefix"].strip("/")

    def uri_for(self, owner_id: str, relative_path: str) -> Optional[str]:
        if not self.enabled:
            return None
        return f"gs://{self.bucket_name}/{self._object_name(owner_id, relative_path)}"

    def _sha256_file(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            cached = self._digest_cache.get(key)
        if cached:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        with self._lock:
            self._digest_cache[key] = value
        return value

    def upload_file(
        self,
        local_path: Path,
        *,
        owner_id: str,
        relative_path: str,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        local_path = Path(local_path)
        if not local_path.exists() or not local_path.is_file():
            return None

        object_name = self._object_name(owner_id, relative_path)
        blob = get_storage_client().bucket(self.bucket_name).blob(object_name)
        digest = self._sha256_file(local_path)

        try:
            if blob.exists():
                blob.reload()
                metadata = blob.metadata or {}
                if metadata.get("reviveai_sha256") == digest and int(blob.size or 0) == local_path.stat().st_size:
                    return f"gs://{self.bucket_name}/{object_name}"
        except Exception:
            logger.warning("Could not inspect existing runtime artifact %s; uploading a fresh copy", object_name, exc_info=True)

        blob.upload_from_filename(str(local_path), content_type=content_type)
        blob.metadata = {
            **(blob.metadata or {}),
            "reviveai_sha256": digest,
            "reviveai_category": self.category,
        }
        blob.patch()
        return f"gs://{self.bucket_name}/{object_name}"

    def upload_file_create_only(
        self,
        local_path: Path,
        *,
        owner_id: str,
        relative_path: str,
        content_type: Optional[str] = None,
    ) -> Optional[str]:
        """Immutable runtime upload. Never overwrite a different object's bytes.

        Uploads the digest as object metadata atomically and verifies the
        stored generation, size and checksum after upload. Existing objects
        may be reused only when the original bytes are identical.
        """
        if not self.enabled:
            return None
        local_path = Path(local_path)
        if not local_path.is_file():
            raise FileNotFoundError(local_path)
        from google.api_core.exceptions import PreconditionFailed

        object_name = self._object_name(owner_id, relative_path)
        uri = f"gs://{self.bucket_name}/{object_name}"
        bucket = get_storage_client().bucket(self.bucket_name)
        digest = self._sha256_file(local_path)
        expected_size = local_path.stat().st_size
        blob = bucket.blob(object_name)
        blob.metadata = {"reviveai_sha256": digest, "reviveai_category": self.category}
        try:
            blob.upload_from_filename(
                str(local_path), content_type=content_type, if_generation_match=0
            )
        except PreconditionFailed:
            pass  # Verify the existing object; never overwrite it.
        verified = bucket.blob(object_name)
        verified.reload()
        metadata = verified.metadata or {}
        if (metadata.get("reviveai_sha256") != digest
                or int(verified.size or -1) != expected_size
                or not verified.generation):
            raise RuntimeError(f"Immutable runtime GCS object conflict: {uri}")
        # Metadata is not cryptographic proof: verify actual remote bytes too.
        remote_hash = hashlib.sha256()
        from tempfile import TemporaryFile
        with TemporaryFile() as temp:
            verified.download_to_file(temp, if_generation_match=int(verified.generation))
            temp.seek(0)
            for block in iter(lambda: temp.read(1024 * 1024), b""):
                remote_hash.update(block)
        if remote_hash.hexdigest() != digest:
            raise RuntimeError(f"Immutable runtime GCS object content mismatch: {uri}")
        return uri

    def ensure_local(
        self,
        local_path: Path,
        *,
        owner_id: str,
        relative_path: str,
        gcs_uri: Optional[str] = None,
    ) -> Path:
        local_path = Path(local_path)
        if local_path.exists():
            return local_path

        if gcs_uri:
            bucket_name, object_name = self._parse_explicit_uri(gcs_uri)
        else:
            if not self.enabled:
                return local_path
            bucket_name = self.bucket_name
            object_name = self._object_name(owner_id, relative_path)

        blob = get_storage_client().bucket(bucket_name).blob(object_name)
        if not blob.exists():
            return local_path

        local_path.parent.mkdir(parents=True, exist_ok=True)
        temp = local_path.with_suffix(local_path.suffix + ".download")
        blob.download_to_filename(str(temp))
        temp.replace(local_path)
        return local_path

    def exists(
        self,
        *,
        owner_id: str,
        relative_path: str,
        gcs_uri: Optional[str] = None,
    ) -> bool:
        if gcs_uri:
            bucket_name, object_name = self._parse_explicit_uri(gcs_uri)
        else:
            if not self.enabled:
                return False
            bucket_name = self.bucket_name
            object_name = self._object_name(owner_id, relative_path)
        return bool(get_storage_client().bucket(bucket_name).blob(object_name).exists())
