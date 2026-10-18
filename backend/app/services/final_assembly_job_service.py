from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.final_assembly import (
    AssemblyAsset,
    AssemblyAssetKind,
    AssemblyTimelineItem,
    FinalAssemblyJob,
    FinalAssemblyJobStage,
    FinalAssemblyResult,
    FinalAssemblyReviewStatus,
)
from app.models.media_studio import MediaAssetReviewStatus, MediaStudioJobStage
from app.services.media_studio_job_service import media_studio_job_store
from app.services.production_brief_job_service import production_brief_job_store
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.runtime_artifact_store import RuntimeArtifactStore

logger = logging.getLogger(__name__)


class FinalAssemblyJobNotFoundError(KeyError):
    pass


class FinalAssemblyError(RuntimeError):
    pass


class FinalAssemblyJobStore:
    """Final Assembly jobs with Firestore metadata and GCS artifact durability."""

    def __init__(self, checkpoint_root: str):
        self._jobs: TenantScopedDict[str, FinalAssemblyJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "final_assembly"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("final_assembly_jobs")
        self._artifacts = RuntimeArtifactStore("final_assembly")

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
    def _validate_payload(payload: dict | None) -> Optional[FinalAssemblyJob]:
        if not payload:
            return None
        try:
            return FinalAssemblyJob.model_validate(payload)
        except Exception:
            return None

    def _sync_artifacts(self, job: FinalAssemblyJob) -> None:
        if not job.result:
            return
        assets = [job.result.final_video]
        if job.result.subtitles:
            assets.append(job.result.subtitles)
        for asset in assets:
            path = self.assets_dir(job.job_id) / asset.filename
            if not path.exists():
                if asset.gcs_uri:
                    continue
                raise FileNotFoundError(f"Final Assembly artifact is missing from the local cache: {asset.filename}")
            uri = self._artifacts.upload_file(
                path, owner_id=job.job_id, relative_path=f"assets/{asset.filename}", content_type=asset.mime_type
            )
            if uri:
                asset.gcs_uri = uri

    def _persist_local(self, job: FinalAssemblyJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, job: FinalAssemblyJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: FinalAssemblyJob) -> None:
        artifact_error: Exception | None = None
        cloud_error: Exception | None = None
        try:
            self._sync_artifacts(job)
        except Exception as exc:
            artifact_error = exc
            logger.exception("Could not mirror Final Assembly artifacts for %s to GCS", job.job_id)
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Final Assembly job %s to Firestore", job.job_id)
        self._persist_local(job)
        if get_settings().app_env.strip().lower() in {"production", "prod"}:
            if artifact_error is not None:
                raise RuntimeError("Durable GCS artifact persistence failed for the Final Assembly job") from artifact_error
            if cloud_error is not None:
                raise RuntimeError("Durable Firestore persistence failed for the Final Assembly job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[FinalAssemblyJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read Final Assembly job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[FinalAssemblyJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return FinalAssemblyJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load local Final Assembly checkpoint %s", job_id)
            return None

    def _backfill_cloud(self, job: FinalAssemblyJob) -> None:
        try:
            self._sync_artifacts(job)
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill Final Assembly job %s to cloud persistence", job.job_id)

    def _load(self, job_id: str) -> Optional[FinalAssemblyJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud
        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    def create(self, media_job_id: str) -> FinalAssemblyJob:
        media_job = media_studio_job_store.get(media_job_id)
        if media_job.stage != MediaStudioJobStage.READY_FOR_ASSEMBLY or not media_job.result or not media_job.result.assembly_ready:
            raise ValueError("All Veo clips must be pipeline-approved before starting M2C final assembly.")
        approved = [clip for clip in media_job.result.video_clips if clip.review_status == MediaAssetReviewStatus.APPROVED]
        if len(approved) < media_job.result.required_clips:
            raise ValueError("Every required Veo clip must be approved before final assembly.")
        now = datetime.now(timezone.utc)
        job = FinalAssemblyJob(
            job_id=f"assembly_{uuid4().hex}",
            media_job_id=media_job_id,
            production_brief_job_id=media_job.production_brief_job_id,
            channel_id=media_job.channel_id,
            stage=FinalAssemblyJobStage.QUEUED,
            message="Final Short assembly queued",
            progress_current=0,
            progress_total=len(media_job.result.source_snapshot.storyboard.shots) + 2,
            created_at=now,
            updated_at=now,
            detail={"captions": "burned-in on-screen text", "audio_mode": "SILENT_MASTER"},
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> FinalAssemblyJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None:
                raise FinalAssemblyJobNotFoundError(job_id)
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def latest_for_media_job(self, media_job_id: str) -> Optional[FinalAssemblyJob]:
        """Return the newest tenant-owned assembly across cloud/local/in-memory state."""
        candidates: Dict[str, FinalAssemblyJob] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.media_job_id == media_job_id:
                    candidates[loaded.job_id] = loaded
        except Exception:
            logger.exception("Could not list Final Assembly jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("*/job.json"):
            loaded = self._load_local(path.parent.name)
            if loaded and loaded.media_job_id == media_job_id:
                candidates[loaded.job_id] = loaded
                if self._load_cloud(loaded.job_id) is None:
                    self._backfill_cloud(loaded)

        with self._lock:
            for item in self._jobs.values():
                if item.media_job_id == media_job_id:
                    candidates[item.job_id] = item.model_copy(deep=True)

        if not candidates:
            return None
        latest = max(candidates.values(), key=lambda item: (item.updated_at, item.created_at, item.job_id))
        return self.get(latest.job_id)

    def save(self, job: FinalAssemblyJob) -> None:
        job.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)

    def fail(self, job_id: str, message: str) -> None:
        job = self.get(job_id)
        job.stage = FinalAssemblyJobStage.FAILED
        job.message = "Final assembly paused"
        job.error = message
        self.save(job)

    def approve(
        self,
        job_id: str,
        *,
        actor: str = "HUMAN",
        review_summary: Optional[str] = None,
    ) -> FinalAssemblyJob:
        job = self.get(job_id)
        if job.stage != FinalAssemblyJobStage.COMPLETED or not job.result:
            raise ValueError("Render the final Short before approving it.")
        actor = (actor or "HUMAN").upper()
        job.result.review_status = FinalAssemblyReviewStatus.APPROVED
        job.result.reviewed_at = datetime.now(timezone.utc)
        job.stage = FinalAssemblyJobStage.DELIVERED
        job.detail = {
            **job.detail,
            "approval_actor": actor,
            "approval_review_summary": review_summary,
        }
        job.message = (
            "Visual master AI-reviewed and ready for audio finishing"
            if actor == "AI"
            else "Visual master human-approved and ready for audio finishing"
        )
        self.save(job)
        return self.get(job_id)

    def asset_path(self, job_id: str, asset_id: str) -> tuple[Path, str]:
        job = self.get(job_id)
        if not job.result:
            raise FinalAssemblyJobNotFoundError(asset_id)
        assets = [job.result.final_video]
        if job.result.subtitles:
            assets.append(job.result.subtitles)
        asset = next((item for item in assets if item.asset_id == asset_id), None)
        if not asset:
            raise FinalAssemblyJobNotFoundError(asset_id)
        path = self.assets_dir(job_id) / asset.filename
        if not path.exists():
            self._artifacts.ensure_local(
                path, owner_id=job_id, relative_path=f"assets/{asset.filename}", gcs_uri=asset.gcs_uri
            )
        if not path.exists():
            raise FinalAssemblyJobNotFoundError(asset_id)
        return path, asset.mime_type


final_assembly_job_store = FinalAssemblyJobStore(get_settings().content_dna_checkpoint_dir)


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise FinalAssemblyError("M2C.1.2 requires imageio-ffmpeg. Run pip install -r requirements.txt.") from exc


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-1800:]
        raise FinalAssemblyError(f"FFmpeg could not render the final Short. {tail}")


def _timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(path: Path, shots) -> bool:
    """Generate readable phrase-level *approximate* cues from storyboard timing.

    These timings are evenly distributed, not speech-aligned transcription.
    Keep the entire narration in the exported SRT without truncation.
    """
    cursor = 0.0
    rows: list[str] = []
    index = 1
    for shot in shots:
        text = " ".join((shot.voiceover_or_dialogue or shot.on_screen_text or "").split())
        start = cursor
        duration = max(0.01, float(shot.duration_seconds))
        cursor += duration
        if not text:
            continue
        words = text.split()
        # Prevent rapid unreadable captions on short shots: prefer a single
        # cue if a shot cannot support at least 1.2 seconds per phrase.
        pieces = max(1, min((len(words) + 5) // 6, int(duration / 1.2)))
        for part in range(pieces):
            lo = (part * len(words)) // pieces
            hi = ((part + 1) * len(words)) // pieces
            cue = " ".join(words[lo:hi])
            cue_start = start + duration * part / pieces
            cue_end = start + duration * (part + 1) / pieces
            rows.extend([str(index), f"{_timestamp(cue_start)} --> {_timestamp(cue_end)}", cue, ""])
            index += 1
    if not rows:
        return False
    path.write_text("\n".join(rows), encoding="utf-8")
    return True


def _caption_font(size: int):
    """Load a scalable bold font or fail, never silently use bitmap-sized text."""
    from PIL import ImageFont
    candidates = (
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    raise FinalAssemblyError(
        "Cannot load a scalable bold caption font. Install DejaVu Sans (e.g. fonts-dejavu-core) "
        "in the rendering image; refusing to make unreadably small text."
    )


def _make_overlay(path: Path, text: str, width: int, height: int) -> bool:
    text = " ".join(str(text or "").split())
    if not text:
        return False
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        raise FinalAssemblyError("Pillow is required for caption overlays. Install it using requirements.txt.") from exc

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    maximum_width = int(width * 0.82)
    max_size = max(44, round(width * 0.082))
    min_size = max(34, round(width * 0.055))

    def wrap_words(font, value):
        lines = []
        current = ""
        for word in value.split():
            trial = f"{current} {word}".strip()
            if current and draw.textbbox((0, 0), trial, font=font, stroke_width=2)[2] > maximum_width:
                lines.append(current)
                current = word
            else:
                current = trial
        if current:
            lines.append(current)
        return lines

    chosen = None
    for size in range(max_size, min_size - 1, -2):
        font = _caption_font(size)
        lines = wrap_words(font, text)
        if len(lines) <= 2 and all(draw.textbbox((0, 0), line, font=font)[2] <= maximum_width for line in lines):
            chosen = (font, lines)
            break
    if chosen is None:
        # Storyboard screen copy is a brief visual label, not a transcript.
        # Never shrink it to a microscopic font or clip half a sentence silently.
        font = _caption_font(min_size)
        lines = wrap_words(font, text)
        if len(lines) > 2:
            logger.warning("On-screen storyboard label shortened for legibility; complete narration remains in SRT")
            first = lines[0]
            remainder = " ".join(lines[1:])
            while remainder and draw.textbbox((0, 0), remainder + "…", font=font)[2] > maximum_width:
                remainder = remainder.rsplit(" ", 1)[0] if " " in remainder else ""
            lines = [first, remainder + "…"] if remainder else [first, "…"]
        chosen = (font, lines)

    font, lines = chosen
    spacing = max(6, int(font.size * 0.18))
    rendered = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), rendered, font=font, spacing=spacing, align="center", stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padding_x = max(18, int(width * 0.032))
    padding_y = max(12, int(width * 0.025))
    x = (width - tw) // 2 - bbox[0]
    # Keep subtitles above common Shorts bottom controls and below faces.
    center_y = int(height * 0.72)
    y = center_y - th // 2 - bbox[1]
    rect = (x + bbox[0] - padding_x, y + bbox[1] - padding_y,
            x + bbox[2] + padding_x, y + bbox[3] + padding_y)
    draw.rounded_rectangle(rect, radius=max(14, width // 36), fill=(5, 10, 25, 215))
    draw.multiline_text((x, y), rendered, font=font, fill=(255, 255, 255, 255),
                        spacing=spacing, align="center", stroke_width=max(2, width // 360),
                        stroke_fill=(0, 0, 0, 255))
    image.save(path)
    return True


def _render_segment(
    *, ffmpeg: str, source: Path, destination: Path, duration: float, overlay: Optional[Path], width: int, height: int, fps: int
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}"
    if overlay:
        command = [
            ffmpeg, "-y", "-i", str(source), "-loop", "1", "-i", str(overlay),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}",
            "-filter_complex", f"[0:v]{scale}[base];[base][1:v]overlay=0:0:format=auto[v]",
            "-map", "[v]", "-map", "2:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(destination),
        ]
    else:
        command = [
            ffmpeg, "-y", "-i", str(source), "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{duration:.3f}", "-vf", scale,
            "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-shortest", str(destination),
        ]
    _run(command)


def _concat_segments(ffmpeg: str, segments: list[Path], destination: Path, work_dir: Path) -> None:
    """Concatenate rendered segments without duplicating relative paths.

    FFmpeg resolves paths inside a concat manifest relative to the manifest's own
    directory.  The assembly workspace itself is usually configured as a relative
    path (for example ``.reviveai_checkpoints/.../work``).  Writing that full
    relative path into ``concat.txt`` therefore makes FFmpeg prepend the manifest
    directory a second time.  Keep manifest entries relative to ``work_dir`` (or
    absolute as a safe fallback) instead.
    """
    concat_file = work_dir / "concat.txt"
    work_dir_resolved = work_dir.resolve()
    manifest_lines: list[str] = []
    for item in segments:
        item_resolved = item.resolve()
        try:
            manifest_path = item_resolved.relative_to(work_dir_resolved).as_posix()
        except ValueError:
            manifest_path = item_resolved.as_posix()
        # FFmpeg concat files use single-quoted paths. Escape any literal quote.
        manifest_path = manifest_path.replace("'", "'\\''")
        manifest_lines.append(f"file '{manifest_path}'")

    concat_file.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    _run([
        ffmpeg, "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_file.resolve()), "-c", "copy", str(destination.resolve()),
    ])


def render_final_assembly(job_id: str, settings: Settings) -> None:
    store = final_assembly_job_store
    try:
        job = store.get(job_id)
        media_job = media_studio_job_store.get(job.media_job_id)
        production_job = production_brief_job_store.get(job.production_brief_job_id)
        if not media_job.result or not media_job.result.assembly_ready:
            raise FinalAssemblyError("Approved Veo clips are no longer assembly-ready.")
        if not production_job.result:
            raise FinalAssemblyError("Approved M2A production brief is unavailable.")

        ffmpeg = _ffmpeg_executable()
        work_dir = store.work_dir(job_id)
        assets_dir = store.assets_dir(job_id)
        width = settings.assembly_render_width
        height = settings.assembly_render_height
        fps = settings.assembly_frame_rate
        shots = sorted(media_job.result.source_snapshot.storyboard.shots, key=lambda item: item.shot_number)
        clips = {clip.shot_number: clip for clip in media_job.result.video_clips if clip.review_status == MediaAssetReviewStatus.APPROVED}
        segments: list[Path] = []
        timeline: list[AssemblyTimelineItem] = []

        job.stage = FinalAssemblyJobStage.PREPARING
        job.message = "Preparing approved Veo clips and storyboard timing"
        store.save(job)

        for index, shot in enumerate(shots, start=1):
            clip = clips.get(shot.shot_number)
            if not clip:
                raise FinalAssemblyError(f"Approved Veo clip for shot {shot.shot_number} is missing.")
            source_path, _ = media_studio_job_store.asset_path(job.media_job_id, clip.asset_id)
            overlay_path = work_dir / f"overlay-{shot.shot_number}.png"
            overlay = overlay_path if settings.assembly_burn_on_screen_text and _make_overlay(overlay_path, shot.on_screen_text, width, height) else None
            segment_path = work_dir / f"segment-{shot.shot_number:02d}.mp4"
            job = store.get(job_id)
            job.stage = FinalAssemblyJobStage.RENDERING
            job.message = f"Trimming and rendering shot {shot.shot_number} of {len(shots)}"
            job.progress_current = index
            job.detail = {**job.detail, "current_shot": shot.shot_number}
            store.save(job)
            _render_segment(
                ffmpeg=ffmpeg,
                source=source_path,
                destination=segment_path,
                duration=shot.duration_seconds,
                overlay=overlay,
                width=width,
                height=height,
                fps=fps,
            )
            segments.append(segment_path)
            timeline.append(
                AssemblyTimelineItem(
                    shot_number=shot.shot_number,
                    source_clip_asset_id=clip.asset_id,
                    source_generation_attempt=clip.generation_attempt,
                    storyboard_duration_seconds=shot.duration_seconds,
                    source_duration_seconds=clip.generated_duration_seconds,
                    output_duration_seconds=shot.duration_seconds,
                    on_screen_text=shot.on_screen_text,
                    voiceover_or_dialogue=shot.voiceover_or_dialogue,
                )
            )

        final_asset_id = f"final_{uuid4().hex}"
        final_filename = f"{final_asset_id}.mp4"
        final_path = assets_dir / final_filename
        _concat_segments(ffmpeg, segments, final_path, work_dir)

        subtitle_asset = None
        srt_path = assets_dir / f"{final_asset_id}.srt"
        if _write_srt(srt_path, shots):
            subtitle_id = f"subs_{uuid4().hex}"
            renamed = assets_dir / f"{subtitle_id}.srt"
            srt_path.replace(renamed)
            subtitle_asset = AssemblyAsset(
                asset_id=subtitle_id,
                kind=AssemblyAssetKind.SUBTITLES,
                created_at=datetime.now(timezone.utc),
                filename=renamed.name,
                mime_type="application/x-subrip",
                asset_url=f"/api/v1/youtube/assembly-jobs/{job_id}/assets/{subtitle_id}",
            )

        result = FinalAssemblyResult(
            media_job_id=job.media_job_id,
            production_brief_job_id=job.production_brief_job_id,
            working_title=media_job.result.source_snapshot.working_title,
            rendered_at=datetime.now(timezone.utc),
            total_duration_seconds=round(sum(item.output_duration_seconds for item in timeline), 3),
            timeline=timeline,
            final_video=AssemblyAsset(
                asset_id=final_asset_id,
                kind=AssemblyAssetKind.FINAL_VIDEO,
                created_at=datetime.now(timezone.utc),
                filename=final_filename,
                mime_type="video/mp4",
                asset_url=f"/api/v1/youtube/assembly-jobs/{job_id}/assets/{final_asset_id}",
            ),
            subtitles=subtitle_asset,
            publishing=production_job.result.publishing.model_copy(deep=True),
            captions_burned_in=settings.assembly_burn_on_screen_text,
        )
        job = store.get(job_id)
        job.result = result
        job.stage = FinalAssemblyJobStage.COMPLETED
        job.message = "Final Short rendered; AI visual-master review pending"
        job.progress_current = job.progress_total
        job.detail = {**job.detail, "current_shot": None, "ffmpeg": ffmpeg}
        job.error = None
        store.save(job)
    except Exception as exc:
        logger.exception("Final Short assembly failed")
        message = str(exc) if isinstance(exc, FinalAssemblyError) else "ReviveAI could not finish the final Short assembly."
        store.fail(job_id, message)
