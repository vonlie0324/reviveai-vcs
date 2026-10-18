"""Admin-driven, resumable Lyria clip generation. No automatic retry of uncertain charges."""
from __future__ import annotations

import hashlib
import base64
import binascii
import subprocess
import logging
import os
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from google.cloud import firestore

from app.core.firebase_clients import get_runtime_firestore_client
from app.api.routes.platform_soundtracks import _bucket, _validate_audio, _probe_duration, COLLECTION

logger = logging.getLogger(__name__)

BATCHES = "reviveai_platform_music_batches"
MODEL = "lyria-3-clip-preview"
ESTIMATED_USD = 0.04  # configuration-time estimate; NOT verified provider billing
CATEGORIES = [
    ("Playful & Comedy", [("Whimsical Mischief", "pizzicato strings, marimba", 112), ("Cheeky Footsteps", "clarinet, ukulele, wood blocks", 124), ("Slapstick Surprise", "muted brass, bouncing piano", 138)]),
    ("Happy & Uplifting", [("Sunny Morning", "acoustic guitar, hand claps", 116), ("Joyful Momentum", "warm piano, light pop drums", 126), ("Celebration Glow", "bright strings, glockenspiel", 120)]),
    ("Mystery & Suspense", [("Tiny Detective", "pizzicato cello, brushed percussion", 98), ("Curious Clues", "marimba, bass clarinet", 106), ("Midnight Puzzle", "soft synth pulses, muted strings", 104)]),
    ("Adventure & Action", [("First Expedition", "acoustic percussion, strings", 130), ("The Great Chase", "rhythmic strings, toms", 145), ("Brave Horizon", "horns, light snare", 122)]),
    ("Emotional & Heartwarming", [("Gentle Reunion", "felt piano, warm cello", 76), ("Kindred Memories", "fingerstyle guitar, soft strings", 88), ("Golden Moment", "piano, subtle orchestral strings", 82)]),
    ("Cinematic & Epic", [("Bright Arrival", "orchestral strings, soft timpani", 110), ("Rising Resolve", "piano ostinato, French horns", 115), ("Final Triumph", "brass, orchestral percussion", 128)]),
    ("Calm & Relaxing", [("Slow Breathing", "gentle electric piano, ambient pads", 68), ("Quiet Garden", "nylon guitar, soft flute", 74), ("Blue Sky", "ambient keys, delicate harp", 80)]),
    ("Educational & Corporate", [("Fresh Ideas", "marimba, plucked synth", 106), ("Clear Thinking", "light piano, subtle electronic drums", 110), ("Forward Motion", "acoustic guitar, simple beat", 118)]),
    ("Technology & Futuristic", [("Soft Circuit", "warm analog synths, light arpeggios", 108), ("Digital Discovery", "plucked synth, clean pulse", 120), ("Future Friendly", "shimmering synthesizers, restrained beat", 115)]),
    ("Luxury & Elegant", [("Evening Lounge", "soft jazz piano, upright bass", 92), ("Silk & Satin", "harp, chamber strings", 84), ("Golden Gallery", "clean electric piano, brushed jazz kit", 94)]),
]


def _now():
    return datetime.now(timezone.utc)


def _batch_ref(batch_id):
    return get_runtime_firestore_client().collection(BATCHES).document(batch_id)


def _safe(doc):
    data = doc.to_dict() or {}
    return {k: v.isoformat() if isinstance(v, datetime) else v for k, v in data.items()}


def list_batches():
    return {"batches": [_safe(d) for d in get_runtime_firestore_client().collection(BATCHES).limit(30).stream()]}


def get_batch(batch_id):
    ref = _batch_ref(batch_id)
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(404, "Music batch not found")
    tracks = [_safe(d) for d in ref.collection("tracks").order_by("index").stream()]
    return {"batch": _safe(snap), "tracks": tracks}


def create_batch(count: int, uid: str):
    if count not in (3, 10, 30):
        raise HTTPException(422, "Choose 3, 10, or 30 tracks")
    batch_id = "lyria_" + uuid4().hex
    ref = _batch_ref(batch_id)
    plan = []
    for category, choices in CATEGORIES:
        for title, instruments, bpm in choices:
            index = len(plan) + 1
            prompt = (f"Generate a 30-second original instrumental background soundtrack titled '{title}'. "
                      f"Mood/category: {category}. Tempo approximately {bpm} BPM. "
                      f"Primary instruments: {instruments}. Narration-friendly arrangement, moderate loudness, "
                      "immediate introduction, clear musical resolution. Instrumental only, no vocals, "
                      "no lyrics or speech. Do not imitate any existing song, melody, or named performer.")
            plan.append({"index": index, "title": title, "category": category, "bpm": bpm,
                         "prompt": prompt, "status": "PENDING", "track_id": None})
    now = _now()
    ref.create({"batch_id": batch_id, "model": MODEL, "count": count, "created_by": uid,
                "created_at": now, "estimated_unit_cost_usd": ESTIMATED_USD,
                "estimated_max_cost_usd": round(count * ESTIMATED_USD, 2), "status": "PENDING"})
    for entry in plan[:count]:
        ref.collection("tracks").document(f"{entry['index']:03}").create(entry)
    return get_batch(batch_id)


def _claim_next(batch_id: str):
    ref = _batch_ref(batch_id)
    if not ref.get().exists:
        raise HTTPException(404, "Music batch not found")
    db = get_runtime_firestore_client()
    # Resolve references outside the transaction; read every track INSIDE the
    # transaction so an unresolved attempt blocks new paid calls server-side.
    references = list(ref.collection("tracks").list_documents())
    references.sort(key=lambda item: item.id)
    if not references:
        raise HTTPException(409, "Batch has no tracks")

    tx = db.transaction()

    @firestore.transactional
    def claim(transaction):
        snapshots = list(db.get_all(references, transaction=transaction))
        records = [(snap.reference, snap.to_dict() or {}) for snap in snapshots if snap.exists]
        if any(record.get("status") in ("RUNNING", "NEEDS_ATTENTION") for _, record in records):
            raise HTTPException(409, "Resolve the interrupted or failed track before starting another paid generation")
        for document, record in records:
            if record.get("status") == "PENDING":
                attempt = uuid4().hex
                transaction.update(document, {"status": "RUNNING", "attempt_id": attempt, "started_at": _now()})
                return (document, record, attempt)
        raise HTTPException(409, "No pending tracks")

    return claim(tx)


def skip_failed_track(batch_id: str, index: int, uid: str, reason: str):
    """Acknowledge a failed attempt without ever calling the paid provider.

    SKIPPED is terminal for this attempt, not a retry. Keep the original
    attempt ID/error and store an immutable resolution event separately.
    """
    reason = reason.strip()
    if not 12 <= len(reason) <= 1000:
        raise HTTPException(422, "Provide an investigation reason of 12 to 1000 characters")
    if index < 1 or index > 30:
        raise HTTPException(422, "Invalid track index")
    ref = _batch_ref(batch_id)
    doc = ref.collection("tracks").document(f"{index:03d}")
    db = get_runtime_firestore_client()
    tx = db.transaction()

    @firestore.transactional
    def resolve(transaction):
        batch_snap = ref.get(transaction=transaction)
        if not batch_snap.exists:
            raise HTTPException(404, "Music batch not found")
        snap = doc.get(transaction=transaction)
        if not snap.exists:
            raise HTTPException(404, "Batch track not found")
        record = snap.to_dict() or {}
        if record.get("status") != "NEEDS_ATTENTION":
            raise HTTPException(409, "Only a track marked NEEDS_ATTENTION can be skipped")
        if record.get("track_id") or record.get("possible_storage_key") or record.get("diagnostic_storage_key"):
            raise HTTPException(409, "Saved media may exist. Reconcile the storage artifact before skipping")
        attempt_id = record.get("attempt_id")
        if not attempt_id:
            raise HTTPException(409, "Missing original attempt ID; manual investigation required")
        now = _now()
        event = ref.collection("recovery_events").document(attempt_id)
        transaction.create(event, {
            "action": "SKIP_AFTER_INVESTIGATION", "track_index": index,
            "original_attempt_id": attempt_id, "original_error": record.get("error", ""),
            "actor_uid": uid, "reason": reason, "created_at": now,
            "possible_provider_charge": True,
        })
        transaction.update(doc, {
            "status": "SKIPPED", "resolved_at": now, "resolved_by": uid,
            "resolution_reason": reason, "possible_provider_charge": True,
            "updated_at": now,
        })

    resolve(tx)
    return get_batch(batch_id)


def _extract_audio(response):
    """Accept only audio inline parts, never lyrics/JSON or arbitrary binary parts."""
    parts = list(getattr(response, "parts", None) or [])
    if not parts:
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            parts.extend(getattr(content, "parts", None) or [])
    seen = []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline is None:
            continue
        mime = str(getattr(inline, "mime_type", "") or "").split(";", 1)[0].lower().strip()
        raw = getattr(inline, "data", None)
        seen.append(mime or "unknown")
        if not mime.startswith("audio/") or not raw:
            continue
        if isinstance(raw, str):
            try:
                raw = base64.b64decode(raw, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise RuntimeError("Provider supplied invalid base64 audio data") from exc
        if isinstance(raw, (bytes, bytearray)) and raw:
            return bytes(raw), mime
    raise RuntimeError("No audio part returned by provider; inline MIME types: " + ", ".join(seen[:8]))


def _normalize_mp3(audio: bytes, mime: str) -> bytes:
    """Decode the actual input bytes and always produce a valid MP3 for the catalog."""
    import imageio_ffmpeg
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory(prefix="revai_lyria_") as work:
        source = os.path.join(work, "provider_audio")
        target = os.path.join(work, "validated.mp3")
        with open(source, "wb") as f:
            f.write(audio)
        cmd = [executable, "-hide_banner", "-nostdin", "-v", "error", "-y",
               "-i", source, "-map", "0:a:0", "-vn", "-codec:a", "libmp3lame",
               "-b:a", "192k", target]
        try:
            completed = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FFmpeg audio conversion timed out") from exc
        if completed.returncode != 0 or not os.path.isfile(target) or os.path.getsize(target) == 0:
            details = completed.stderr.decode("utf-8", errors="replace").strip()
            # Avoid logging remote text bodies or secrets; only a bounded ffmpeg diagnostic.
            raise RuntimeError("Generated audio decode failed (MIME " + mime + "): " + details[-450:])
        _validate_audio(target)
        with open(target, "rb") as f:
            return f.read()


def generate_next(batch_id: str):
    # Only explicit administrator action initiates each paid provider call.
    # Historical NEEDS_ATTENTION tracks are never reclaimed or retried here.
    if not os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
        raise HTTPException(503, "Set GEMINI_API_KEY in the backend secret environment to enable Lyria generation")
    doc_ref, plan, attempt = _claim_next(batch_id)
    stored_key = None
    provider_audio = None
    mime = None
    try:
        from google import genai
        client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])
        response = client.models.generate_content(model=MODEL, contents=plan["prompt"])
        provider_audio, mime = _extract_audio(response)
        if len(provider_audio) > 25 * 1024 * 1024:
            raise RuntimeError("Provider audio exceeded 25 MB limit")
        provider_hash = hashlib.sha256(provider_audio).hexdigest()
        doc_ref.update({"provider_response_received": True, "provider_audio_mime": mime,
                        "provider_audio_size_bytes": len(provider_audio),
                        "provider_audio_sha256": provider_hash, "updated_at": _now()})
        try:
            audio = _normalize_mp3(provider_audio, mime)
        except Exception:
            # Preserve non-public raw provider output for manual investigation; never
            # surface it through the published soundtrack endpoints.
            try:
                bucket, prefix = _bucket()
                quarantine = "/".join(filter(None, [prefix, "lyria-diagnostics", batch_id, attempt, "provider_audio.bin"]))
                bucket.blob(quarantine).upload_from_string(
                    provider_audio, content_type="application/octet-stream", if_generation_match=0)
                doc_ref.update({"diagnostic_storage_key": quarantine})
            except Exception:
                logger.exception("Unable to preserve Lyria diagnostic audio for batch %s attempt %s", batch_id, attempt)
            raise
        bucket, prefix = _bucket()
        track_id = "platform_" + uuid4().hex
        stored_key = "/".join(filter(None, [prefix, "platform", track_id, "original.mp3"]))
        bucket.blob(stored_key).upload_from_string(audio, content_type="audio/mpeg", if_generation_match=0)
        with tempfile.NamedTemporaryFile(suffix=".mp3") as measured:
            measured.write(audio)
            measured.flush()
            duration_seconds = _probe_duration(measured.name)
        now = _now()
        track_ref = get_runtime_firestore_client().collection(COLLECTION).document(track_id)
        track_ref.create({"track_id": track_id, "title": plan["title"], "artist": "ReviveAI · Google Lyria",
                          "license_name": "AI-generated; rights review required", "license_evidence": "",
                          "attribution": "", "status": "DRAFT", "owner_type": "PLATFORM",
                          "source": "GOOGLE_LYRIA", "model": MODEL, "prompt": plan["prompt"],
                          "batch_id": batch_id, "generation_attempt_id": attempt,
                          "storage_key": stored_key, "content_type": "audio/mpeg",
                          "size_bytes": len(audio), "sha256": hashlib.sha256(audio).hexdigest(),
                          "duration_seconds": duration_seconds, "mood": plan["category"],
                          "requested_bpm": plan["bpm"], "generation_cost_estimated_usd": ESTIMATED_USD,
                          "generation_cost_status": "ESTIMATED_NOT_BILLED",
                          "provider_audio_mime": mime, "provider_audio_sha256": provider_hash,
                          "created_at": now, "updated_at": now})
        doc_ref.update({"status": "DRAFT", "track_id": track_id, "completed_at": now})
        return get_batch(batch_id)
    except Exception as exc:
        logger.exception("Lyria processing needs attention; batch=%s attempt=%s", batch_id, attempt)
        doc_ref.update({"status": "NEEDS_ATTENTION", "error": str(exc)[:350], "updated_at": _now(),
                        "possible_storage_key": stored_key})
        raise HTTPException(502, "Generation needs attention. This track will not be automatically retried; inspect its state and provider usage.") from exc
