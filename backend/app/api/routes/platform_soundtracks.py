"""Private GCS-backed platform music catalog, independent of tenant music shelves.

All writes require a Firebase platform admin session. Public means available to
authenticated ReviveAI users through this API, never a publicly readable GCS blob.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.routes.platform_admin import require_platform_admin
from app.core.config import get_settings
from app.core.firebase_auth import require_authenticated_user
from app.core.firebase_clients import get_runtime_firestore_client, get_storage_client

router = APIRouter(prefix="/api/v1", tags=["platform-soundtracks"])
COLLECTION = "reviveai_platform_soundtracks"
MAX_BYTES = 25 * 1024 * 1024
ALLOWED = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4"}


def _catalog():
    return get_runtime_firestore_client().collection(COLLECTION)


def _bucket():
    path = get_settings().soundtrack_output_gcs_uri
    if not path.startswith("gs://"):
        raise RuntimeError("SOUNDTRACK_OUTPUT_GCS_URI must start with gs://")
    value = path[5:].strip("/")
    bucket, _, prefix = value.partition("/")
    if not bucket:
        raise RuntimeError("Soundtrack bucket is not configured")
    return get_storage_client().bucket(bucket), prefix


def _serial(doc):
    data = doc.to_dict() or {}
    return {key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in data.items() if key != "storage_key"}


def _record(track_id: str):
    snap = _catalog().document(track_id).get()
    if not snap.exists:
        raise HTTPException(404, "Soundtrack not found")
    return snap, snap.to_dict() or {}


def _validate_audio(path: str) -> None:
    try:
        import imageio_ffmpeg
        executable = imageio_ffmpeg.get_ffmpeg_exe()
        result = subprocess.run(
            [executable, "-v", "error", "-nostdin", "-i", path,
             "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired, ImportError) as exc:
        raise HTTPException(422, "Audio validation could not complete") from exc
    if result.returncode != 0:
        raise HTTPException(422, "Audio file could not be decoded")


def _probe_duration(path: str) -> float | None:
    """Measure actual decoded file duration without relying on expected clip length."""
    try:
        import imageio_ffmpeg
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", path,
             "-map", "0:a:0", "-f", "null", "-"],
            capture_output=True, timeout=90, check=False,
        )
        import re
        # FFmpeg emits elapsed processing time on stderr (final decoded timestamp).
        values = re.findall(rb"time=(\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if result.returncode == 0 and values:
            h, m, sec = values[-1]
            duration = int(h) * 3600 + int(m) * 60 + float(sec)
            return round(duration, 3) if duration > 0 else None
    except (ImportError, OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


class SoundtrackMetadata(BaseModel):
    license_name: str = Field(min_length=3, max_length=160)
    license_evidence: str = Field(default="", max_length=2000)
    attribution: str = Field(default="", max_length=1000)
    rights_confirmed: bool = False  # Compatibility only; never implies standalone approval.
    internal_video_use_approved: bool = False
    standalone_distribution_approved: bool = False
    internal_video_use_evidence: str = Field(default="", max_length=2000)


@router.patch("/admin/soundtracks/{track_id}/metadata")
def update_soundtrack_metadata(track_id: str, payload: SoundtrackMetadata,
                               claims: dict = Depends(require_platform_admin)):
    snap, data = _record(track_id)
    if data.get("status") in {"PUBLISHED", "RETIRED"}:
        raise HTTPException(409, "Published or retired music cannot be edited through draft review")
    evidence = payload.license_evidence.strip()
    if evidence and len(evidence) < 8:
        raise HTTPException(422, "Rights evidence must contain at least 8 characters")
    if payload.internal_video_use_approved and len(payload.internal_video_use_evidence.strip()) < 8:
        raise HTTPException(422, "Verified evidence is required for internal video-use approval")
    if payload.standalone_distribution_approved and len(evidence) < 8:
        raise HTTPException(422, "Verified distribution evidence is required before approval")
    if payload.standalone_distribution_approved and any(tag in evidence.upper() for tag in ("[VERIFY", "[ADD", "REVIEW PENDING", "REVIEW REQUIRED")):
        raise HTTPException(422, "Replace evidence placeholders with verified permission")
    # Editing evidence invalidates any earlier rights confirmation until reconfirmed.
    now = datetime.now(timezone.utc)
    snap.reference.update({
        "license_name": payload.license_name.strip(),
        "license_evidence": evidence, "attribution": payload.attribution.strip(),
        "rights_confirmed": bool(payload.standalone_distribution_approved),
        "rights_confirmed_by": claims["uid"] if payload.standalone_distribution_approved else None,
        "rights_confirmed_at": now if payload.standalone_distribution_approved else None,
        "internal_video_use_approved": payload.internal_video_use_approved,
        "internal_video_use_evidence": payload.internal_video_use_evidence.strip(),
        "internal_video_use_approved_by": claims["uid"] if payload.internal_video_use_approved else None,
        "internal_video_use_approved_at": now if payload.internal_video_use_approved else None,
        "standalone_distribution_approved": payload.standalone_distribution_approved,
        "standalone_distribution_approved_by": claims["uid"] if payload.standalone_distribution_approved else None,
        "standalone_distribution_approved_at": now if payload.standalone_distribution_approved else None,
        "updated_at": now, "last_changed_by": claims["uid"],
    })
    return {"track": _serial(snap.reference.get())}


@router.post("/admin/soundtracks/backfill-metadata")
def backfill_soundtrack_metadata(claims: dict = Depends(require_platform_admin)):
    """Admin-initiated idempotent backfill. No generation, no provider costs."""
    from app.services.platform_lyria_batch_service import BATCHES, ESTIMATED_USD
    db = get_runtime_firestore_client()
    bucket, _ = _bucket()
    enriched, skipped, errors = 0, 0, []
    for snap in _catalog().limit(250).stream():
        data = snap.to_dict() or {}
        if data.get("source") != "GOOGLE_LYRIA":
            skipped += 1
            continue
        updates = {}
        batch_id = data.get("batch_id")
        if batch_id and any(data.get(k) is None for k in ("mood", "requested_bpm", "generation_cost_estimated_usd")):
            for item in db.collection(BATCHES).document(batch_id).collection("tracks").stream():
                entry = item.to_dict() or {}
                if entry.get("track_id") == snap.id:
                    for dst, source in (("mood", "category"), ("requested_bpm", "bpm")):
                        if data.get(dst) is None and entry.get(source) is not None:
                            updates[dst] = entry[source]
                    break
        if data.get("generation_cost_estimated_usd") is None:
            updates["generation_cost_estimated_usd"] = ESTIMATED_USD
        if data.get("generation_cost_status") is None:
            updates["generation_cost_status"] = "ESTIMATED_NOT_BILLED"
        if data.get("duration_seconds") is None and data.get("storage_key"):
            try:
                with tempfile.NamedTemporaryFile(suffix=".mp3") as f:
                    bucket.blob(data["storage_key"]).download_to_filename(f.name)
                    duration = _probe_duration(f.name)
                    if duration is not None:
                        updates["duration_seconds"] = duration
            except Exception:
                errors.append(snap.id)
        if updates:
            updates["updated_at"] = datetime.now(timezone.utc)
            updates["metadata_backfilled_by"] = claims["uid"]
            snap.reference.update(updates)
            enriched += 1
        else:
            skipped += 1
    return {"enriched": enriched, "skipped": skipped, "duration_probe_failures": errors}


@router.get("/soundtracks/platform")
def creator_catalog(_: dict = Depends(require_authenticated_user)):
    rows = _catalog().where("status", "==", "PUBLISHED").limit(200).stream()
    return {"tracks": [{k: v for k, v in _serial(doc).items() if k not in {"license_evidence", "uploaded_by", "last_changed_by"}} for doc in rows]}


@router.get("/admin/soundtracks")
def admin_catalog(_: dict = Depends(require_platform_admin)):
    rows = _catalog().limit(250).stream()
    return {"tracks": [_serial(doc) for doc in rows]}


@router.post("/admin/soundtracks", status_code=201)
def upload_platform_track(
    file: UploadFile = File(...),
    title: str = Form(..., min_length=1, max_length=160),
    artist: str = Form("", max_length=160),
    license_name: str = Form(..., min_length=3, max_length=160),
    license_evidence: str = Form(..., min_length=8, max_length=2000),
    attribution: str = Form("", max_length=1000),
    rights_confirmed: bool = Form(False),
    claims: dict = Depends(require_platform_admin),
):
    if not rights_confirmed:
        raise HTTPException(422, "Confirm that ReviveAI has rights to distribute this soundtrack")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "Only .mp3, .wav and .m4a audio files are supported")
    track_id = "platform_" + uuid4().hex
    total = 0
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as output:
            tmp = output.name
            while chunk := file.file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(413, "Soundtrack exceeds the 25 MB upload limit")
                output.write(chunk)
        if total == 0:
            raise HTTPException(422, "The audio file is empty")
        _validate_audio(tmp)
        duration = _probe_duration(tmp)
        bucket, prefix = _bucket()
        key = "/".join(v for v in [prefix, "platform", track_id, "original" + suffix] if v)
        blob = bucket.blob(key)
        blob.upload_from_filename(tmp, content_type=ALLOWED[suffix], if_generation_match=0)
        now = datetime.now(timezone.utc)
        record = {
            "track_id": track_id, "title": title.strip(), "artist": artist.strip(),
            "license_name": license_name.strip(), "license_evidence": license_evidence.strip(),
            "attribution": attribution.strip(), "status": "DRAFT", "owner_type": "PLATFORM",
            "uploaded_by": claims["uid"], "storage_key": key, "content_type": ALLOWED[suffix],
            "size_bytes": total, "duration_seconds": duration,
            "rights_confirmed": True, "standalone_distribution_approved": True,
            "standalone_distribution_approved_by": claims["uid"],
            "standalone_distribution_approved_at": now, "rights_confirmed_by": claims["uid"],
            "rights_confirmed_at": now, "created_at": now, "updated_at": now,
        }
        try:
            _catalog().document(track_id).create(record)
        except Exception:
            blob.delete()
            raise
        return {"track": _serial(_catalog().document(track_id).get())}
    finally:
        file.file.close()
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


class StatusChange(BaseModel):
    status: str = Field(pattern="^(PENDING_REVIEW|PUBLISHED|RETIRED)$")


@router.patch("/admin/soundtracks/{track_id}/status")
def change_platform_track_status(track_id: str, payload: StatusChange,
                                 claims: dict = Depends(require_platform_admin)):
    snap, data = _record(track_id)
    old = data.get("status")
    allowed = {"DRAFT": {"PENDING_REVIEW", "RETIRED"},
               "PENDING_REVIEW": {"PUBLISHED", "RETIRED"},
               "PUBLISHED": {"RETIRED"}, "RETIRED": set()}
    if payload.status not in allowed.get(old, set()):
        raise HTTPException(409, f"Cannot transition {old} to {payload.status}")
    if payload.status == "PUBLISHED":
        if not (str(data.get("license_name") or "").strip() and len(str(data.get("license_evidence") or "").strip()) >= 8):
            raise HTTPException(409, "License evidence is required before publication")
        if not data.get("standalone_distribution_approved"):
            raise HTTPException(409, "Verified standalone distribution approval is required before publication")
    snap.reference.update({"status": payload.status, "updated_at": datetime.now(timezone.utc),
                           "last_changed_by": claims["uid"]}, option=None)
    return {"track": _serial(snap.reference.get())}


@router.get("/soundtracks/platform/{track_id}/preview")
def preview_platform_track(track_id: str, _: dict = Depends(require_authenticated_user)):
    _, data = _record(track_id)
    if data.get("status") != "PUBLISHED":
        raise HTTPException(404, "Soundtrack not available")
    return _download(data)


@router.get("/admin/soundtracks/{track_id}/preview")
def preview_admin_track(track_id: str, _: dict = Depends(require_platform_admin)):
    _, data = _record(track_id)
    return _download(data)


def _download(data):
    bucket, prefix = _bucket()
    key = str(data.get("storage_key") or "")
    if not key.startswith((prefix + "/platform/" if prefix else "platform/")):
        raise HTTPException(500, "Invalid platform soundtrack storage reference")
    if int(data.get("size_bytes") or 0) > MAX_BYTES:
        raise HTTPException(413, "Stored soundtrack exceeds preview limit")
    try:
        content = bucket.blob(key).download_as_bytes()
    except Exception as exc:
        raise HTTPException(503, "Soundtrack preview unavailable") from exc
    return Response(content, media_type=data.get("content_type") or "application/octet-stream",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
