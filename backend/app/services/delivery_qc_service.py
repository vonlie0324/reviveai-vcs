from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.audio_finishing import (
    AudioFinishingJobStage,
    AudioFinishingReviewStatus,
    MusicSource,
    TrendingMusicRenderMode,
)
from app.models.delivery_qc import (
    DeliveryQcAcknowledgment,
    DeliveryQcCheck,
    DeliveryQcCheckStatus,
    DeliveryQcOverallStatus,
    DeliveryQcReport,
)
from app.models.final_assembly import FinalAssemblyReviewStatus
from app.services.audio_finishing_job_service import (
    AudioFinishingJobNotFoundError,
    audio_finishing_job_store,
)
from app.services.final_assembly_job_service import FinalAssemblyJobNotFoundError, final_assembly_job_store
from app.services.firestore_job_repository import FirestoreJobRepository

logger = logging.getLogger(__name__)


class DeliveryQcError(RuntimeError):
    pass


class DeliveryQcReportNotFoundError(KeyError):
    pass


class DeliveryQcStore:
    """Delivery QC reports with Firestore durability and local mirroring."""

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "delivery_qc"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._reports: TenantScopedDict[str, DeliveryQcReport] = TenantScopedDict()
        self._cloud = FirestoreJobRepository("delivery_qc_reports")

    def _path(self, audio_job_id: str) -> Path:
        return tenant_scoped_root(self._root) / audio_job_id / "latest.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[DeliveryQcReport]:
        if not payload:
            return None
        try:
            return DeliveryQcReport.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, report: DeliveryQcReport) -> None:
        path = self._path(report.audio_job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, report: DeliveryQcReport) -> None:
        self._cloud.save(report.audio_job_id, report.model_dump(mode="json"))

    def save(self, report: DeliveryQcReport) -> None:
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(report)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Delivery QC report %s to Firestore", report.report_id)
        self._persist_local(report)
        with self._lock:
            self._reports[report.audio_job_id] = report.model_copy(deep=True)
        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the Delivery QC report") from cloud_error

    def _load_cloud(self, audio_job_id: str) -> Optional[DeliveryQcReport]:
        try:
            return self._validate_payload(self._cloud.load(audio_job_id))
        except Exception:
            logger.exception("Could not read Delivery QC report for %s from Firestore", audio_job_id)
            return None

    def _load_local(self, audio_job_id: str) -> Optional[DeliveryQcReport]:
        path = self._path(audio_job_id)
        if not path.exists():
            return None
        try:
            return DeliveryQcReport.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.exception("Could not load local Delivery QC report for %s", audio_job_id)
            raise DeliveryQcError("Saved delivery QC report could not be read.") from exc

    def get(self, audio_job_id: str) -> DeliveryQcReport:
        with self._lock:
            cached = self._reports.get(audio_job_id)
            if cached:
                return cached.model_copy(deep=True)
        report = self._load_cloud(audio_job_id)
        if report is None:
            report = self._load_local(audio_job_id)
            if report is not None:
                try:
                    self._persist_cloud(report)
                except Exception:
                    logger.exception("Could not backfill Delivery QC report for %s to Firestore", audio_job_id)
        if report is None:
            raise DeliveryQcReportNotFoundError(audio_job_id)
        with self._lock:
            self._reports[audio_job_id] = report
        return report.model_copy(deep=True)


delivery_qc_store = DeliveryQcStore(get_settings().content_dna_checkpoint_dir)


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise DeliveryQcError("M2C.3 requires imageio-ffmpeg. Run pip install -r requirements.txt.") from exc


def _run_capture(command: list[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DeliveryQcError("FFmpeg delivery verification timed out.") from exc


def _parse_duration(text: str) -> Optional[float]:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_probe(ffmpeg: str, path: Path) -> dict:
    result = _run_capture([ffmpeg, "-hide_banner", "-i", str(path.resolve())], timeout=30)
    text = (result.stderr or "") + "\n" + (result.stdout or "")
    duration = _parse_duration(text)

    video_line = next((line for line in text.splitlines() if " Video: " in line), "")
    audio_line = next((line for line in text.splitlines() if " Audio: " in line), "")

    video_codec = None
    audio_codec = None
    width = None
    height = None
    fps = None
    sample_rate = None
    channels = None

    if video_line:
        codec_match = re.search(r"Video:\s*([^,\s]+)", video_line)
        size_match = re.search(r"(?:^|[,\s])(\d{2,5})x(\d{2,5})(?:[,\s])", video_line)
        fps_match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*fps", video_line)
        video_codec = codec_match.group(1).lower() if codec_match else None
        if size_match:
            width, height = int(size_match.group(1)), int(size_match.group(2))
        fps = float(fps_match.group(1)) if fps_match else None

    if audio_line:
        codec_match = re.search(r"Audio:\s*([^,\s]+)", audio_line)
        sample_match = re.search(r"(\d+)\s*Hz", audio_line)
        audio_codec = codec_match.group(1).lower() if codec_match else None
        sample_rate = int(sample_match.group(1)) if sample_match else None
        if "stereo" in audio_line.lower():
            channels = "stereo"
        elif "mono" in audio_line.lower():
            channels = "mono"

    return {
        "duration_seconds": duration,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "width": width,
        "height": height,
        "fps": fps,
        "sample_rate": sample_rate,
        "channels": channels,
        "has_video": bool(video_line),
        "has_audio": bool(audio_line),
        "raw": text,
    }


def _decode_check(ffmpeg: str, path: Path) -> tuple[bool, str]:
    result = _run_capture([
        ffmpeg, "-v", "error", "-i", str(path.resolve()), "-map", "0:v?", "-map", "0:a?", "-f", "null", "-"
    ])
    errors = (result.stderr or result.stdout or "").strip()
    return result.returncode == 0 and not errors, errors[-1200:]


def _analyze_loudness(ffmpeg: str, path: Path, target_lufs: float) -> dict:
    result = _run_capture([
        ffmpeg,
        "-hide_banner", "-nostats", "-i", str(path.resolve()), "-vn",
        "-af", f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11:print_format=json",
        "-f", "null", "-",
    ])
    text = result.stderr or ""
    blocks = re.findall(r"\{[\s\S]*?\}", text)
    payload = None
    for block in reversed(blocks):
        if '"input_i"' in block:
            try:
                payload = json.loads(block)
                break
            except json.JSONDecodeError:
                continue
    if not payload:
        return {"integrated_lufs": None, "true_peak_dbfs": None, "lra": None}

    def number(key: str) -> Optional[float]:
        raw = payload.get(key)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "integrated_lufs": number("input_i"),
        "true_peak_dbfs": number("input_tp"),
        "lra": number("input_lra"),
    }


def _analyze_silence(ffmpeg: str, path: Path) -> dict:
    result = _run_capture([
        ffmpeg, "-hide_banner", "-nostats", "-i", str(path.resolve()), "-vn",
        "-af", "silencedetect=noise=-45dB:d=1.0", "-f", "null", "-",
    ])
    text = result.stderr or ""
    durations = [float(value) for value in re.findall(r"silence_duration:\s*([0-9]+(?:\.[0-9]+)?)", text)]
    return {
        "long_silence_count": len(durations),
        "max_silence_seconds": max(durations, default=0.0),
    }


def _check(
    checks: list[DeliveryQcCheck],
    *,
    key: str,
    category: str,
    label: str,
    status: DeliveryQcCheckStatus,
    summary: str,
    detail: Optional[str] = None,
    metric: Optional[str] = None,
    expected: Optional[str] = None,
) -> None:
    checks.append(DeliveryQcCheck(
        key=key,
        category=category,
        label=label,
        status=status,
        summary=summary,
        detail=detail,
        metric=metric,
        expected=expected,
    ))


def run_delivery_qc(audio_job_id: str, settings: Settings) -> DeliveryQcReport:
    try:
        audio_job = audio_finishing_job_store.get(audio_job_id)
    except AudioFinishingJobNotFoundError as exc:
        raise DeliveryQcReportNotFoundError(audio_job_id) from exc

    if not audio_job.result:
        raise DeliveryQcError("The selected audio master has not finished rendering.")

    try:
        assembly_job = final_assembly_job_store.get(audio_job.assembly_job_id)
    except FinalAssemblyJobNotFoundError as exc:
        raise DeliveryQcError("The approved visual master checkpoint is unavailable.") from exc
    if not assembly_job.result:
        raise DeliveryQcError("The approved visual master is unavailable.")

    result = audio_job.result
    checks: list[DeliveryQcCheck] = []
    metrics: dict = {}
    ffmpeg = _ffmpeg_executable()

    approved_audio = audio_job.stage == AudioFinishingJobStage.DELIVERED and result.review_status == AudioFinishingReviewStatus.APPROVED
    audio_actor = str(audio_job.detail.get("approval_actor") or "UNKNOWN").upper()
    _check(
        checks,
        key="audio_master_approval",
        category="Lineage",
        label="Audio master review gate",
        status=DeliveryQcCheckStatus.PASS if approved_audio else DeliveryQcCheckStatus.FAIL,
        summary=(
            f"Audio master v{audio_job.version_number} passed {audio_actor.lower()} review."
            if approved_audio
            else "The audio master has not passed the required review gate."
        ),
    )

    visual_approved = assembly_job.result.review_status == FinalAssemblyReviewStatus.APPROVED
    visual_detail = getattr(assembly_job, "detail", None) or {}
    visual_actor = str(visual_detail.get("approval_actor") or "UNKNOWN").upper()
    source_visual_id = str(audio_job.detail.get("source_visual_asset_id") or "")
    expected_visual_id = assembly_job.result.final_video.asset_id
    lineage_ok = visual_approved and source_visual_id == expected_visual_id and bool(audio_job.detail.get("visual_master_preserved"))
    _check(
        checks,
        key="visual_master_lineage",
        category="Lineage",
        label="Approved visual master preserved",
        status=DeliveryQcCheckStatus.PASS if lineage_ok else DeliveryQcCheckStatus.FAIL,
        summary=(f"Final mux traces back to the {visual_actor.lower()}-reviewed visual master without visual regeneration." if lineage_ok else "Visual-master lineage could not be verified."),
        metric=source_visual_id or "missing",
        expected=expected_visual_id,
    )

    delivery_path, _ = audio_finishing_job_store.asset_path(audio_job_id, result.delivery_video.asset_id)
    file_ok = delivery_path.exists() and delivery_path.stat().st_size > 1024
    _check(
        checks,
        key="delivery_asset",
        category="Technical",
        label="Delivery video exists",
        status=DeliveryQcCheckStatus.PASS if file_ok else DeliveryQcCheckStatus.FAIL,
        summary="Delivery master file is present and non-empty." if file_ok else "Delivery master file is missing or empty.",
        metric=f"{delivery_path.stat().st_size / (1024 * 1024):.2f} MB" if delivery_path.exists() else "missing",
    )

    probe = _parse_probe(ffmpeg, delivery_path) if file_ok else {}
    metrics["container"] = {key: value for key, value in probe.items() if key != "raw"}

    decode_ok, decode_error = _decode_check(ffmpeg, delivery_path) if file_ok else (False, "missing file")
    _check(
        checks,
        key="decode_integrity",
        category="Technical",
        label="Full-file decode integrity",
        status=DeliveryQcCheckStatus.PASS if decode_ok else DeliveryQcCheckStatus.FAIL,
        summary="FFmpeg decoded the complete master without media errors." if decode_ok else "FFmpeg reported a media decode problem.",
        detail=decode_error or None,
    )

    expected_duration = float(result.total_duration_seconds)
    actual_duration = probe.get("duration_seconds")
    duration_delta = abs(actual_duration - expected_duration) if actual_duration is not None else None
    duration_ok = duration_delta is not None and duration_delta <= settings.delivery_qc_duration_tolerance_seconds
    metrics["duration_delta_seconds"] = duration_delta
    _check(
        checks,
        key="duration",
        category="Technical",
        label="Duration matches approved timeline",
        status=DeliveryQcCheckStatus.PASS if duration_ok else DeliveryQcCheckStatus.FAIL,
        summary="Container duration matches the approved timeline." if duration_ok else "Container duration differs from the approved timeline.",
        metric=f"{actual_duration:.3f}s" if actual_duration is not None else "unknown",
        expected=f"{expected_duration:.3f}s ± {settings.delivery_qc_duration_tolerance_seconds:.2f}s",
    )

    resolution_ok = probe.get("width") == settings.assembly_render_width and probe.get("height") == settings.assembly_render_height
    _check(
        checks,
        key="resolution",
        category="Technical",
        label="Portrait master resolution",
        status=DeliveryQcCheckStatus.PASS if resolution_ok else DeliveryQcCheckStatus.FAIL,
        summary="Delivery master uses the configured portrait resolution." if resolution_ok else "Delivery master resolution does not match the configured assembly master.",
        metric=f"{probe.get('width')}×{probe.get('height')}" if probe.get("width") else "unknown",
        expected=f"{settings.assembly_render_width}×{settings.assembly_render_height}",
    )

    fps = probe.get("fps")
    fps_ok = fps is not None and abs(fps - settings.assembly_frame_rate) <= 0.5
    _check(
        checks,
        key="frame_rate",
        category="Technical",
        label="Frame rate",
        status=DeliveryQcCheckStatus.PASS if fps_ok else DeliveryQcCheckStatus.WARN,
        summary="Frame rate matches the configured delivery master." if fps_ok else "Frame rate could not be confirmed exactly; review before delivery.",
        metric=f"{fps:.2f} fps" if fps is not None else "unknown",
        expected=f"{settings.assembly_frame_rate} fps",
    )

    video_codec_ok = str(probe.get("video_codec") or "").startswith("h264")
    audio_codec_ok = str(probe.get("audio_codec") or "").startswith("aac")
    _check(
        checks,
        key="codecs",
        category="Technical",
        label="Delivery codecs",
        status=DeliveryQcCheckStatus.PASS if video_codec_ok and audio_codec_ok else DeliveryQcCheckStatus.FAIL,
        summary="Master uses H.264 video with AAC audio." if video_codec_ok and audio_codec_ok else "Expected H.264 video and AAC audio were not both detected.",
        metric=f"video={probe.get('video_codec') or 'missing'} · audio={probe.get('audio_codec') or 'missing'}",
        expected="H.264 + AAC",
    )

    if result.audio_mix:
        mix_path, _ = audio_finishing_job_store.asset_path(audio_job_id, result.audio_mix.asset_id)
        mix_probe = _parse_probe(ffmpeg, mix_path) if mix_path.exists() else {}
        mix_duration = mix_probe.get("duration_seconds")
        av_delta = abs((actual_duration or 0.0) - (mix_duration or 0.0)) if actual_duration is not None and mix_duration is not None else None
        av_ok = av_delta is not None and av_delta <= settings.delivery_qc_duration_tolerance_seconds
        metrics["audio_mix_duration_seconds"] = mix_duration
        metrics["audio_video_delta_seconds"] = av_delta
        _check(
            checks,
            key="audio_video_alignment",
            category="Audio",
            label="Audio/video duration alignment",
            status=DeliveryQcCheckStatus.PASS if av_ok else DeliveryQcCheckStatus.FAIL,
            summary="Audio mix and delivery video durations are aligned." if av_ok else "Audio/video durations are not aligned within tolerance.",
            metric=f"Δ {av_delta:.3f}s" if av_delta is not None else "unknown",
            expected=f"≤ {settings.delivery_qc_duration_tolerance_seconds:.2f}s",
        )
    else:
        _check(
            checks,
            key="audio_video_alignment",
            category="Audio",
            label="Audio/video duration alignment",
            status=DeliveryQcCheckStatus.FAIL,
            summary="Rendered audio mix asset is missing.",
        )

    if probe.get("has_audio") and file_ok:
        loudness = _analyze_loudness(ffmpeg, delivery_path, settings.audio_target_lufs)
        silence = _analyze_silence(ffmpeg, delivery_path)
    else:
        loudness = {"integrated_lufs": None, "true_peak_dbfs": None, "lra": None}
        silence = {"long_silence_count": 0, "max_silence_seconds": 0.0}
    metrics["loudness"] = loudness
    metrics["silence"] = silence

    measured_lufs = loudness.get("integrated_lufs")
    lufs_delta = abs(measured_lufs - settings.audio_target_lufs) if measured_lufs is not None else None
    loudness_ok = lufs_delta is not None and lufs_delta <= settings.delivery_qc_loudness_tolerance_lufs
    loudness_status = DeliveryQcCheckStatus.PASS if loudness_ok else (DeliveryQcCheckStatus.WARN if measured_lufs is not None else DeliveryQcCheckStatus.FAIL)
    _check(
        checks,
        key="loudness",
        category="Audio",
        label="Integrated loudness",
        status=loudness_status,
        summary="Master loudness is within the delivery target window." if loudness_ok else "Master loudness is outside the preferred target window." if measured_lufs is not None else "Integrated loudness could not be measured.",
        metric=f"{measured_lufs:.1f} LUFS" if measured_lufs is not None else "unknown",
        expected=f"{settings.audio_target_lufs:.1f} ± {settings.delivery_qc_loudness_tolerance_lufs:.1f} LUFS",
    )

    true_peak = loudness.get("true_peak_dbfs")
    peak_ok = true_peak is not None and true_peak <= settings.delivery_qc_max_true_peak_dbfs
    peak_status = DeliveryQcCheckStatus.PASS if peak_ok else (DeliveryQcCheckStatus.FAIL if true_peak is not None and true_peak > -0.1 else DeliveryQcCheckStatus.WARN)
    _check(
        checks,
        key="true_peak",
        category="Audio",
        label="Peak / clipping safety",
        status=peak_status,
        summary="True peak remains below the configured ceiling." if peak_ok else "True peak is above the preferred ceiling; listen for clipping or harsh limiting." if true_peak is not None else "True peak could not be measured.",
        metric=f"{true_peak:.2f} dBTP" if true_peak is not None else "unknown",
        expected=f"≤ {settings.delivery_qc_max_true_peak_dbfs:.1f} dBTP",
    )

    max_silence = float(silence.get("max_silence_seconds") or 0.0)
    any_layer_enabled = result.options.music_enabled or result.options.voiceover_enabled or result.options.ambience_sfx_enabled
    silence_ok = not any_layer_enabled or max_silence <= settings.delivery_qc_max_unexpected_silence_seconds
    _check(
        checks,
        key="silence",
        category="Audio",
        label="Unexpected long silence",
        status=DeliveryQcCheckStatus.PASS if silence_ok else DeliveryQcCheckStatus.WARN,
        summary="No unexpected long-silence event was detected." if silence_ok else "A long quiet section was detected; preview the master before delivery.",
        metric=f"max {max_silence:.2f}s",
        expected=f"≤ {settings.delivery_qc_max_unexpected_silence_seconds:.1f}s when audio layers are enabled",
    )

    music_layer = next((layer for layer in result.layers if layer.key == "music"), None)
    if result.options.music_enabled:
        music_ok = bool(music_layer and music_layer.generated)
        _check(
            checks,
            key="music_layer",
            category="Audio",
            label="Background music layer",
            status=DeliveryQcCheckStatus.PASS if music_ok else DeliveryQcCheckStatus.FAIL,
            summary="Selected background music was rendered into the audio pipeline." if music_ok else "Music was enabled but no rendered music layer is recorded.",
            detail=music_layer.detail if music_layer else None,
        )
    else:
        _check(
            checks,
            key="music_layer",
            category="Audio",
            label="Background music layer",
            status=DeliveryQcCheckStatus.INFO,
            summary="Music is intentionally disabled for this version.",
        )

    if result.options.voiceover_enabled:
        expected_cues = [cue for cue in result.voiceover_cues if cue.text.strip()]
        synthesized = [cue for cue in expected_cues if cue.synthesized]
        if not expected_cues:
            voice_status = DeliveryQcCheckStatus.INFO
            voice_summary = "Voiceover is enabled, but the approved timeline contains no concise narration cue to synthesize."
        elif len(synthesized) == len(expected_cues):
            voice_status = DeliveryQcCheckStatus.PASS
            voice_summary = f"All {len(expected_cues)} expected narration cue(s) were synthesized."
        elif synthesized:
            voice_status = DeliveryQcCheckStatus.WARN
            voice_summary = f"{len(synthesized)} of {len(expected_cues)} expected narration cues were synthesized."
        else:
            voice_status = DeliveryQcCheckStatus.FAIL
            voice_summary = "Expected narration cues exist, but none were synthesized."
        _check(
            checks,
            key="voiceover",
            category="Audio",
            label="Voiceover completion",
            status=voice_status,
            summary=voice_summary,
        )
    else:
        _check(
            checks,
            key="voiceover",
            category="Audio",
            label="Voiceover completion",
            status=DeliveryQcCheckStatus.INFO,
            summary="Voiceover is intentionally disabled for this version.",
        )

    subtitle_expected = assembly_job.result.subtitles is not None
    subtitle_present = result.subtitles is not None
    captions_ok = assembly_job.result.captions_burned_in and (not subtitle_expected or subtitle_present)
    _check(
        checks,
        key="captions",
        category="Captions",
        label="Caption and on-screen text assets",
        status=DeliveryQcCheckStatus.PASS if captions_ok else DeliveryQcCheckStatus.FAIL,
        summary="Approved on-screen text remains burned into the visual master and subtitle assets are preserved." if captions_ok else "Expected caption/subtitle assets are incomplete.",
    )

    if result.effective_music_source == MusicSource.YOUTUBE_AUDIO_LIBRARY and result.selected_youtube_audio_library_track:
        track = result.selected_youtube_audio_library_track
        attribution_ok = True
        if track.attribution_required:
            attribution_ok = bool(track.attribution_text and track.attribution_text.strip() in result.publishing.description)
        _check(
            checks,
            key="music_rights",
            category="Rights",
            label="YouTube Audio Library rights metadata",
            status=DeliveryQcCheckStatus.PASS if attribution_ok else DeliveryQcCheckStatus.FAIL,
            summary=(
                "YouTube Audio Library license metadata is preserved and required attribution is present."
                if attribution_ok and track.attribution_required
                else "YouTube Audio Library license metadata is preserved; no attribution is marked as required."
                if attribution_ok
                else "Required YouTube music attribution is missing from the publishing description."
            ),
            detail=f"{track.title}{' · ' + track.artist if track.artist else ''}",
        )
    elif result.effective_music_source == MusicSource.TRENDING_LICENSED and result.selected_trending_track:
        track = result.selected_trending_track
        rights_ok = track.commercial_use_allowed and track.render_mode == TrendingMusicRenderMode.EMBEDDED and track.render_ready
        _check(
            checks,
            key="music_rights",
            category="Rights",
            label="Licensed music usage record",
            status=DeliveryQcCheckStatus.PASS if rights_ok else DeliveryQcCheckStatus.FAIL,
            summary="Commercial-use metadata and embedded-render permission are preserved." if rights_ok else "Selected licensed track no longer satisfies the recorded render-rights requirements.",
            detail=f"{track.provider or 'Provider'} · {track.license_reference or 'no license reference'}",
        )
    else:
        _check(
            checks,
            key="music_rights",
            category="Rights",
            label="Music rights metadata",
            status=DeliveryQcCheckStatus.PASS,
            summary="This version uses ReviveAI-generated music or has music disabled; no third-party music attribution is required.",
        )

    if result.warnings:
        _check(
            checks,
            key="render_warnings",
            category="Review",
            label="Audio render warnings",
            status=DeliveryQcCheckStatus.WARN,
            summary=f"{len(result.warnings)} render warning(s) remain for AI review.",
            detail=" ".join(result.warnings),
        )
    else:
        _check(
            checks,
            key="render_warnings",
            category="Review",
            label="Audio render warnings",
            status=DeliveryQcCheckStatus.PASS,
            summary="No audio-finishing warnings are recorded for this version.",
        )

    counts = {
        status: sum(1 for item in checks if item.status == status)
        for status in DeliveryQcCheckStatus
    }
    if counts[DeliveryQcCheckStatus.FAIL] > 0:
        overall = DeliveryQcOverallStatus.BLOCKED
    elif counts[DeliveryQcCheckStatus.WARN] > 0:
        overall = DeliveryQcOverallStatus.REVIEW
    else:
        overall = DeliveryQcOverallStatus.READY

    report = DeliveryQcReport(
        report_id=f"qc_{uuid4().hex}",
        audio_job_id=audio_job_id,
        assembly_job_id=audio_job.assembly_job_id,
        audio_version=audio_job.version_number,
        generated_at=datetime.now(timezone.utc),
        overall_status=overall,
        ready_for_delivery=overall != DeliveryQcOverallStatus.BLOCKED,
        pass_count=counts[DeliveryQcCheckStatus.PASS],
        warn_count=counts[DeliveryQcCheckStatus.WARN],
        fail_count=counts[DeliveryQcCheckStatus.FAIL],
        info_count=counts[DeliveryQcCheckStatus.INFO],
        source_visual_asset_id=source_visual_id or None,
        delivery_asset_id=result.delivery_video.asset_id,
        checks=checks,
        metrics=metrics,
    )
    delivery_qc_store.save(report)
    return report


def qc_allows_manual_delivery(report: DeliveryQcReport) -> bool:
    """Accept deterministic READY or same-report human acknowledgment of warnings."""
    if report.fail_count or report.overall_status == DeliveryQcOverallStatus.BLOCKED:
        return False
    if report.overall_status == DeliveryQcOverallStatus.READY:
        return True
    if report.overall_status != DeliveryQcOverallStatus.REVIEW:
        return False
    acknowledgment = report.human_acknowledgment
    return bool(
        acknowledgment
        and acknowledgment.report_id == report.report_id
        and acknowledgment.audio_version == report.audio_version
        and acknowledgment.delivery_asset_id == report.delivery_asset_id
        and acknowledgment.warning_keys == sorted(c.key for c in report.checks if c.status == DeliveryQcCheckStatus.WARN)
        and acknowledgment.acknowledged_by.strip()
    )


def acknowledge_delivery_qc_warnings(audio_job_id: str, report_id: str, actor: str) -> DeliveryQcReport:
    """Persist acknowledgment against the exact current warning set and media version."""
    if not actor.strip():
        raise DeliveryQcError("A verified user is required to acknowledge QC warnings.")
    report = delivery_qc_store.get(audio_job_id)
    if report.report_id != report_id:
        raise DeliveryQcError("This QC report is no longer current. Refresh before acknowledging.")
    from app.services.audio_finishing_job_service import audio_finishing_job_store
    job = audio_finishing_job_store.get(audio_job_id)
    if (not job.result or job.version_number != report.audio_version
            or job.result.delivery_video.asset_id != report.delivery_asset_id):
        raise DeliveryQcError("The audio master changed. Run a new QC review before acknowledgment.")
    if report.fail_count or report.overall_status == DeliveryQcOverallStatus.BLOCKED:
        raise DeliveryQcError("Blocking failures cannot be acknowledged for delivery.")
    if report.overall_status != DeliveryQcOverallStatus.REVIEW or report.warn_count == 0:
        raise DeliveryQcError("No review warnings require acknowledgment.")
    if qc_allows_manual_delivery(report):
        return report
    report.human_acknowledgment = DeliveryQcAcknowledgment(
        report_id=report.report_id,
        audio_version=report.audio_version,
        delivery_asset_id=report.delivery_asset_id,
        warning_keys=sorted(c.key for c in report.checks if c.status == DeliveryQcCheckStatus.WARN),
        acknowledged_by=actor,
        acknowledged_at=datetime.now(timezone.utc),
    )
    delivery_qc_store.save(report)
    return report
