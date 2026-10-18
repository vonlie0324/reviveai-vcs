from __future__ import annotations

import re

import hashlib
import json
import logging
import time
import shutil
import subprocess
import wave
from datetime import datetime, timezone, timedelta
from pathlib import Path
from app.services.cloud_storage_service import CloudStorageService
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace
from app.services.narration_alignment import split_phrases, ssml_with_marks, timed_phrases, write_srt
from app.services.speech_verified_alignment import align_voice_wav
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.audio_finishing import (
    AudioFinishingJob,
    AudioFinishingJobStage,
    AudioFinishingResult,
    AudioFinishingReviewStatus,
    AudioLayerSummary,
    BackgroundMusicPreset,
    MusicSource,
    AudioMixOptions,
    VoiceoverCue,
)
from app.models.final_assembly import AssemblyAsset, AssemblyAssetKind, FinalAssemblyJobStage, FinalAssemblyReviewStatus
from app.services.final_assembly_job_service import final_assembly_job_store
from app.services.production_brief_job_service import production_brief_job_store
from app.services.trending_music_service import TrendingMusicCatalogError, TrendingMusicTrackNotFoundError, trending_music_catalog
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.runtime_artifact_store import RuntimeArtifactStore
from app.services.youtube_audio_library_service import (
    YouTubeAudioLibraryError,
    YouTubeAudioLibraryTrackNotFoundError,
    youtube_audio_library,
)

logger = logging.getLogger(__name__)


class AudioFinishingJobNotFoundError(KeyError):
    pass


class AudioFinishingError(RuntimeError):
    pass


class AudioFinishingJobStore:
    """Audio Finishing jobs with Firestore metadata and GCS artifact durability."""

    def __init__(self, checkpoint_root: str):
        self._jobs: TenantScopedDict[str, AudioFinishingJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "audio_finishing"
        self.cloud_storage = CloudStorageService(get_settings().soundtrack_output_gcs_uri)
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("audio_finishing_jobs")
        self._artifacts = RuntimeArtifactStore("audio_finishing")

    def _job_dir(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / job_id

    def assets_dir(self, job_id: str) -> Path:
        path = self._job_dir(job_id) / "assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def work_dir(self, job_id: str) -> Path:
        path = self._job_dir(job_id) / "work"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[AudioFinishingJob]:
        if not payload:
            return None
        try:
            return AudioFinishingJob.model_validate(payload)
        except Exception:
            return None

    def _sync_artifacts(self, job: AudioFinishingJob) -> None:
        if not job.result:
            return
        assets = [job.result.delivery_video]
        if job.result.audio_mix:
            assets.append(job.result.audio_mix)
        if job.result.subtitles:
            assets.append(job.result.subtitles)
        for asset in assets:
            path = self.assets_dir(job.job_id) / asset.filename
            if not path.exists():
                # A durable MUX_READY checkpoint intentionally references the yet-to-be
                # created delivery video. Never accept a missing mix or subtitle.
                pending_mux = (job.stage in {AudioFinishingJobStage.RENDERING, AudioFinishingJobStage.FAILED}
                    and (job.detail or {}).get("render_checkpoint", {}).get("state") == "MUX_READY"
                    and asset.asset_id == job.result.delivery_video.asset_id)
                if pending_mux or asset.gcs_uri:
                    continue
                raise FileNotFoundError(f"Audio Finishing artifact is missing from the local cache: {asset.filename}")
            uri = self._artifacts.upload_file_create_only(
                path, owner_id=job.job_id, relative_path=f"assets/{asset.filename}", content_type=asset.mime_type
            )
            if uri:
                asset.gcs_uri = uri

    def _persist_local(self, job: AudioFinishingJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, job: AudioFinishingJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: AudioFinishingJob) -> None:
        artifact_error: Exception | None = None
        cloud_error: Exception | None = None
        try:
            self._sync_artifacts(job)
        except Exception as exc:
            artifact_error = exc
            logger.exception("Could not mirror Audio Finishing artifacts for %s to GCS", job.job_id)
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Audio Finishing job %s to Firestore", job.job_id)
        self._persist_local(job)
        if get_settings().app_env.strip().lower() in {"production", "prod"}:
            if artifact_error is not None:
                raise RuntimeError("Durable GCS artifact persistence failed for the Audio Finishing job") from artifact_error
            if cloud_error is not None:
                raise RuntimeError("Durable Firestore persistence failed for the Audio Finishing job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[AudioFinishingJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read Audio Finishing job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[AudioFinishingJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return AudioFinishingJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load local Audio Finishing checkpoint %s", job_id)
            return None

    def _backfill_cloud(self, job: AudioFinishingJob) -> None:
        try:
            self._sync_artifacts(job)
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill Audio Finishing job %s to cloud persistence", job.job_id)

    def _load(self, job_id: str) -> Optional[AudioFinishingJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud
        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    def create(self, assembly_job_id: str, options: AudioMixOptions) -> AudioFinishingJob:
        assembly_job = final_assembly_job_store.get(assembly_job_id)
        if (
            assembly_job.stage != FinalAssemblyJobStage.DELIVERED
            or not assembly_job.result
            or assembly_job.result.review_status != FinalAssemblyReviewStatus.APPROVED
        ):
            raise ValueError("The visual master must pass review before starting M2C.2 audio finishing.")

        existing = self.list_for_assembly_job(assembly_job_id)
        running = next((item for item in existing if item.stage in {
            AudioFinishingJobStage.QUEUED,
            AudioFinishingJobStage.PREPARING,
            AudioFinishingJobStage.SYNTHESIZING_VOICE,
            AudioFinishingJobStage.BUILDING_MIX,
            AudioFinishingJobStage.RENDERING,
        }), None)
        if running:
            raise ValueError(f"Audio master v{running.version_number} is already being created.")

        previous = existing[0] if existing else None
        version_number = max((item.version_number for item in existing), default=0) + 1
        now = datetime.now(timezone.utc)
        job = AudioFinishingJob(
            job_id=f"audio_{uuid4().hex}",
            assembly_job_id=assembly_job_id,
            production_brief_job_id=assembly_job.production_brief_job_id,
            media_job_id=assembly_job.media_job_id,
            channel_id=assembly_job.channel_id,
            version_number=version_number,
            based_on_job_id=previous.job_id if previous else None,
            stage=AudioFinishingJobStage.QUEUED,
            message=f"Audio master v{version_number} queued",
            progress_current=0,
            progress_total=5,
            created_at=now,
            updated_at=now,
            options=options,
            detail={
                "visual_master_preserved": True,
                "audio_only_regeneration": previous is not None,
                "source_visual_asset_id": assembly_job.result.final_video.asset_id,
            },
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> AudioFinishingJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None:
                raise AudioFinishingJobNotFoundError(job_id)
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def list_for_assembly_job(self, assembly_job_id: str) -> list[AudioFinishingJob]:
        candidates: Dict[str, AudioFinishingJob] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.assembly_job_id == assembly_job_id:
                    candidates[loaded.job_id] = loaded
        except Exception:
            logger.exception("Could not list Audio Finishing jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("*/job.json"):
            loaded = self._load_local(path.parent.name)
            if loaded and loaded.assembly_job_id == assembly_job_id:
                candidates[loaded.job_id] = loaded
                if self._load_cloud(loaded.job_id) is None:
                    self._backfill_cloud(loaded)

        with self._lock:
            for item in self._jobs.values():
                if item.assembly_job_id == assembly_job_id:
                    candidates[item.job_id] = item.model_copy(deep=True)
        return sorted(
            candidates.values(),
            key=lambda item: (item.version_number, item.created_at, item.job_id),
            reverse=True,
        )

    def list_for_channel(self, channel_id: str) -> list[AudioFinishingJob]:
        """Return durable Audio Finishing history for one channel, newest first."""
        channel_id = (channel_id or "").strip()
        if not channel_id:
            return []

        candidates: Dict[str, AudioFinishingJob] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.channel_id == channel_id:
                    candidates[loaded.job_id] = loaded
        except Exception:
            logger.exception("Could not list channel Audio Finishing jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("*/job.json"):
            loaded = self._load_local(path.parent.name)
            if loaded and loaded.channel_id == channel_id:
                candidates[loaded.job_id] = loaded
                if self._load_cloud(loaded.job_id) is None:
                    self._backfill_cloud(loaded)

        with self._lock:
            for item in self._jobs.values():
                if item.channel_id == channel_id:
                    candidates[item.job_id] = item.model_copy(deep=True)

        return sorted(
            candidates.values(),
            key=lambda item: (item.updated_at, item.created_at, item.job_id),
            reverse=True,
        )

    def latest_for_assembly_job(self, assembly_job_id: str) -> Optional[AudioFinishingJob]:
        items = self.list_for_assembly_job(assembly_job_id)
        return items[0] if items else None

    def save(self, job: AudioFinishingJob) -> None:
        job.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)

    def fail(self, job_id: str, message: str) -> None:
        job = self.get(job_id)
        job.stage = AudioFinishingJobStage.FAILED
        job.message = "Audio finishing paused"
        job.error = message
        self.save(job)

    def approve(
        self,
        job_id: str,
        *,
        actor: str = "HUMAN",
        review_summary: Optional[str] = None,
    ) -> AudioFinishingJob:
        job = self.get(job_id)
        if job.stage != AudioFinishingJobStage.COMPLETED or not job.result:
            raise ValueError("Build the audio-finished delivery master before approving it.")
        if job.result.options.voiceover_enabled:
            missing = [cue.shot_number for cue in job.result.voiceover_cues if cue.text.strip() and not cue.synthesized]
            if missing:
                raise ValueError(
                    "Required voiceover was not synthesized for shot(s) "
                    + ", ".join(map(str, missing))
                    + ". Repair audio finishing before approval."
                )
        actor = (actor or "HUMAN").upper()
        job.result.review_status = AudioFinishingReviewStatus.APPROVED
        job.result.reviewed_at = datetime.now(timezone.utc)
        job.stage = AudioFinishingJobStage.DELIVERED
        job.detail = {
            **job.detail,
            "approval_actor": actor,
            "approval_review_summary": review_summary,
            "human_final_approved": bool(job.detail.get("human_final_approved", False)),
        }
        job.message = (
            f"Audio master v{job.version_number} AI-reviewed and ready for delivery QC"
            if actor == "AI"
            else f"Audio master v{job.version_number} human-approved"
        )
        self.save(job)
        return self.get(job_id)

    def asset_path(self, job_id: str, asset_id: str) -> tuple[Path, str]:
        job = self.get(job_id)
        if not job.result:
            raise AudioFinishingJobNotFoundError(asset_id)
        assets = [job.result.delivery_video]
        if job.result.audio_mix:
            assets.append(job.result.audio_mix)
        if job.result.subtitles:
            assets.append(job.result.subtitles)
        asset = next((item for item in assets if item.asset_id == asset_id), None)
        if not asset:
            raise AudioFinishingJobNotFoundError(asset_id)
        path = self.assets_dir(job_id) / asset.filename
        if not path.exists():
            self._artifacts.ensure_local(
                path, owner_id=job_id, relative_path=f"assets/{asset.filename}", gcs_uri=asset.gcs_uri
            )
        if not path.exists():
            raise AudioFinishingJobNotFoundError(asset_id)
        return path, asset.mime_type


audio_finishing_job_store = AudioFinishingJobStore(get_settings().content_dna_checkpoint_dir)


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise AudioFinishingError("M2C.2 requires imageio-ffmpeg. Run pip install -r requirements.txt.") from exc


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-2200:]
        raise AudioFinishingError(f"FFmpeg could not finish the audio master. {tail}")


def _ambience_profile(audio_direction: str) -> str:
    text = (audio_direction or "").lower()
    if any(token in text for token in ("airplane", "aircraft", "cabin", "flight", "seatbelt")):
        return "CABIN"
    if any(token in text for token in ("bakery", "kitchen", "cafe", "restaurant", "cooking")):
        return "KITCHEN"
    if any(token in text for token in ("party", "celebration", "wedding")):
        return "CELEBRATION"
    return "ROOM"


def _voice_text_for_shot(item) -> str:
    dialogue = (item.voiceover_or_dialogue or "").strip()
    on_screen = (item.on_screen_text or "").strip()
    max_words = max(4, int(item.output_duration_seconds * 2.1))
    if dialogue and len(dialogue.split()) <= max_words:
        return dialogue
    if on_screen and len(on_screen.split()) <= max_words + 2:
        return on_screen
    return ""


def _synthesize_tts(text: str, destination: Path, settings: Settings, voice_name: Optional[str] = None) -> tuple[list, dict[str, float]]:
    """Synthesize narration and request actual phrase-boundary timepoints.

    When a voice/provider rejects SSML marks, synthesize the same text normally,
    returning empty timepoints so callers never mislabel estimates as aligned.
    """
    try:
        from google.cloud import texttospeech_v1beta1 as texttospeech
        from google.api_core import exceptions as google_errors
    except ImportError as exc:
        raise AudioFinishingError(
            "Google Cloud TTS Python client is missing. Install google-cloud-texttospeech in requirements.txt."
        ) from exc

    client = texttospeech.TextToSpeechClient()
    phrases = split_phrases(text)
    transient_errors = (
        google_errors.ServiceUnavailable, google_errors.DeadlineExceeded,
        google_errors.TooManyRequests, google_errors.InternalServerError,
    )
    for attempt in range(1, 4):
        try:
            voice = texttospeech.VoiceSelectionParams(
                language_code=settings.audio_tts_language_code,
                name=voice_name or settings.audio_tts_voice,
            )
            config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
            # Different google-cloud-texttospeech releases expose SSML timepoint
            # support differently. A missing enum must never prevent narration.
            # Always pass a request object: the client method does not accept
            # enable_time_pointing as a top-level keyword argument.
            request_type = texttospeech.SynthesizeSpeechRequest
            timepoint_enum = getattr(request_type, "TimepointType", None)
            ssml_mark = getattr(timepoint_enum, "SSML_MARK", None) if timepoint_enum is not None else None
            if ssml_mark is None:
                logger.info("TTS SDK lacks SSML timepoint support; synthesizing plain narration")
                response = client.synthesize_speech(
                    request=request_type(
                        input=texttospeech.SynthesisInput(text=text),
                        voice=voice,
                        audio_config=config,
                    ),
                    timeout=30,
                )
                marks = {}
            else:
                try:
                    marked_request = request_type(
                        input=texttospeech.SynthesisInput(ssml=ssml_with_marks(phrases)),
                        voice=voice,
                        audio_config=config,
                        enable_time_pointing=[ssml_mark],
                    )
                    response = client.synthesize_speech(request=marked_request, timeout=30)
                    marks = {tp.mark_name: float(tp.time_seconds) for tp in response.timepoints}
                except (google_errors.InvalidArgument, google_errors.FailedPrecondition, TypeError, ValueError) as exc:
                    logger.warning("TTS marked SSML unavailable: %s; synthesizing plain narration", exc)
                    response = client.synthesize_speech(
                        request=request_type(
                            input=texttospeech.SynthesisInput(text=text),
                            voice=voice,
                            audio_config=config,
                        ),
                        timeout=30,
                    )
                    marks = {}
            if not response.audio_content:
                raise AudioFinishingError("Google Cloud TTS returned empty audio content.")
            destination.write_bytes(response.audio_content)
            return phrases, marks
        except transient_errors as exc:
            logger.warning("Google TTS transient failure attempt %s/3: %s", attempt, exc)
            if attempt == 3:
                raise AudioFinishingError(f"Google Cloud TTS failed after 3 attempts: {type(exc).__name__}: {exc}") from exc
            time.sleep(2 ** (attempt - 1))
        except Exception as exc:
            raise AudioFinishingError(f"Google Cloud TTS failed: {type(exc).__name__}: {exc}") from exc


def _make_silence(ffmpeg: str, destination: Path, duration: float) -> None:
    _run([
        ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{duration:.3f}", "-c:a", "pcm_s16le", str(destination.resolve()),
    ])


def _measured_voice_duration(ffmpeg: str, source: Path) -> float:
    """Decode source to PCM and measure samples, not estimated MP3 metadata."""
    pcm = source.with_name(source.stem + "-duration-check.wav")
    try:
        _run([ffmpeg, "-y", "-i", str(source.resolve()), "-vn", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(pcm.resolve())])
        with wave.open(str(pcm), "rb") as stream:
            return stream.getnframes() / stream.getframerate()
    finally:
        pcm.unlink(missing_ok=True)


def _fit_voice_segment(ffmpeg: str, source: Path, destination: Path, duration: float) -> dict:
    """Never silently clip narration. Permit at most 12% tempo increase."""
    spoken = _measured_voice_duration(ffmpeg, source)
    # A small fixed pause before the next shot reduces boundary clipping.
    usable = max(0.1, duration - 0.15)
    ratio = spoken / usable
    if ratio > 1.12:
        raise AudioFinishingError(
            f"Narration duration {spoken:.2f}s exceeds usable shot duration {usable:.2f}s "
            f"(requires {ratio:.2f}x tempo; maximum permitted 1.12x). "
            "Shorten the narration for this shot; do not trim spoken words."
        )
    tempo = max(1.0, ratio)
    _run([
        ffmpeg, "-y", "-i", str(source.resolve()),
        "-af", f"atempo={tempo:.5f},apad,atrim=0:{duration:.3f},afade=t=out:st={max(0.0, duration - 0.12):.3f}:d=0.12",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination.resolve()),
    ])
    return {"measured_duration_seconds": round(spoken, 3), "shot_duration_seconds": round(duration, 3), "tempo": round(tempo, 4)}


def _normalize_voice_segment(ffmpeg: str, source: Path, destination: Path, duration: float) -> None:
    _run([
        ffmpeg, "-y", "-i", str(source.resolve()),
        "-af", f"apad,atrim=0:{duration:.3f},afade=t=out:st={max(0.0, duration - 0.12):.3f}:d=0.12",
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination.resolve()),
    ])


def _concat_audio(ffmpeg: str, sources: list[Path], destination: Path, work_dir: Path) -> None:
    manifest = work_dir / "voice-concat.txt"
    lines = []
    for source in sources:
        rel = source.resolve().relative_to(work_dir.resolve()).as_posix().replace("'", "'\\''")
        lines.append(f"file '{rel}'")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _run([
        ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(manifest.resolve()),
        "-c:a", "pcm_s16le", str(destination.resolve()),
    ])


MUSIC_PRESET_LABELS: dict[BackgroundMusicPreset, str] = {
    BackgroundMusicPreset.AUTO: "Auto match",
    BackgroundMusicPreset.CINEMATIC_AMBIENT: "Cinematic ambient",
    BackgroundMusicPreset.WARM_INSPIRATIONAL: "Warm inspirational",
    BackgroundMusicPreset.MODERN_PULSE: "Modern pulse",
    BackgroundMusicPreset.REFLECTIVE: "Reflective",
    BackgroundMusicPreset.BRIGHT_UPBEAT: "Bright upbeat",
}


def _resolve_music_preset(requested: BackgroundMusicPreset, audio_direction: str) -> BackgroundMusicPreset:
    if requested != BackgroundMusicPreset.AUTO:
        return requested

    direction = (audio_direction or "").lower()
    if any(word in direction for word in ("celebration", "festive", "upbeat", "bright", "playful", "happy")):
        return BackgroundMusicPreset.BRIGHT_UPBEAT
    if any(word in direction for word in ("reflective", "calm", "quiet", "gentle", "emotional", "intimate", "soft")):
        return BackgroundMusicPreset.REFLECTIVE
    if any(word in direction for word in ("pulse", "energetic", "rhythmic", "modern", "tech", "digital", "driving")):
        return BackgroundMusicPreset.MODERN_PULSE
    if any(word in direction for word in ("warm", "inspiring", "inspirational", "uplifting", "hopeful", "optimistic")):
        return BackgroundMusicPreset.WARM_INSPIRATIONAL
    return BackgroundMusicPreset.CINEMATIC_AMBIENT


def _music_preset_spec(preset: BackgroundMusicPreset) -> tuple[list[tuple[float, float]], str]:
    if preset == BackgroundMusicPreset.WARM_INSPIRATIONAL:
        return (
            [(220.00, 0.22), (277.18, 0.17), (329.63, 0.14), (440.00, 0.08)],
            "tremolo=f=0.45:d=0.22,lowpass=f=2800",
        )
    if preset == BackgroundMusicPreset.MODERN_PULSE:
        return (
            [(110.00, 0.25), (220.00, 0.14), (329.63, 0.10)],
            "tremolo=f=2.2:d=0.72,highpass=f=65,lowpass=f=2400",
        )
    if preset == BackgroundMusicPreset.REFLECTIVE:
        return (
            [(196.00, 0.16), (246.94, 0.12), (293.66, 0.10), (392.00, 0.05)],
            "tremolo=f=0.20:d=0.16,aecho=0.8:0.35:180|360:0.08|0.05,lowpass=f=2100",
        )
    if preset == BackgroundMusicPreset.BRIGHT_UPBEAT:
        return (
            [(261.63, 0.18), (329.63, 0.15), (392.00, 0.12), (523.25, 0.07)],
            "tremolo=f=3.0:d=0.48,highpass=f=120,lowpass=f=3200",
        )
    return (
        [(174.61, 0.22), (220.00, 0.17), (261.63, 0.12)],
        "aecho=0.8:0.40:140|280:0.08|0.05,lowpass=f=1900",
    )


def _generate_music_bed(
    ffmpeg: str,
    destination: Path,
    duration: float,
    preset: BackgroundMusicPreset = BackgroundMusicPreset.CINEMATIC_AMBIENT,
) -> None:
    if preset == BackgroundMusicPreset.AUTO:
        preset = BackgroundMusicPreset.CINEMATIC_AMBIENT
    tones, post_filter = _music_preset_spec(preset)
    command = [ffmpeg, "-y"]
    for frequency, _ in tones:
        command.extend([
            "-f", "lavfi", "-i",
            f"sine=frequency={frequency:.2f}:duration={duration:.3f}:sample_rate=44100",
        ])
    chains: list[str] = []
    labels: list[str] = []
    for index, (_, level) in enumerate(tones):
        label = f"m{index}"
        chains.append(f"[{index}:a]volume={level:.4f}[{label}]")
        labels.append(f"[{label}]")
    chains.append(
        f"{''.join(labels)}amix=inputs={len(tones)}:normalize=0,{post_filter},"
        f"afade=t=in:st=0:d=0.6,afade=t=out:st={max(0.0, duration-0.8):.3f}:d=0.8,"
        "loudnorm=I=-23:TP=-3:LRA=7,pan=stereo|c0=c0|c1=c0[out]"
    )
    command.extend([
        "-filter_complex", ";".join(chains),
        "-map", "[out]", "-ar", "44100", "-ac", "2",
        "-c:a", "pcm_s16le", str(destination.resolve()),
    ])
    _run(command)


def _prepare_trending_music_bed(
    ffmpeg: str,
    source: Path,
    destination: Path,
    duration: float,
) -> None:
    fade_out_start = max(0.0, duration - 0.8)
    _run([
        ffmpeg, "-y", "-stream_loop", "-1", "-i", str(source.resolve()),
        "-t", f"{duration:.3f}", "-vn",
        "-af", (
            "aformat=sample_rates=44100:channel_layouts=stereo,"
            "loudnorm=I=-23:TP=-3:LRA=7,"
            "afade=t=in:st=0:d=0.35,"
            f"afade=t=out:st={fade_out_start:.3f}:d=0.8"
        ),
        "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(destination.resolve()),
    ])


def build_music_preview(
    assembly_job_id: str,
    requested: BackgroundMusicPreset,
    settings: Settings,
    duration_seconds: float = 8.0,
) -> tuple[Path, BackgroundMusicPreset]:
    assembly_job = final_assembly_job_store.get(assembly_job_id)
    if (
        assembly_job.stage != FinalAssemblyJobStage.DELIVERED
        or not assembly_job.result
        or assembly_job.result.review_status != FinalAssemblyReviewStatus.APPROVED
    ):
        raise ValueError("The visual master must pass review before previewing M2C.2 background music.")

    production_job = production_brief_job_store.get(assembly_job.production_brief_job_id)
    if not production_job.result:
        raise AudioFinishingError("The approved production brief is unavailable.")

    audio_direction = production_job.result.publishing.audio_direction or ""
    effective = _resolve_music_preset(requested, audio_direction)
    fingerprint = hashlib.sha1(audio_direction.encode("utf-8")).hexdigest()[:10]
    assembly_cache_key = hashlib.sha1(assembly_job_id.encode("utf-8")).hexdigest()[:20]
    preview_dir = tenant_scoped_root(Path(settings.content_dna_checkpoint_dir)) / "audio_music_previews" / assembly_cache_key
    preview_dir.mkdir(parents=True, exist_ok=True)
    destination = preview_dir / f"{requested.value.lower()}-{effective.value.lower()}-{fingerprint}.wav"

    if destination.exists() and destination.stat().st_size > 1000:
        return destination, effective

    ffmpeg = _ffmpeg_executable()
    temporary = preview_dir / f".{destination.stem}-{uuid4().hex}.tmp.wav"
    try:
        _generate_music_bed(ffmpeg, temporary, max(3.0, min(15.0, duration_seconds)), effective)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    return destination, effective


def _generate_ambience(ffmpeg: str, destination: Path, duration: float, profile: str) -> None:
    if profile == "CABIN":
        filters = (
            f"anoisesrc=color=pink:amplitude=0.025:duration={duration:.3f}:sample_rate=44100,lowpass=f=480,highpass=f=70[hum];"
            "sine=frequency=880:duration=0.22:sample_rate=44100,volume=0.06,adelay=120|120[ch1];"
            "sine=frequency=659.25:duration=0.28:sample_rate=44100,volume=0.045,adelay=330|330[ch2];"
            f"[hum][ch1][ch2]amix=inputs=3:normalize=0,afade=t=out:st={max(0.0, duration-0.35):.3f}:d=0.35,pan=stereo|c0=c0|c1=c0[out]"
        )
    elif profile == "KITCHEN":
        filters = (
            f"anoisesrc=color=white:amplitude=0.012:duration={duration:.3f}:sample_rate=44100,lowpass=f=1200[room];"
            "sine=frequency=1046.5:duration=0.12:sample_rate=44100,volume=0.035,adelay=450|450[bell];"
            f"[room][bell]amix=inputs=2:normalize=0,afade=t=out:st={max(0.0, duration-0.3):.3f}:d=0.3,pan=stereo|c0=c0|c1=c0[out]"
        )
    elif profile == "CELEBRATION":
        filters = (
            f"anoisesrc=color=pink:amplitude=0.010:duration={duration:.3f}:sample_rate=44100,lowpass=f=1600[room];"
            "sine=frequency=784:duration=0.18:sample_rate=44100,volume=0.035,adelay=180|180[ch];"
            f"[room][ch]amix=inputs=2:normalize=0,afade=t=out:st={max(0.0, duration-0.3):.3f}:d=0.3,pan=stereo|c0=c0|c1=c0[out]"
        )
    else:
        filters = (
            f"anoisesrc=color=pink:amplitude=0.010:duration={duration:.3f}:sample_rate=44100,lowpass=f=900,"
            f"afade=t=out:st={max(0.0, duration-0.3):.3f}:d=0.3,pan=stereo|c0=c0|c1=c0[out]"
        )
    _run([
        ffmpeg, "-y", "-f", "lavfi", "-i", filters, "-map", "0:a:0",
        "-c:a", "pcm_s16le", str(destination.resolve()),
    ])


def _mix_layers(ffmpeg: str, layers: list[tuple[Path, float]], destination: Path, duration: float, target_lufs: float) -> None:
    if not layers:
        _make_silence(ffmpeg, destination, duration)
        return
    command = [ffmpeg, "-y"]
    for path, _ in layers:
        command.extend(["-i", str(path.resolve())])
    chains = []
    labels = []
    for index, (_, volume) in enumerate(layers):
        label = f"a{index}"
        chains.append(f"[{index}:a]volume={volume:.4f}[{label}]")
        labels.append(f"[{label}]")
    chains.append(
        f"{''.join(labels)}amix=inputs={len(layers)}:duration=longest:dropout_transition=0,"
        f"atrim=0:{duration:.3f},loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11[out]"
    )
    command.extend([
        "-filter_complex", ";".join(chains), "-map", "[out]", "-ar", "44100", "-ac", "2",
        "-c:a", "aac", "-b:a", "192k", str(destination.resolve()),
    ])
    _run(command)


def _mix_audio_buses(
    ffmpeg: str,
    destination: Path,
    duration: float,
    target_lufs: float,
    options: AudioMixOptions,
    *,
    music_path: Optional[Path] = None,
    voice_path: Optional[Path] = None,
    ambience_path: Optional[Path] = None,
) -> None:
    buses: list[tuple[str, Path, float]] = []
    if music_path is not None:
        buses.append(("music", music_path, options.music_volume))
    if voice_path is not None:
        buses.append(("voice", voice_path, options.voice_volume))
    if ambience_path is not None:
        buses.append(("ambience", ambience_path, options.ambience_volume))
    if not buses:
        _run([
            ffmpeg, "-y", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}", "-c:a", "aac", "-b:a", "192k", str(destination.resolve()),
        ])
        return

    command = [ffmpeg, "-y"]
    indices: dict[str, int] = {}
    for index, (key, path, _) in enumerate(buses):
        indices[key] = index
        command.extend(["-i", str(path.resolve())])

    chains: list[str] = []
    mix_labels: list[str] = []
    if "music" in indices and "voice" in indices and options.duck_music_during_voiceover:
        music_index = indices["music"]
        voice_index = indices["voice"]
        chains.append(f"[{music_index}:a]volume={options.music_volume:.4f}[musicv]")
        chains.append(f"[{voice_index}:a]volume={options.voice_volume:.4f},asplit=2[voicekey][voicemix]")
        chains.append(
            "[musicv][voicekey]sidechaincompress="
            "threshold=0.030:ratio=4:attack=15:release=280:makeup=1[duckedmusic]"
        )
        mix_labels.extend(["[duckedmusic]", "[voicemix]"])
    else:
        if "music" in indices:
            chains.append(f"[{indices['music']}:a]volume={options.music_volume:.4f}[musicmix]")
            mix_labels.append("[musicmix]")
        if "voice" in indices:
            chains.append(f"[{indices['voice']}:a]volume={options.voice_volume:.4f}[voicemix]")
            mix_labels.append("[voicemix]")

    if "ambience" in indices:
        chains.append(f"[{indices['ambience']}:a]volume={options.ambience_volume:.4f}[ambmix]")
        mix_labels.append("[ambmix]")

    chains.append(
        f"{''.join(mix_labels)}amix=inputs={len(mix_labels)}:duration=longest:dropout_transition=0,"
        f"atrim=0:{duration:.3f},loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11[out]"
    )
    command.extend([
        "-filter_complex", ";".join(chains), "-map", "[out]", "-ar", "44100", "-ac", "2",
        "-c:a", "aac", "-b:a", "192k", str(destination.resolve()),
    ])
    _run(command)


def _mux_delivery(ffmpeg: str, visual: Path, audio: Path, destination: Path) -> None:
    _run([
        ffmpeg, "-y", "-i", str(visual.resolve()), "-i", str(audio.resolve()),
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart", str(destination.resolve()),
    ])


def _track_text_tokens(track) -> set[str]:
    text = " ".join(
        str(getattr(track, field, "") or "")
        for field in ("title", "artist", "genre", "mood")
    ).lower()
    return {token for token in text.replace("/", " " ).replace("-", " " ).split() if len(token) >= 3}


def _direction_tokens(audio_direction: str) -> set[str]:
    return {
        token
        for token in (audio_direction or "").lower().replace("/", " " ).replace("-", " " ).split()
        if len(token) >= 3
    }


def _selected_saved_track_id(job: AudioFinishingJob) -> Optional[str]:
    if job.result and job.result.selected_youtube_audio_library_track:
        return job.result.selected_youtube_audio_library_track.track_id
    value = job.detail.get("youtube_audio_library_track_id") if isinstance(job.detail, dict) else None
    return str(value).strip() if value else None


def _auto_select_saved_soundtrack(
    *,
    store: AudioFinishingJobStore,
    job: AudioFinishingJob,
    saved_tracks: list,
    audio_direction: str,
) -> tuple[object, str]:
    """Choose a saved soundtrack with repeat protection and deterministic rotation.

    Policy:
    - Audio-only revisions keep the prior version's soundtrack when possible.
    - New productions avoid tracks used by the previous 3 distinct productions.
    - Among eligible tracks, prefer audio-direction metadata matches, then least-used,
      then least-recently-used. This remains deterministic across Cloud Run instances.
    """
    by_id = {track.track_id: track for track in saved_tracks}
    # Inspect the entire audio lineage, because a replacement may have been
    # created before its immediate predecessor received a listening review.
    # Never rely solely on the most recent version's review metadata.
    rejected_ids: set[str] = set()
    flagged_music = False
    ancestor_id = job.based_on_job_id
    seen_ids: set[str] = set()
    for _ in range(30):
        if not ancestor_id or ancestor_id in seen_ids:
            break
        seen_ids.add(ancestor_id)
        try:
            ancestor = store.get(ancestor_id)
        except Exception:
            logger.exception("Could not inspect audio ancestor %s", ancestor_id)
            break
        review = (ancestor.detail or {}).get("ai_audio_review") or {}
        review_text = (
            " ".join(str(x) for x in review.get("issues", []))
            + " " + str(review.get("corrective_instruction") or "")
        )
        if re.search(r"music|soundtrack|genre|instrumental|vocals|acoustic|mix balance", review_text, re.IGNORECASE):
            flagged_music = True
            track_id = _selected_saved_track_id(ancestor)
            if track_id:
                rejected_ids.add(track_id)
        ancestor_id = ancestor.based_on_job_id

    if job.based_on_job_id and not flagged_music:
        try:
            previous = store.get(job.based_on_job_id)
            previous_track_id = _selected_saved_track_id(previous)
            if previous_track_id and previous_track_id in by_id:
                prior_track = by_id[previous_track_id]
                if not _direction_tokens(audio_direction) or (_direction_tokens(audio_direction) & _track_text_tokens(prior_track)):
                    return prior_track, "previous-version"
                logger.warning("Prior soundtrack metadata does not match production direction; reselecting")
        except Exception:
            logger.exception("Could not inspect prior audio version %s", job.based_on_job_id)

    history = [
        item
        for item in store.list_for_channel(job.channel_id)
        if item.job_id != job.job_id
        and item.production_brief_job_id != job.production_brief_job_id
    ]

    usage_count: dict[str, int] = {}
    last_used_position: dict[str, int] = {}
    recent_distinct: list[str] = []
    seen_productions: set[str] = set()

    for position, item in enumerate(history):
        track_id = _selected_saved_track_id(item)
        if not track_id or track_id not in by_id:
            continue
        usage_count[track_id] = usage_count.get(track_id, 0) + 1
        last_used_position.setdefault(track_id, position)
        production_id = item.production_brief_job_id or item.job_id
        if production_id not in seen_productions:
            seen_productions.add(production_id)
            recent_distinct.append(track_id)

    recent_three = set(recent_distinct[:3])
    eligible = [track for track in saved_tracks if track.track_id not in recent_three]
    if not eligible:
        eligible = list(saved_tracks)

    direction = _direction_tokens(audio_direction)

    def rank(track):
        metadata_match = len(direction & _track_text_tokens(track))
        count = usage_count.get(track.track_id, 0)
        # Larger position means it was used longer ago. Never-used tracks rank highest.
        age = last_used_position.get(track.track_id, 1_000_000)
        return (
            -metadata_match,
            count,
            -age,
            track.title.casefold(),
            track.track_id,
        )

    # Review-rejected tracks must never be selected again in this remix.
    # Also honor the explicit correction manifest on the queued job: ancestor
    # metadata can be incomplete on jobs that were not reviewed.
    correction = (job.detail or {}).get("correction_manifest") or {}
    rejected_ids.update(str(x) for x in (correction.get("rejected_track_ids") or []) if x)
    eligible = [track for track in eligible if track.track_id not in rejected_ids]
    if not eligible:
        return None, "review-rejected-catalog"
    # Strong creative constraints are enforced even when generic words overlap.
    requested = _direction_tokens(audio_direction)
    if {"acoustic", "guitar"} & requested:
        eligible = [track for track in eligible if
                    ({"acoustic", "guitar"} & _track_text_tokens(track))
                    and not ({"rock", "pop", "vocal", "vocals", "singing", "energetic"} & _track_text_tokens(track))]
        if not eligible:
            return None, "no-confirmed-acoustic-match"
    ranked = sorted(eligible, key=rank)
    chosen = ranked[0]
    if direction and not (direction & _track_text_tokens(chosen)):
        return None, "no-metadata-match"
    mode = "rotation" if chosen.track_id not in recent_three else "least-recently-used"
    return chosen, mode


def render_audio_finishing(job_id: str, settings: Settings) -> None:
    from app.services.autopilot_side_effect_fence import require_supervisor_lease
    require_supervisor_lease("audio render start")
    store = audio_finishing_job_store
    try:
        job = store.get(job_id)
        assembly_job = final_assembly_job_store.get(job.assembly_job_id)
        if not assembly_job.result or assembly_job.result.review_status != FinalAssemblyReviewStatus.APPROVED:
            raise AudioFinishingError("The approved visual master is unavailable.")
        production_job = production_brief_job_store.get(job.production_brief_job_id)
        if not production_job.result:
            raise AudioFinishingError("The approved production brief is unavailable.")

        ffmpeg = _ffmpeg_executable()
        work_dir = store.work_dir(job_id)
        assets_dir = store.assets_dir(job_id)
        total_duration = assembly_job.result.total_duration_seconds
        audio_direction = production_job.result.publishing.audio_direction or ""
        profile = _ambience_profile(audio_direction)
        warnings: list[str] = []
        layers_summary: list[AudioLayerSummary] = []
        voiceover_cues: list[VoiceoverCue] = []
        music_path: Optional[Path] = None
        ambience_path: Optional[Path] = None
        voice_path: Optional[Path] = None
        effective_voice = job.options.voice_name or settings.audio_tts_voice
        effective_music_preset = _resolve_music_preset(job.options.music_preset, audio_direction)
        effective_music_source = job.options.music_source
        selected_trending_track = None
        selected_youtube_audio_library_track = None
        soundtrack_selection_mode = "explicit" if job.options.youtube_audio_library_track_id else None

        job.stage = AudioFinishingJobStage.PREPARING
        job.progress_current = 1
        job.message = "Preparing the approved visual master and audio direction"
        job.detail = {**job.detail, "ambience_profile": profile,
                      "specific_sfx_verified": False,
                      "specific_sfx_note": "Generic ambience is not evidence of requested ASMR effects."}
        store.save(job)

        visual_path, _ = final_assembly_job_store.asset_path(job.assembly_job_id, assembly_job.result.final_video.asset_id)

        if job.options.music_enabled:
            music_path = work_dir / "music-bed.wav"
            if job.options.music_source == MusicSource.TRENDING_LICENSED:
                try:
                    resolved_track = trending_music_catalog.resolve(job.options.trending_track_id or "", settings)
                except TrendingMusicTrackNotFoundError as exc:
                    raise AudioFinishingError("The selected trending music track is no longer in the catalog.") from exc
                except TrendingMusicCatalogError as exc:
                    raise AudioFinishingError(str(exc)) from exc
                if not resolved_track.local_path:
                    raise AudioFinishingError("The selected licensed trending track file is unavailable.")
                _prepare_trending_music_bed(ffmpeg, resolved_track.local_path, music_path, total_duration)
                selected_trending_track = resolved_track.public
                display_artist = f" · {resolved_track.public.artist}" if resolved_track.public.artist else ""
                rights = resolved_track.public.license_reference or resolved_track.public.provider or "rights confirmed in catalog"
                layers_summary.append(AudioLayerSummary(
                    key="music", label="Trending licensed music", enabled=True, generated=True,
                    detail=(
                        f"{resolved_track.public.title}{display_artist} · {resolved_track.public.platform or 'licensed catalog'} "
                        f"· {round(job.options.music_volume * 100)}% mix level · {rights}."
                    ),
                ))
            elif job.options.music_source == MusicSource.YOUTUBE_AUDIO_LIBRARY:
                selected_track_id = job.options.youtube_audio_library_track_id
                if not selected_track_id:
                    try:
                        saved_tracks = sorted(
                            (track for track in youtube_audio_library.list(settings).tracks if track.render_ready),
                            key=lambda track: (track.title.casefold(), track.track_id),
                        )
                    except YouTubeAudioLibraryError as exc:
                        raise AudioFinishingError(str(exc)) from exc
                    if not saved_tracks:
                        selected_track, soundtrack_selection_mode = None, "empty-catalog"
                    else:
                        selected_track, soundtrack_selection_mode = _auto_select_saved_soundtrack(
                            store=store,
                            job=job,
                            saved_tracks=saved_tracks,
                            audio_direction=audio_direction,
                        )
                    if selected_track is None:
                        warnings.append("No saved soundtrack matched direction metadata; using generated instrumental bed.")
                        _generate_music_bed(ffmpeg, music_path, total_duration, effective_music_preset)
                        layers_summary.append(AudioLayerSummary(
                            key="music", label="ReviveAI music bed", enabled=True, generated=True,
                            detail=f"Generated {MUSIC_PRESET_LABELS[effective_music_preset]} instrumental bed; no matching catalog metadata.",
                        ))
                    else:
                        selected_track_id = selected_track.track_id
                        warnings.append(
                            f"ReviveAI auto-selected Saved soundtrack: {selected_track.title} "
                            f"({soundtrack_selection_mode}; recent-repeat protection enabled)."
                        )
                if selected_track_id:
                    try:
                        resolved_youtube_track = youtube_audio_library.resolve(
                            selected_track_id, settings
                        )
                    except YouTubeAudioLibraryTrackNotFoundError as exc:
                        raise AudioFinishingError("The selected YouTube Audio Library track is no longer in your imported library.") from exc
                    except YouTubeAudioLibraryError as exc:
                        raise AudioFinishingError(str(exc)) from exc

                    track_file = getattr(resolved_youtube_track, 'local_path', None)
                    if getattr(resolved_youtube_track, 'storage_path', None):
                        track_file = store.cloud_storage.download_temp(resolved_youtube_track.storage_path)

                    _prepare_trending_music_bed(
                        ffmpeg, track_file, music_path, total_duration
                    )
                    selected_youtube_audio_library_track = resolved_youtube_track.public
                    display_artist = f" · {resolved_youtube_track.public.artist}" if resolved_youtube_track.public.artist else ""
                    attribution_note = (
                        " · attribution will be added to the YouTube description"
                        if resolved_youtube_track.public.attribution_required
                        else " · no attribution marked as required"
                    )
                    layers_summary.append(AudioLayerSummary(
                        key="music", label="YouTube Audio Library music", enabled=True, generated=True,
                        detail=(
                            f"{resolved_youtube_track.public.title}{display_artist} · "
                            f"{round(job.options.music_volume * 100)}% mix level{attribution_note}."
                        ),
                    ))
            else:
                _generate_music_bed(ffmpeg, music_path, total_duration, effective_music_preset)
                preset_label = MUSIC_PRESET_LABELS[effective_music_preset]
                selection_detail = f"Auto matched to {preset_label}" if job.options.music_preset == BackgroundMusicPreset.AUTO else preset_label
                layers_summary.append(AudioLayerSummary(
                    key="music", label="ReviveAI music bed", enabled=True, generated=True,
                    detail=f"{selection_detail} · {round(job.options.music_volume * 100)}% mix level.",
                ))
        else:
            layers_summary.append(AudioLayerSummary(key="music", label="Music", enabled=False, generated=False, detail="Disabled by creator."))

        if job.options.ambience_sfx_enabled:
            ambience_path = work_dir / "ambience.wav"
            _generate_ambience(ffmpeg, ambience_path, total_duration, profile)
            layers_summary.append(AudioLayerSummary(
                key="ambience", label="Ambience + SFX", enabled=True, generated=True,
                detail=f"{profile.title()} profile · {round(job.options.ambience_volume * 100)}% mix level.",
            ))
        else:
            layers_summary.append(AudioLayerSummary(key="ambience", label="Ambience + SFX", enabled=False, generated=False, detail="Disabled by creator."))

        if job.options.voiceover_enabled:
            # Apply the immutable production budget before any billable voice call.
            # The production brief ID is the canonical key shared with Veo.
            from app.services.channel_autonomy_policy import channel_policy_store
            from app.services.firestore_budget_service import FirestoreBudgetService
            from app.services.narration_budget import estimated_tts_usd
            narration_budget = FirestoreBudgetService()
            narration_budget.ensure_production_budget(
                job.production_brief_job_id, job.channel_id,
                channel_policy_store.get(job.channel_id).max_total_production_cost_usd,
            )
            job.stage = AudioFinishingJobStage.SYNTHESIZING_VOICE
            job.progress_current = 2
            job.message = "Synthesizing concise shot voiceover with Google Cloud Text-to-Speech"
            store.save(job)
            voice_segments: list[Path] = []
            aligned_caption_cues: list[tuple[float, float, str]] = []
            narration_alignment_complete = True
            cursor = 0.0
            synthesized_any = False
            stem_records: list[dict] = []
            verification_records: dict[str, dict] = {}
            tts_warning: Optional[str] = None
            for item in assembly_job.result.timeline:
                duration = item.output_duration_seconds
                text = _voice_text_for_shot(item)
                cue = VoiceoverCue(
                    shot_number=item.shot_number,
                    start_seconds=round(cursor, 3),
                    duration_seconds=duration,
                    text=text,
                    synthesized=False,
                )
                segment = work_dir / f"voice-{item.shot_number:02d}.wav"
                if text and settings.audio_tts_enabled:
                    try:
                        mp3 = work_dir / f"voice-{item.shot_number:02d}.mp3"
                        # Reserve BEFORE synthesis and reconcile immediately after
                        # receipt. An uncertain failure deliberately keeps the
                        # reservation; never automatically re-submit this job.
                        tts_operation_id = f"tts_{job.job_id}_{item.shot_number}"
                        tts_estimate = estimated_tts_usd(text)
                        reservation = narration_budget.reserve(
                            job.production_brief_job_id, tts_estimate, tts_operation_id,
                        )
                        if not reservation.get("allowed"):
                            raise AudioFinishingError(
                                "Narration budget reservation denied: "
                                + str(reservation.get("reason") or "insufficient remaining production budget")
                            )
                        job.detail = {**job.detail, "tts_budget_reservations": {
                            **job.detail.get("tts_budget_reservations", {}),
                            str(item.shot_number): tts_operation_id,
                        }}
                        store.save(job)
                        phrases, marks = _synthesize_tts(text, mp3, settings, effective_voice)
                        # Google TTS does not expose the final billed USD here.
                        # This amount is an accounted estimate with retry margin,
                        # not a claim of actual provider invoice charges.
                        narration_budget.reconcile(
                            job.production_brief_job_id, tts_operation_id,
                            tts_estimate, tts_estimate,
                        )
                        job.detail = {**job.detail, "tts_cost_accounting": "ESTIMATED_NOT_INVOICED"}
                        store.save(job)
                        fit = _fit_voice_segment(ffmpeg, mp3, segment, duration)
                        job.detail = {**job.detail, "narration_fit": {
                            **job.detail.get("narration_fit", {}), str(item.shot_number): fit,
                        }}
                        # SSML timepoints refer to the source audio timeline. Once tempo
                        # changes, they cannot be used unchanged as aligned captions.
                        aligned = (timed_phrases(phrases, marks, shot_start=cursor, shot_duration=duration)
                                   if fit["tempo"] == 1.0 else [])
                        if not aligned:
                            # Do not infer timing from storyboard or nominal shot length.
                            # Align the actual synthesized narration, not the mixed soundtrack.
                            normalized = work_dir / f"voice-align-{item.shot_number:02d}.wav"
                            _run([ffmpeg, "-y", "-i", str(segment.resolve()), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(normalized.resolve())])
                            try:
                                local_cues, report = align_voice_wav(normalized, text, language_code=settings.audio_tts_language_code)
                                aligned = [(cursor + a, cursor + b, phrase) for a, b, phrase in local_cues]
                                verification_records[str(item.shot_number)] = report
                            except Exception as alignment_error:
                                verification_records[str(item.shot_number)] = {"method": "UNVERIFIED", "reason": str(alignment_error)[:500]}
                                logger.warning("Speech alignment unavailable for %s shot %s: %s", job_id, item.shot_number, alignment_error)
                        if aligned:
                            aligned_caption_cues.extend(aligned)
                        else:
                            narration_alignment_complete = False
                        # Keep each voice stem durable for subsequent caption-only corrections.
                        stem_asset = assets_dir / f"narration-shot-{item.shot_number:02d}.wav"
                        shutil.copy2(segment, stem_asset)
                        uri = store._artifacts.upload_file(stem_asset, owner_id=job_id,
                            relative_path=f"assets/{stem_asset.name}", content_type="audio/wav")
                        if not uri:
                            raise AudioFinishingError("Narration stem could not be persisted in GCS; refusing non-recoverable delivery")
                        stem_records.append({"shot_number": item.shot_number, "filename": stem_asset.name, "gcs_uri": uri, "text": text, "duration_seconds": duration})
                        cue.synthesized = True
                        synthesized_any = True
                    except Exception as exc:
                        logger.exception("Required TTS synthesis failed for audio job %s shot %s", job_id, item.shot_number)
                        job.detail = {
                            **job.detail,
                            "tts_failed_shot": item.shot_number,
                            "tts_error_type": type(exc).__name__,
                            "tts_error": str(exc)[:1600],
                            "tts_voice": effective_voice,
                        }
                        store.save(job)
                        raise AudioFinishingError(
                            f"Required voiceover failed at shot {item.shot_number}: "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                else:
                    if text and not settings.audio_tts_enabled:
                        raise AudioFinishingError(
                            "Required voiceover cues exist, but AUDIO_TTS_ENABLED is false. "
                            "Enable TTS or explicitly disable voiceover for this audio master."
                        )
                    _make_silence(ffmpeg, segment, duration)
                voice_segments.append(segment)
                voiceover_cues.append(cue)
                cursor += duration
            rendered_voice_path = work_dir / "voiceover.wav"
            job.detail = {**job.detail, "narration_stems": stem_records, "speech_alignment_reports": verification_records}
            store.save(job)
            _concat_audio(ffmpeg, voice_segments, rendered_voice_path, work_dir)
            if synthesized_any:
                voice_path = rendered_voice_path
            if tts_warning:
                warnings.append(tts_warning)
            layers_summary.append(AudioLayerSummary(
                key="voiceover", label="Voiceover", enabled=True, generated=synthesized_any,
                detail=f"Google Cloud TTS · {effective_voice} · {round(job.options.voice_volume * 100)}% mix level." if synthesized_any else "No synthesized cues were added.",
                warning=tts_warning,
            ))
        else:
            layers_summary.append(AudioLayerSummary(key="voiceover", label="Voiceover", enabled=False, generated=False, detail="Disabled by creator."))

        job = store.get(job_id)
        job.stage = AudioFinishingJobStage.BUILDING_MIX
        job.progress_current = 3
        job.message = "Mixing music, ambience, SFX, and voiceover"
        store.save(job)

        audio_asset_id = f"mix_{uuid4().hex}"
        mix_path = assets_dir / f"{audio_asset_id}.m4a"
        _mix_audio_buses(
            ffmpeg,
            mix_path,
            total_duration,
            settings.audio_target_lufs,
            job.options,
            music_path=music_path,
            voice_path=voice_path,
            ambience_path=ambience_path,
        )

        # Remain BUILDING_MIX until the complete result and durable pre-mux
        # checkpoint have been persisted. Persisting RENDERING without a
        # checkpoint strands jobs after an instance is terminated.
        delivery_id = f"delivery_{uuid4().hex}"
        delivery_path = assets_dir / f"{delivery_id}.mp4"
        # Mux is deliberately deferred until metadata and the independently
        # generated mix/subtitles have been persisted to durable storage.

        subtitle_asset = None
        # Delivery subtitles are authored after narration exists, never from storyboard
        # estimates when provider timing has been verified for every spoken shot.
        if job.options.voiceover_enabled and aligned_caption_cues and narration_alignment_complete:
            subtitle_id = f"subs_{uuid4().hex}"
            subtitle_path = assets_dir / f"{subtitle_id}.srt"
            write_srt(subtitle_path, aligned_caption_cues)
            subtitle_asset = AssemblyAsset(
                asset_id=subtitle_id, kind=AssemblyAssetKind.SUBTITLES,
                created_at=datetime.now(timezone.utc), filename=subtitle_path.name,
                mime_type="application/x-subrip",
                asset_url=f"/api/v1/youtube/audio-jobs/{job_id}/assets/{subtitle_id}",
            )
            job.detail = {**job.detail, "subtitle_alignment": (
                "SPEECH_VERIFIED" if verification_records and all(v.get("method") == "GOOGLE_STT_WORD_OFFSETS" for v in verification_records.values())
                else "TTS_SSML_MARK" if not verification_records else "SPEECH_VERIFIED_MIXED_METHODS"
            ), "subtitle_cues": len(aligned_caption_cues)}
        elif job.options.voiceover_enabled:
            warnings.append("Audio-aligned captions unavailable for this voice or tempo-adjusted narration; storyboard-estimated SRT is not speech-verified.")
            job.detail = {**job.detail, "subtitle_alignment": "ESTIMATED_FALLBACK"}
        if subtitle_asset is None and assembly_job.result.subtitles:
            source_srt, mime = final_assembly_job_store.asset_path(job.assembly_job_id, assembly_job.result.subtitles.asset_id)
            subtitle_id = f"subs_{uuid4().hex}"
            subtitle_path = assets_dir / f"{subtitle_id}.srt"
            shutil.copy2(source_srt, subtitle_path)
            subtitle_asset = AssemblyAsset(
                asset_id=subtitle_id,
                kind=AssemblyAssetKind.SUBTITLES,
                created_at=datetime.now(timezone.utc),
                filename=subtitle_path.name,
                mime_type=mime,
                asset_url=f"/api/v1/youtube/audio-jobs/{job_id}/assets/{subtitle_id}",
            )

        publishing = assembly_job.result.publishing.model_copy(deep=True)
        if (
            selected_youtube_audio_library_track
            and selected_youtube_audio_library_track.attribution_required
            and selected_youtube_audio_library_track.attribution_text
        ):
            attribution = selected_youtube_audio_library_track.attribution_text.strip()
            marker = "Music attribution:"
            if attribution and attribution not in publishing.description:
                publishing.description = (
                    publishing.description.rstrip()
                    + f"\n\n{marker}\n{attribution}"
                ).strip()

        result = AudioFinishingResult(
            assembly_job_id=job.assembly_job_id,
            production_brief_job_id=job.production_brief_job_id,
            media_job_id=job.media_job_id,
            working_title=assembly_job.result.working_title,
            rendered_at=datetime.now(timezone.utc),
            total_duration_seconds=total_duration,
            delivery_video=AssemblyAsset(
                asset_id=delivery_id,
                kind=AssemblyAssetKind.FINAL_VIDEO,
                created_at=datetime.now(timezone.utc),
                filename=delivery_path.name,
                mime_type="video/mp4",
                asset_url=f"/api/v1/youtube/audio-jobs/{job_id}/assets/{delivery_id}",
            ),
            subtitles=subtitle_asset,
            audio_mix=AssemblyAsset(
                asset_id=audio_asset_id,
                kind=AssemblyAssetKind.AUDIO_MIX,
                created_at=datetime.now(timezone.utc),
                filename=mix_path.name,
                mime_type="audio/mp4",
                asset_url=f"/api/v1/youtube/audio-jobs/{job_id}/assets/{audio_asset_id}",
            ),
            publishing=publishing,
            options=job.options,
            layers=layers_summary,
            voiceover_cues=voiceover_cues,
            audio_direction=audio_direction,
            ambience_profile=profile,
            effective_tts_voice=effective_voice,
            effective_music_preset=effective_music_preset,
            effective_music_source=effective_music_source,
            selected_trending_track=selected_trending_track,
            selected_youtube_audio_library_track=selected_youtube_audio_library_track,
            warnings=warnings,
        )
        job = store.get(job_id)
        job.result = result
        job.detail = {
            **job.detail,
            "visual_master_preserved": True,
            "audio_only_regeneration": job.version_number > 1,
            "tts_voice": effective_voice,
            "music_source": effective_music_source.value,
            "music_preset_requested": job.options.music_preset.value,
            "music_preset_effective": effective_music_preset.value,
            "trending_track_id": selected_trending_track.track_id if selected_trending_track else None,
            "youtube_audio_library_track_id": (
                selected_youtube_audio_library_track.track_id if selected_youtube_audio_library_track else None
            ),
            "youtube_audio_library_attribution_required": bool(
                selected_youtube_audio_library_track and selected_youtube_audio_library_track.attribution_required
            ),
            "soundtrack_selection_mode": soundtrack_selection_mode,
            "duck_music_during_voiceover": job.options.duck_music_during_voiceover,
        }
        correction = (job.detail or {}).get("correction_manifest")
        if isinstance(correction, dict):
            actual_track = job.detail.get("youtube_audio_library_track_id")
            rejected_tracks = set(correction.get("rejected_track_ids") or [])
            if actual_track and actual_track in rejected_tracks:
                raise AudioFinishingError("Corrective remix reused a reviewer-rejected soundtrack")
            ceiling = float(correction.get("music_volume_ceiling", 0.30))
            if job.options.music_enabled and job.options.music_volume > ceiling + 0.0001:
                raise AudioFinishingError("Corrective remix music level exceeds its approved ceiling")
            job.detail = {**job.detail, "correction_manifest": {
                **correction,
                "actual_track_id": actual_track,
                "actual_music_volume": job.options.music_volume,
                "actual_ambience_volume": job.options.ambience_volume,
                "music_changed": actual_track != correction.get("previous_track_id"),
                "status": "MIX_RENDERED_AWAITING_AI_REVIEW",
                "specific_asmr_effects_verified": False,
            }}
            # The correction manifest is part of the durable pre-mux checkpoint.

        job.stage = AudioFinishingJobStage.RENDERING
        job.progress_current = 4
        job.message = "Muxing the approved visual master with the unified audio mix"
        job.detail = {**job.detail, "render_checkpoint": {
            "version": 1, "state": "MUX_READY",
            "prepared_at": datetime.now(timezone.utc).isoformat(),
            "delivery_asset_id": delivery_id,
            "mix_asset_id": audio_asset_id,
        }}
        # Upload mix/SRT and preserve complete result metadata before muxing.
        # A new Cloud Run instance can now finish without any provider calls.
        store.save(job)
        _mux_delivery(ffmpeg, visual_path, mix_path, delivery_path)
        job = store.get(job_id)
        job.stage = AudioFinishingJobStage.COMPLETED
        job.progress_current = job.progress_total
        job.message = f"Audio master v{job.version_number} rendered; AI listening review pending"
        job.error = None
        job.detail = {**job.detail, "render_checkpoint": {
            **job.detail.get("render_checkpoint", {}),
            "state": "COMPLETED",
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }}
        store.save(job)
    except Exception as exc:
        logger.exception("Audio finishing failed")
        message = str(exc) if isinstance(exc, AudioFinishingError) else "ReviveAI could not finish the delivery audio mix."
        store.fail(job_id, message)

def _mux_recovery_lock_ref(job_id: str):
    """Tenant-scoped lock separate from the JSON job document."""
    return (get_runtime_firestore_client().collection("reviveai_tenants")
            .document(tenant_namespace()).collection("audio_mux_recovery_locks")
            .document(job_id))


def _acquire_mux_recovery_claim(job_id: str, owner: str) -> bool:
    """Atomic claim. Fail closed if Firestore is unreachable.

    The 45-minute lease exceeds the recovery FFmpeg timeout (20 minutes) and
    validation budget; a different owner must never share the output path.
    """
    from google.cloud import firestore
    ref = _mux_recovery_lock_ref(job_id)
    transaction = get_runtime_firestore_client().transaction()

    @firestore.transactional
    def claim(tx):
        snap = ref.get(transaction=tx)
        info = snap.to_dict() or {}
        now = datetime.now(timezone.utc)
        expires = info.get("expires_at")
        if expires is not None:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires > now:
                return False
        # Increment across expiration/takeover: never recycle an ownership generation.
        generation = int(info.get("generation") or 0) + 1
        tx.set(ref, {"owner": owner, "generation": generation, "claimed_at": now,
                     "expires_at": now + timedelta(minutes=45)})
        return True

    return bool(claim(transaction))


def _owns_mux_recovery_claim(job_id: str, owner: str) -> bool:
    info = _mux_recovery_lock_ref(job_id).get().to_dict() or {}
    expiry = info.get("expires_at")
    return (info.get("owner") == owner and expiry is not None
            and (expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry)
            > datetime.now(timezone.utc))


def _release_mux_recovery_claim(job_id: str, owner: str) -> None:
    from google.cloud import firestore
    ref = _mux_recovery_lock_ref(job_id)
    transaction = get_runtime_firestore_client().transaction()

    @firestore.transactional
    def release(tx):
        snap = ref.get(transaction=tx)
        if snap.exists and (snap.to_dict() or {}).get("owner") == owner:
            # Preserve generation counter across releases; never delete lock doc.
            tx.update(ref, {"owner": None, "expires_at": datetime.now(timezone.utc)})

    release(transaction)



def _mux_recovery_claim_generation(job_id: str, owner: str) -> int:
    """Return the active claim generation, never the previous owner's generation."""
    data = _mux_recovery_lock_ref(job_id).get().to_dict() or {}
    expiry = data.get("expires_at")
    if expiry is None:
        return 0
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    if data.get("owner") != owner or expiry <= datetime.now(timezone.utc):
        return 0
    return int(data.get("generation") or 0)


def _commit_mux_recovery_fenced(job_id: str, owner: str, generation: int,
                                destination_filename: str, destination_gcs_uri: str) -> bool:
    """Atomically change audio job and recovery lock; refuse expired/stale owners.

    This covers inline FirestoreJobRepository documents only. Chunked documents
    fail closed; we cannot update their chunks inside this transaction.
    The unique, pre-uploaded MP4 remains orphaned if commit is refused.
    """
    from google.cloud import firestore
    db = get_runtime_firestore_client()
    lock_ref = _mux_recovery_lock_ref(job_id)
    job_ref = (db.collection("reviveai_tenants").document(tenant_namespace())
               .collection("audio_finishing_jobs").document(job_id))
    tx = db.transaction()

    @firestore.transactional
    def commit(transaction):
        # All reads must precede writes inside a Firestore transaction.
        lock_snap = lock_ref.get(transaction=transaction)
        job_snap = job_ref.get(transaction=transaction)
        lock = lock_snap.to_dict() or {}
        expiry = lock.get("expires_at")
        if expiry is None:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if (lock.get("owner") != owner or int(lock.get("generation") or 0) != generation
                or expiry <= datetime.now(timezone.utc)):
            return False
        raw = job_snap.to_dict() or {}
        if raw.get("storage_mode") != FirestoreJobRepository.STORAGE_INLINE:
            return False
        payload_json = raw.get("payload_json")
        if not isinstance(payload_json, str):
            return False
        payload = json.loads(payload_json)
        detail = payload.get("detail") or {}
        checkpoint = detail.get("render_checkpoint") or {}
        result = payload.get("result") or {}
        delivery = result.get("delivery_video") or {}
        if (payload.get("stage") != AudioFinishingJobStage.RENDERING.value
                or checkpoint.get("version") != 1 or checkpoint.get("state") != "MUX_READY"
                or checkpoint.get("delivery_asset_id") != delivery.get("asset_id")):
            return False
        now = datetime.now(timezone.utc)
        payload["stage"] = AudioFinishingJobStage.COMPLETED.value
        payload["progress_current"] = payload.get("progress_total", 5)
        payload["message"] = (f"Audio master v{payload.get('version_number')} recovered "
                              "from durable mux checkpoint; AI review pending")
        payload["error"] = None
        payload["updated_at"] = now.isoformat()
        detail["render_checkpoint"] = {**checkpoint, "state": "COMPLETED",
                                       "recovered_at": now.isoformat(),
                                       "recovery_generation": generation}
        payload["detail"] = detail
        delivery["filename"] = destination_filename
        delivery["gcs_uri"] = destination_gcs_uri
        result["delivery_video"] = delivery
        payload["result"] = result
        serialized = FirestoreJobRepository._encode(payload)
        encoded = serialized.encode("utf-8")
        if len(encoded) > FirestoreJobRepository.INLINE_JSON_LIMIT_BYTES:
            return False
        transaction.set(job_ref, {
            "schema_version": FirestoreJobRepository.SCHEMA_VERSION,
            "storage_mode": FirestoreJobRepository.STORAGE_INLINE,
            "payload_json": serialized,
            "payload_size_bytes": len(encoded),
            "payload_sha256": FirestoreJobRepository._sha256(encoded),
            "persisted_at": now,
        })
        transaction.update(lock_ref, {"committed_generation": generation})
        return True

    return bool(commit(tx))


def _probe_mux_media(path: Path, *, require_video: bool, require_audio: bool) -> bool:
    """Verify FFprobe can demux the file and identify required media streams.

    Size-only checks can accept truncated/corrupt MP4s. Absence of FFprobe is
    not permission to accept unverified media.
    """
    probe = shutil.which("ffprobe")
    if not probe or not path.is_file() or path.stat().st_size < 1024:
        return False
    try:
        result = subprocess.run(
            [probe, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type", "-of", "json", str(path.resolve())],
            capture_output=True, text=True, timeout=30, check=True,
        )
        info = json.loads(result.stdout)
        kinds = {s.get("codec_type") for s in info.get("streams", [])}
        duration = float((info.get("format") or {}).get("duration") or 0)
        return (duration > 0 and (not require_video or "video" in kinds)
                and (not require_audio or "audio" in kinds))
    except (OSError, ValueError, subprocess.SubprocessError, TypeError):
        return False


def resume_audio_final_mux(job_id: str, settings: Settings) -> None:
    """Restore a MUX_READY checkpoint under generation-fenced Firestore ownership.

    Writes only to an owner-unique output filename, mirrors it to GCS, then
    atomically commits the job document plus the same claim generation.
    No TTS, Veo, or publishing calls. Missing GCS fails closed.
    """
    store = audio_finishing_job_store
    owner = f"mux-{uuid4().hex}"
    claimed = False
    generation = 0
    try:
        claimed = _acquire_mux_recovery_claim(job_id, owner)
        if not claimed:
            logger.info("Mux recovery already owned elsewhere for %s", job_id)
            return
        generation = _mux_recovery_claim_generation(job_id, owner)
        if not generation:
            logger.warning("Mux recovery claim expired before start for %s", job_id)
            return
        job = store.get(job_id)
        checkpoint = (job.detail or {}).get("render_checkpoint") or {}
        if (job.stage != AudioFinishingJobStage.RENDERING or job.result is None
                or checkpoint.get("version") != 1 or checkpoint.get("state") != "MUX_READY"):
            raise AudioFinishingError("Missing durable pre-mux checkpoint; automatic replay refused")
        assembly = final_assembly_job_store.get(job.assembly_job_id)
        if not assembly.result or assembly.result.review_status != FinalAssemblyReviewStatus.APPROVED:
            raise AudioFinishingError("Source visual master is not approved")
        if (job.detail or {}).get("source_visual_asset_id") != assembly.result.final_video.asset_id:
            raise AudioFinishingError("Visual master lineage does not match approved assembly")
        if checkpoint.get("mix_asset_id") != job.result.audio_mix.asset_id:
            raise AudioFinishingError("Audio mix checkpoint identity mismatch")
        if checkpoint.get("delivery_asset_id") != job.result.delivery_video.asset_id:
            raise AudioFinishingError("Delivery master checkpoint identity mismatch")
        mix_path, _ = store.asset_path(job_id, job.result.audio_mix.asset_id)
        visual_path, _ = final_assembly_job_store.asset_path(
            assembly.job_id, assembly.result.final_video.asset_id)
        if not _probe_mux_media(mix_path, require_video=False, require_audio=True):
            raise AudioFinishingError("Recovered audio mix failed FFprobe validation")
        if not _probe_mux_media(visual_path, require_video=True, require_audio=False):
            raise AudioFinishingError("Recovered visual master failed FFprobe validation")

        # Unique filename: an expired worker cannot overwrite the output of its
        # successor. Do not use or promote to the shared pre-recovery filename.
        filename = f"{Path(job.result.delivery_video.filename).stem}.recover-g{generation}-{owner}.mp4"
        dest = store.assets_dir(job_id) / filename
        ffmpeg = _ffmpeg_executable()
        subprocess.run([
            ffmpeg, "-y", "-i", str(visual_path.resolve()), "-i", str(mix_path.resolve()),
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(dest.resolve()),
        ], capture_output=True, text=True, timeout=1200, check=True)
        if not _probe_mux_media(dest, require_video=True, require_audio=True):
            raise AudioFinishingError("Recovered delivery failed FFprobe validation")
        if not _owns_mux_recovery_claim(job_id, owner):
            logger.warning("Mux claim ownership lost before upload: %s", job_id)
            return
        # Persist the exact bytes before committing a reference to them.
        # Never mark COMPLETED if GCS is disabled/unavailable.
        uri = store._artifacts.upload_file_create_only(
            dest, owner_id=job_id, relative_path=f"assets/{filename}",
            content_type="video/mp4",
        )
        if not uri:
            raise AudioFinishingError("Durable delivery upload unavailable; refusing recovery commit")
        if not _commit_mux_recovery_fenced(job_id, owner, generation, filename, uri):
            logger.warning("Mux recovery atomic commit rejected for %s generation=%s", job_id, generation)
            return
        # The authoritative job was saved atomically in Firestore, so clear
        # process-local caching rather than calling store.save() a second time.
        with store._lock:
            store._jobs.pop(job_id, None)
        logger.info("Mux recovery committed for %s generation=%s", job_id, generation)
    except Exception:
        # Do not call store.fail(): an unfenced error handler could overwrite a
        # job already completed or taken over by a different worker.
        logger.exception("Guarded audio mux recovery stopped for %s; job remains for attention", job_id)
    finally:
        if claimed:
            try:
                _release_mux_recovery_claim(job_id, owner)
            except Exception:
                logger.exception("Could not release mux recovery claim for %s", job_id)
