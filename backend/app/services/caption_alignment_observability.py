"""Non-mutating caption aligner diagnostic for the active Autopilot audio job.

Only temporary files are written. Never creates jobs, captions, publications or state.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time
import wave
from pathlib import Path
from uuid import uuid4

from app.models.audio_finishing import AudioFinishingJobStage
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.audio_finishing_job_service import _ffmpeg_executable, _run
from app.services.autopilot_state_service import autopilot_state_store
from app.services.remote_forced_alignment import force_align_voice_wav

logger = logging.getLogger(__name__)


class AlignmentDiagnosticError(Exception):
    def __init__(self, stage: str, code: str):
        self.stage = stage
        self.code = code
        super().__init__(code)


def _failure_code(exc: Exception) -> str:
    """Safe categorical result: never return exception text, GCS URI or tokens."""
    from requests.exceptions import HTTPError, RequestException
    from google.auth.exceptions import GoogleAuthError
    if isinstance(exc, HTTPError):
        status = exc.response.status_code if exc.response is not None else 0
        return f"WORKER_HTTP_{status}" if status in (400, 401, 403, 404, 408, 413, 422, 429, 500, 502, 503, 504) else "WORKER_HTTP_ERROR"
    if isinstance(exc, GoogleAuthError):
        return "IDENTITY_TOKEN_ERROR"
    if isinstance(exc, RequestException):
        return "WORKER_NETWORK_ERROR"
    if isinstance(exc, ValueError):
        return "ALIGNMENT_VALIDATION_ERROR"
    return "INTERNAL_DIAGNOSTIC_ERROR"


def diagnose_active_caption_alignment(shot_number: int = 1) -> dict:
    diagnostic_id = f"align_diag_{uuid4().hex[:16]}"
    started = time.monotonic()
    stage = "lineage"
    job_id = None
    info = {"diagnostic_id": diagnostic_id, "status": "FAILED", "stage": stage,
            "shot_number": shot_number, "audio_job_id": None, "read_only": True,
            "assets_mutated": False, "recovery_attempts_consumed": False}
    try:
        if not 1 <= shot_number <= 30:
            raise AlignmentDiagnosticError(stage, "INVALID_SHOT_NUMBER")
        record = autopilot_state_store.get()
        if record is None or record.session.status != "NEEDS_ATTENTION":
            raise AlignmentDiagnosticError(stage, "AUTOPILOT_NOT_PAUSED")
        session = record.session
        if session.currentDeliveryPackageId or session.currentPublicationId:
            raise AlignmentDiagnosticError(stage, "PRODUCTION_ALREADY_ADVANCED")
        job_id = session.currentAudioJobId
        if not job_id:
            raise AlignmentDiagnosticError(stage, "AUDIO_JOB_MISSING")
        source = audio_finishing_job_store.get(job_id)
        if source.stage != AudioFinishingJobStage.DELIVERED or source.result is None:
            raise AlignmentDiagnosticError(stage, "SOURCE_NOT_DELIVERED")
        matching = [item for item in source.result.voiceover_cues if item.shot_number == shot_number and item.text.strip()]
        stems = (source.detail or {}).get("narration_stems") or []
        stems_matching = [stem for stem in stems if int(stem.get("shot_number", -1)) == shot_number]
        if len(matching) != 1 or len(stems_matching) != 1:
            raise AlignmentDiagnosticError(stage, "NARRATION_LINEAGE_INCOMPLETE")
        voice, stem = matching[0], stems_matching[0]
        if not stem.get("gcs_uri") or not stem.get("filename"):
            raise AlignmentDiagnosticError(stage, "STEM_LOCATION_MISSING")
        info["audio_job_id"] = job_id
        info["state_revision"] = record.revision
        info["worker_url_configured"] = bool(os.getenv("REVIVEAI_FORCED_ALIGN_URL", "").startswith("https://"))
        with tempfile.TemporaryDirectory(prefix="reviveai-align-diag-") as folder:
            raw = Path(folder) / "source.wav"
            normalized = Path(folder) / "normalized.wav"
            stage = "gcs_download"
            audio_finishing_job_store._artifacts.ensure_local(
                raw, owner_id=job_id, relative_path=f"assets/{stem['filename']}", gcs_uri=stem['gcs_uri']
            )
            if not raw.is_file():
                raise AlignmentDiagnosticError(stage, "STEM_NOT_ACCESSIBLE")
            info["stem_bytes"] = raw.stat().st_size
            stage = "normalization"
            _run([_ffmpeg_executable(), "-y", "-i", str(raw), "-ac", "1", "-ar", "16000",
                  "-c:a", "pcm_s16le", str(normalized)])
            with wave.open(str(normalized), "rb") as wav:
                info["normalized_channels"] = wav.getnchannels()
                info["normalized_hz"] = wav.getframerate()
                info["normalized_width_bytes"] = wav.getsampwidth()
                info["duration_seconds"] = round(wav.getnframes() / wav.getframerate(), 3)
            stage = "forced_alignment"
            cues, report = force_align_voice_wav(normalized, voice.text)
            info["alignment"] = {
                "method": report.get("method"),
                "worker_model": report.get("worker_model"),
                "recognized_words": report.get("recognized_words"),
                "transcript_match_ratio": report.get("transcript_match_ratio"),
                "timestamps_valid": report.get("timestamps_valid"),
                "cue_count": len(cues),
            }
        info.update(status="PASSED", stage="complete")
    except AlignmentDiagnosticError as exc:
        info.update(stage=exc.stage, error_code=exc.code)
    except Exception as exc:
        info.update(stage=stage, error_code=_failure_code(exc))
        logger.warning("caption_alignment_diagnostic_failure id=%s stage=%s type=%s", diagnostic_id, stage, type(exc).__name__)
    info["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    logger.info("caption_alignment_diagnostic id=%s status=%s stage=%s code=%s job=%s",
                diagnostic_id, info["status"], info["stage"], info.get("error_code", "OK"), job_id)
    return info
