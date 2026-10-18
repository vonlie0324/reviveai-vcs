"""V9F isolated, dependency-injected GCS create-only staging contract.

No default credentials, no imports from app, no production commit workflow.
Caller must inject a CloudStorageService-like instance with a fake client in tests.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

class StagingConflict(RuntimeError):
    pass


def stage_create_only(storage, local_path: Path, storage_path: str, expected_sha256: str, *, content_type: str) -> str:
    """Safely create once or verify an exact existing object; never overwrite.

    Uses CloudStorageService.bucket_name/_require_client/real Blob API shape.
    Intentionally DOES NOT call CloudStorageService.upload_file (no precondition).
    """
    local_path = Path(local_path)
    if not local_path.is_file():
        raise StagingConflict(f"Missing local file: {local_path}")
    with local_path.open('rb') as handle:
        actual = hashlib.file_digest(handle, 'sha256').hexdigest()
    if actual != expected_sha256:
        raise StagingConflict('Local SHA-256 mismatch')
    if not storage_path or storage_path.startswith('/') or '..' in storage_path.split('/'):
        raise StagingConflict('Unsafe object path')
    client = storage._require_client()
    blob = client.bucket(storage.bucket_name).blob(storage_path)
    try:
        blob.upload_from_filename(str(local_path), content_type=content_type, if_generation_match=0)
        outcome = 'CREATED'
    except Exception as exc:
        # Only a 412 precondition failure is an acceptable idempotent retry.
        if not (getattr(exc, 'code', None) == 412 or exc.__class__.__name__ == 'PreconditionFailed'):
            raise
        outcome = 'REUSED_VERIFIED'
    # Verify the actual stored bytes rather than relying on provider md5, which
    # can be absent for composite objects and differs from SHA-256.
    data = blob.download_as_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise StagingConflict('Remote SHA-256 mismatch; refusing finalization')
    if len(data) != local_path.stat().st_size:
        raise StagingConflict('Remote length mismatch')
    return outcome
