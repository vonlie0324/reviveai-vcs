"""Recovery artifact storage primitive; not a recovery runner.

Can accept google-cloud-storage Bucket, but intentionally has no credentials,
no Cloud client construction, and no production executable entrypoint.
Caller must enforce maintenance and journal fencing before using this primitive.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

class ArtifactMismatch(RuntimeError):
    pass

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not isinstance(uri, str) or not uri.startswith('gs://'):
        raise ArtifactMismatch('Expected gs:// URI')
    part=uri[5:].split('/', 1)
    if len(part)!=2 or not part[0] or not part[1] or '\\' in part[1] or any(p in ('', '.', '..') for p in part[1].split('/')):
        raise ArtifactMismatch('Unsafe GCS object reference')
    return part[0],part[1]

def stage_verified(bucket, *, uri: str, path: Path, expected_sha256: str, expected_size: int,
                   prefix: str, content_type: str) -> dict:
    """Create-once staging; preexisting identical objects can be safely resumed.

    A remote read-back verifies SHA-256 of *bytes*, not just GCS CRC32C or metadata.
    GCS generation protects identity; retry never overwrites an existing object.
    """
    b,name=parse_gs_uri(uri)
    if b!=bucket.name or not name.startswith(prefix) or not prefix.endswith('/'):
        raise ArtifactMismatch('Bucket or tenant/job prefix mismatch')
    raw=path.read_bytes()
    if len(raw)!=expected_size or sha256(raw)!=expected_sha256:
        raise ArtifactMismatch('Local media hash/size mismatch')
    blob=bucket.blob(name)
    try:
        blob.upload_from_string(raw,content_type=content_type,if_generation_match=0)
        disposition='CREATED'
    except Exception as exc:
        # Resume only on a genuine precondition conflict (HTTP 412), never on
        # network failures or auth errors. Avoid importing google libraries here.
        code=getattr(exc,'code',None)
        if code!=412:
            raise
        disposition='EXISTING_VERIFIED'
    remote=bucket.get_blob(name)
    if remote is None or getattr(remote,'generation',None) is None:
        raise ArtifactMismatch('Missing remote object or GCS generation')
    gen=int(remote.generation)
    if gen<=0: raise ArtifactMismatch('Invalid remote generation')
    # If the blob changes between metadata fetch and download, generation-match
    # makes the read fail instead of silently attesting a different object.
    verified=bucket.blob(name,generation=gen).download_as_bytes()
    if len(verified)!=expected_size or sha256(verified)!=expected_sha256:
        raise ArtifactMismatch('Remote object digest mismatch')
    return {'gcs_uri':uri,'sha256':expected_sha256,'size_bytes':expected_size,
            'generation':gen,'status':disposition,'verified':True}
