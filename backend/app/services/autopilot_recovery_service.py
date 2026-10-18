from __future__ import annotations

import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.core.config import Settings
from app.models.media_studio import (
    ClipOperation,
    ClipOperationStatus,
    KeyframeFidelityStatus,
    MediaAsset,
    MediaAssetKind,
    MediaAssetReviewStatus,
    MediaStudioJob,
    MediaStudioJobStage,
    VideoClipAsset,
)
from app.services.media_studio_job_service import media_studio_job_store


class AutopilotRecoveryError(RuntimeError):
    pass


_CRITICAL_IDENTITY_CHECKS = {
    "character_identity",
    "wardrobe",
    "supporting_subjects",
}


def _status_value(value) -> str:
    return str(getattr(value, "value", value) or "").upper()


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise AutopilotRecoveryError(
            "Controlled-motion recovery requires imageio-ffmpeg. Run pip install -r requirements.txt."
        ) from exc


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "ffmpeg failed").strip()
        raise AutopilotRecoveryError(message[-1800:])


def _salvage_detail(*, mode: str, shot_number: int, attempt: int, source_asset_id: str, issues: list[str]) -> dict:
    return {
        "outcome": "AI_SALVAGED",
        "recovery_mode": mode,
        "shot_number": shot_number,
        "generation_attempt": attempt,
        "source_asset_id": source_asset_id,
        "issues": list(issues),
        "recovered_at": datetime.now(timezone.utc).isoformat(),
    }


def salvage_keyframe_for_autopilot(job_id: str, shot_number: int) -> MediaStudioJob:
    """Convert an exhausted keyframe into an explicitly AI-salvaged continuation asset.

    This is intentionally not a human/creator override. If the failed report contains a
    critical identity mismatch, the canonical reference image is used as the safest
    starting frame and Veo receives the original storyboard action/camera instruction.
    Otherwise the best latest generated keyframe is retained. The audit trail records
    AI_SALVAGED so final human review can see that recovery was used.
    """

    job = media_studio_job_store.get(job_id)
    if not job.result or not job.result.reference_asset:
        raise AutopilotRecoveryError("A canonical reference is required before keyframe recovery.")

    current = next((asset for asset in job.result.keyframes if asset.shot_number == shot_number), None)
    if current is None or current.fidelity_report is None:
        raise AutopilotRecoveryError(f"Storyboard keyframe {shot_number} is unavailable for AI recovery.")

    report = current.fidelity_report.model_copy(deep=True)
    failed_checks = [
        check.key
        for check in report.checks
        if _status_value(check.status) not in {"PASS", "OK"}
    ]
    identity_critical = any(key in _CRITICAL_IDENTITY_CHECKS for key in failed_checks)
    reference = job.result.reference_asset
    now = datetime.now(timezone.utc)

    if identity_critical:
        salvaged = MediaAsset(
            asset_id=f"keyframe_salvage_{uuid4().hex}",
            kind=MediaAssetKind.KEYFRAME,
            shot_number=shot_number,
            created_at=now,
            model="reviveai-canonical-reference-fallback",
            mime_type=reference.mime_type,
            filename=reference.filename,
            asset_url="",
            prompt=(
                "Autonomous recovery: use the locked canonical identity as the starting frame; "
                "apply the original storyboard action and camera direction during animation."
            ),
            review_status=MediaAssetReviewStatus.APPROVED,
            source_reference_asset_id=reference.asset_id,
            generation_attempt=current.generation_attempt,
            review_note="AI_SALVAGED: canonical-reference fallback after repeated storyboard-fidelity failures.",
            fidelity_report=report,
        )
    else:
        salvaged = current.model_copy(deep=True)
        salvaged.asset_id = f"keyframe_salvage_{uuid4().hex}"
        salvaged.created_at = now
        salvaged.review_status = MediaAssetReviewStatus.APPROVED
        salvaged.review_note = "AI_SALVAGED: best available keyframe retained after autonomous shot-replan attempts."

    salvaged.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{salvaged.asset_id}"
    assert salvaged.fidelity_report is not None
    salvaged.fidelity_report.status = KeyframeFidelityStatus.ADAPTATION_ACCEPTED
    salvaged.fidelity_report.creator_override = False
    salvaged.fidelity_report.corrective_instruction = None
    salvaged.fidelity_report.methodology_notice = (
        "Autopilot autonomous recovery exhausted literal storyboard-fidelity generation. "
        "This keyframe is AI_SALVAGED, not human-approved; the finished video still requires final human approval."
    )
    if "AI_SALVAGED after autonomous shot replan." not in salvaged.fidelity_report.issues:
        salvaged.fidelity_report.issues.append("AI_SALVAGED after autonomous shot replan.")

    job.result.keyframes = [asset for asset in job.result.keyframes if asset.shot_number != shot_number] + [salvaged]
    job.result.keyframes.sort(key=lambda asset: asset.shot_number or 0)
    job.result.shot_operations.pop(shot_number, None)
    job.result.animation_ready = False

    detail = dict(job.detail or {})
    actors = dict(detail.get("keyframe_approval_actor") or {})
    actors[str(shot_number)] = "AI"
    salvaged_map = dict(detail.get("ai_salvaged_keyframes") or {})
    salvaged_map[str(shot_number)] = _salvage_detail(
        mode="CANONICAL_REFERENCE_FALLBACK" if identity_critical else "SHOT_REPLAN",
        shot_number=shot_number,
        attempt=current.generation_attempt,
        source_asset_id=current.asset_id,
        issues=list(report.issues),
    )
    detail.update({
        "keyframe_approval_actor": actors,
        "ai_salvaged_keyframes": salvaged_map,
        "autopilot_recovery_mode": "KEYFRAME_AI_SALVAGE",
    })
    job.detail = detail
    job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
    job.message = f"Shot {shot_number} AI-salvaged; continuing production without intermediate human approval"
    media_studio_job_store.save(job)
    return media_studio_job_store.get(job_id)


def create_controlled_motion_fallback(job_id: str, shot_number: int, settings: Settings) -> MediaStudioJob:
    """Create a deterministic motion clip from the recovered keyframe.

    Used only after Veo generation/review has exhausted its automatic attempts. The
    fallback deliberately favors continuity and completion over ambitious motion.
    """

    job = media_studio_job_store.get(job_id)
    if not job.result:
        raise AutopilotRecoveryError("Media Studio result is unavailable.")

    keyframe = next((asset for asset in job.result.keyframes if asset.shot_number == shot_number), None)
    shot = next((item for item in job.result.source_snapshot.storyboard.shots if item.shot_number == shot_number), None)
    if keyframe is None or shot is None:
        raise AutopilotRecoveryError(f"Shot {shot_number} does not have a recoverable keyframe/storyboard pair.")

    source_path, _ = media_studio_job_store.asset_path(job_id, keyframe.asset_id)
    if not source_path.exists():
        raise AutopilotRecoveryError(f"Recovered keyframe file for shot {shot_number} is unavailable.")

    width = int(settings.assembly_render_width)
    height = int(settings.assembly_render_height)
    fps = int(settings.assembly_frame_rate)
    duration = max(4.0, float(math.ceil(float(shot.duration_seconds))))
    assets_dir = media_studio_job_store.assets_dir(job_id)
    asset_id = f"clip_salvage_{uuid4().hex}"
    filename = f"{asset_id}.mp4"
    destination = assets_dir / filename
    ffmpeg = _ffmpeg_executable()

    # Centered, restrained Ken Burns motion. The output is silent because final
    # assembly/audio finishing owns the coherent soundtrack later in the pipeline.
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,"
        f"zoompan=z='min(1.0+0.0007*on,1.055)':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps},format=yuv420p"
    )
    _run([
        ffmpeg,
        "-y",
        "-loop", "1",
        "-framerate", str(fps),
        "-i", str(source_path),
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-an",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(destination),
    ])

    existing = next((clip for clip in job.result.video_clips if clip.shot_number == shot_number), None)
    generation_attempt = (existing.generation_attempt + 1) if existing else max(1, keyframe.generation_attempt)
    clip = VideoClipAsset(
        asset_id=asset_id,
        shot_number=shot_number,
        created_at=datetime.now(timezone.utc),
        model="reviveai-controlled-motion-fallback",
        mime_type="video/mp4",
        filename=filename,
        asset_url=f"/api/v1/youtube/media-jobs/{job_id}/assets/{asset_id}",
        prompt=(
            "AI_SALVAGED controlled-motion fallback: preserve the recovered keyframe exactly, "
            "use restrained camera motion, and defer narrative action to captions/voiceover when necessary."
        ),
        intended_duration_seconds=float(shot.duration_seconds),
        generated_duration_seconds=int(math.ceil(duration)),
        source_keyframe_asset_id=keyframe.asset_id,
        gcs_uri=None,
        review_status=MediaAssetReviewStatus.APPROVED,
        generation_attempt=generation_attempt,
        review_note="AI_SALVAGED: deterministic controlled-motion fallback after exhausted Veo review/generation.",
    )

    now = datetime.now(timezone.utc)
    job.result.video_clips = [item for item in job.result.video_clips if item.shot_number != shot_number] + [clip]
    job.result.video_clips.sort(key=lambda item: item.shot_number)
    job.result.clip_operations[shot_number] = ClipOperation(
        shot_number=shot_number,
        status=ClipOperationStatus.READY,
        message=f"Shot {shot_number} recovered with controlled motion",
        started_at=now,
        updated_at=now,
        target_generation_attempt=generation_attempt,
        previous_review_status=existing.review_status if existing else None,
        error=None,
        updated_asset_id=asset_id,
    )

    detail = dict(job.detail or {})
    actors = dict(detail.get("clip_approval_actor") or {})
    actors[str(shot_number)] = "AI"
    reviews = dict(detail.get("ai_clip_reviews") or {})
    reviews[str(shot_number)] = {
        "decision": "PASS",
        "summary": "AI_SALVAGED controlled-motion fallback preserves the approved visual identity and keeps production moving.",
        "issues": [],
        "corrective_instruction": None,
        "evaluated_at": now.isoformat(),
        "model": "reviveai-autonomous-recovery",
        "outcome": "AI_SALVAGED",
        "recovery_mode": "KEYFRAME_MOTION_FALLBACK",
    }
    salvaged_clips = dict(detail.get("ai_salvaged_clips") or {})
    salvaged_clips[str(shot_number)] = _salvage_detail(
        mode="KEYFRAME_MOTION_FALLBACK",
        shot_number=shot_number,
        attempt=generation_attempt,
        source_asset_id=keyframe.asset_id,
        issues=[],
    )
    exhausted: list[int] = []
    for value in list(detail.get("ai_review_exhausted_clips") or []):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed != shot_number:
            exhausted.append(parsed)
    detail.update({
        "clip_approval_actor": actors,
        "ai_clip_reviews": reviews,
        "ai_salvaged_clips": salvaged_clips,
        "ai_review_exhausted_clips": exhausted,
        "autopilot_recovery_mode": "CONTROLLED_MOTION_FALLBACK",
    })
    job.detail = detail
    job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
    job.message = f"Shot {shot_number} AI-salvaged with controlled motion; continuing to assembly"
    media_studio_job_store.save(job)
    return media_studio_job_store.get(job_id)
