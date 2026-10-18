from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from app.services.gcs_uri_service import parse_gcs_uri


class CloudStorageService:
    def __init__(self, gcs_uri, client=None):
        parsed = parse_gcs_uri(gcs_uri)
        self.bucket_name = parsed["bucket"]
        self.prefix = parsed["prefix"]
        self.client = client

    def _require_client(self):
        if self.client is None:
            # Preserve compatibility with services that construct CloudStorageService
            # directly. Resolve ADC lazily so import-time initialization stays cheap.
            from app.core.firebase_clients import get_storage_client

            self.client = get_storage_client()
        return self.client

    def build_path(self, filename):
        return f"{self.prefix}/{filename}".strip("/")

    def exists(self, storage_path):
        client = self._require_client()
        return client.bucket(self.bucket_name).blob(storage_path).exists()

    def generate_signed_url(self, storage_path, expiration_minutes=60):
        client = self._require_client()
        blob = client.bucket(self.bucket_name).blob(storage_path)
        return blob.generate_signed_url(
            expiration=timedelta(minutes=expiration_minutes),
            method="GET",
        )

    def upload_file(self, local_path: Path, storage_path, *, content_type=None):
        client = self._require_client()
        blob = client.bucket(self.bucket_name).blob(storage_path)
        blob.upload_from_filename(str(local_path), content_type=content_type)
        return storage_path

    def upload_bytes(self, payload: bytes, storage_path: str, *, content_type=None):
        client = self._require_client()
        blob = client.bucket(self.bucket_name).blob(storage_path)
        blob.upload_from_string(payload, content_type=content_type)
        return storage_path

    def download_file(self, storage_path: str, destination: Path) -> Path:
        client = self._require_client()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        client.bucket(self.bucket_name).blob(storage_path).download_to_filename(str(destination))
        return destination

    def download_temp(self, storage_path: str) -> Path:
        from tempfile import NamedTemporaryFile

        suffix = Path(storage_path).suffix
        with NamedTemporaryFile(prefix="reviveai_soundtrack_", suffix=suffix, delete=False) as handle:
            destination = Path(handle.name)
        try:
            return self.download_file(storage_path, destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def delete(self, storage_path: str) -> None:
        client = self._require_client()
        blob = client.bucket(self.bucket_name).blob(storage_path)
        try:
            blob.delete()
        except Exception as exc:
            # google-cloud-storage raises NotFound for an already deleted object.
            # Treat that operation as idempotent without importing a provider-specific
            # exception into every caller.
            if exc.__class__.__name__ != "NotFound":
                raise
