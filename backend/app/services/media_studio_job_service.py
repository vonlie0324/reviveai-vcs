from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.media_studio import (
    KeyframeFidelityStatus,
    ClipOperation,
    ClipOperationStatus,
    MediaAssetReviewStatus,
    MediaSourceSnapshot,
    VideoGenerationCharge,
    VideoGenerationChargeStatus,
    ShotOperation,
    ShotOperationStatus,
    MediaStudioJob,
    MediaStudioJobStage,
    MediaStudioResult,
)
from app.models.production_brief import ProductionBriefJob, ProductionReviewStatus
from app.services.media_generation_service import MediaGenerationError, MediaGenerationService
from app.services.resource_scheduler_service import global_resource_scheduler
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.runtime_artifact_store import RuntimeArtifactStore

logger = logging.getLogger(__name__)


class MediaStudioJobNotFoundError(KeyError):
    pass


class MediaStudioJobStore:
    """Media Studio jobs with Firestore metadata and GCS artifact durability.

    The local checkpoint/assets tree remains a hot cache for ffmpeg and development.
    Firestore + GCS are authoritative across Cloud Run instance replacement.
    """

    def __init__(self, checkpoint_root: str):
        self._jobs: TenantScopedDict[str, MediaStudioJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "media_studio"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("media_studio_jobs")
        self._artifacts = RuntimeArtifactStore("media_studio")

    def _job_dir(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / job_id

    def assets_dir(self, job_id: str) -> Path:
        path = self._job_dir(job_id) / "assets"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _path(self, job_id: str) -> Path:
        return self._job_dir(job_id) / "job.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[MediaStudioJob]:
        if not payload:
            return None
        try:
            return MediaStudioJob.model_validate(payload)
        except Exception:
            return None

    def _sync_artifacts(self, job: MediaStudioJob) -> None:
        if not job.result:
            return
        assets = []
        if job.result.reference_asset:
            assets.append(job.result.reference_asset)
        assets.extend(job.result.keyframes)
        for asset in assets:
            path = self.assets_dir(job.job_id) / asset.filename
            if not path.exists():
                if getattr(asset, "gcs_uri", None):
                    continue
                raise FileNotFoundError(f"Media Studio artifact is missing from the local cache: {asset.filename}")
            uri = self._artifacts.upload_file(
                path, owner_id=job.job_id, relative_path=f"assets/{asset.filename}", content_type=asset.mime_type
            )
            if uri:
                asset.gcs_uri = uri

        # Veo already returns a durable provider GCS URI. Only mirror a clip when
        # a legacy/local clip has no cloud URI.
        for clip in job.result.video_clips:
            if clip.gcs_uri:
                continue
            path = self.assets_dir(job.job_id) / clip.filename
            if not path.exists():
                raise FileNotFoundError(f"Media Studio clip is missing from the local cache: {clip.filename}")
            uri = self._artifacts.upload_file(
                path, owner_id=job.job_id, relative_path=f"assets/{clip.filename}", content_type=clip.mime_type
            )
            if uri:
                clip.gcs_uri = uri

    def _persist_local(self, job: MediaStudioJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _persist_cloud(self, job: MediaStudioJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: MediaStudioJob) -> None:
        artifact_error: Exception | None = None
        cloud_error: Exception | None = None
        try:
            self._sync_artifacts(job)
        except Exception as exc:
            artifact_error = exc
            logger.exception("Could not mirror Media Studio artifacts for %s to GCS", job.job_id)
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Media Studio job %s to Firestore", job.job_id)
        self._persist_local(job)
        if get_settings().app_env.strip().lower() in {"production", "prod"}:
            if artifact_error is not None:
                raise RuntimeError("Durable GCS artifact persistence failed for the Media Studio job") from artifact_error
            if cloud_error is not None:
                raise RuntimeError("Durable Firestore persistence failed for the Media Studio job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[MediaStudioJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read Media Studio job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[MediaStudioJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return MediaStudioJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load local Media Studio checkpoint %s", job_id)
            return None

    def _backfill_cloud(self, job: MediaStudioJob) -> None:
        try:
            self._sync_artifacts(job)
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill Media Studio job %s to cloud persistence", job.job_id)

    def _load(self, job_id: str) -> Optional[MediaStudioJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud
        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    @staticmethod
    def _source_snapshot(production_job: ProductionBriefJob) -> MediaSourceSnapshot:
        assert production_job.result is not None
        result = production_job.result
        return MediaSourceSnapshot(
            production_brief_job_id=production_job.job_id,
            source_snapshot_id=result.source_snapshot.snapshot_id,
            source_hash=result.source_snapshot.source_hash,
            captured_at=datetime.now(timezone.utc),
            working_title=result.creative_direction.working_title,
            production_identity=result.creative_direction.production_identity.model_copy(deep=True),
            storyboard=result.storyboard.model_copy(deep=True),
            closest_archive_matches=[
                match.model_copy(deep=True)
                for match in result.closest_archive_matches[:3]
            ],
            character_identity_evidence=(
                result.character_identity_evidence.model_copy(deep=True)
                if result.character_identity_evidence is not None
                else None
            ),
        )

    @staticmethod
    def _refresh_gate(job: MediaStudioJob) -> None:
        if not job.result:
            return
        result = job.result
        result.approved_keyframes = sum(1 for a in result.keyframes if a.review_status == MediaAssetReviewStatus.APPROVED)
        result.fidelity_reviewed_keyframes = sum(1 for a in result.keyframes if a.fidelity_report is not None)
        result.fidelity_passed_keyframes = sum(
            1
            for a in result.keyframes
            if a.fidelity_report is not None
            and a.fidelity_report.status in {KeyframeFidelityStatus.PASS, KeyframeFidelityStatus.ADAPTATION_ACCEPTED}
        )
        has_active_shot_operation = any(
            operation.status in {ShotOperationStatus.REGENERATING, ShotOperationStatus.FIDELITY_REVIEW}
            for operation in result.shot_operations.values()
        )
        result.animation_ready = bool(
            result.required_keyframes > 0
            and result.approved_keyframes >= result.required_keyframes
            and result.fidelity_passed_keyframes >= result.required_keyframes
            and not has_active_shot_operation
        )
        result.required_clips = result.required_keyframes
        result.approved_clips = sum(
            1
            for clip in result.video_clips
            if clip.review_status == MediaAssetReviewStatus.APPROVED
            or any(
                op.shot_number == clip.shot_number
                and op.status == ClipOperationStatus.BUDGET_EXCEEDED
                for op in result.clip_operations.values()
            )
        )
        has_active_clip_operation = any(
            operation.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING}
            for operation in result.clip_operations.values()
        )
        failed_clip_operations = [
            operation for operation in result.clip_operations.values()
            if operation.status == ClipOperationStatus.FAILED
        ]
        result.assembly_ready = bool(
            result.required_clips > 0
            and result.approved_clips >= result.required_clips
            and len(result.video_clips) >= result.required_clips
            and not has_active_clip_operation
        )
        if result.assembly_ready:
            job.stage = MediaStudioJobStage.READY_FOR_ASSEMBLY
            job.message = "All Veo shot clips are human-approved; ready for M2C assembly"
        elif failed_clip_operations and not has_active_clip_operation:
            job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
            count = len(failed_clip_operations)
            job.message = f"{count} animated shot{'s' if count != 1 else ''} failed; review the error and retry only those shots"
        elif result.video_clips and job.stage == MediaStudioJobStage.READY_FOR_ASSEMBLY:
            job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
            job.message = "Review each animated shot before assembly"
        elif result.animation_ready and not result.video_clips and job.stage not in {MediaStudioJobStage.GENERATING_CLIPS}:
            job.stage = MediaStudioJobStage.READY_FOR_ANIMATION
            job.message = "All keyframes passed/accepted fidelity review and human approval; ready for M2B.2 animation"
        elif result.keyframes and job.stage == MediaStudioJobStage.READY_FOR_ANIMATION:
            job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
            job.message = "M2B.1.2 shot review is required before animation"

    def create(self, production_job: ProductionBriefJob, settings: Settings) -> MediaStudioJob:
        if production_job.result is None or production_job.result.review_status != ProductionReviewStatus.APPROVED:
            raise ValueError("Approve the M2A production brief before starting media generation.")
        if production_job.result.consistency_report.status != "PASS":
            raise ValueError("The approved production brief must pass the Production Consistency Lock.")
        if production_job.result.direction_fidelity.status == "REVIEW_REQUIRED":
            raise ValueError("Resolve Direction Fidelity before starting media generation.")

        now = datetime.now(timezone.utc)
        snapshot = self._source_snapshot(production_job)
        job = MediaStudioJob(
            job_id=f"media_{uuid4().hex}",
            production_brief_job_id=production_job.job_id,
            channel_id=production_job.channel_id,
            stage=MediaStudioJobStage.QUEUED,
            message="Visual reference generation queued",
            progress_current=0,
            progress_total=1 + len(snapshot.storyboard.shots),
            created_at=now,
            updated_at=now,
            detail={
                "image_model": settings.image_generation_model,
                "fidelity_model": settings.gemini_model,
                "aspect_ratio": settings.media_image_aspect_ratio,
                "identity_locked": True,
                "source_hash": snapshot.source_hash,
                "fidelity_gate": "required",
            },
            result=MediaStudioResult(
                source_snapshot=snapshot,
                image_model=settings.image_generation_model,
                video_model=settings.video_generation_model,
                aspect_ratio=settings.media_image_aspect_ratio,
                required_keyframes=len(snapshot.storyboard.shots),
                required_clips=len(snapshot.storyboard.shots),
            ),
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> MediaStudioJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None:
                raise MediaStudioJobNotFoundError(job_id)
            before = job.model_dump(mode="json")
            self._refresh_gate(job)
            self._jobs[job_id] = job
            if job.model_dump(mode="json") != before:
                self._persist(job)
            return job.model_copy(deep=True)

    def latest_for_production_brief(self, production_brief_job_id: str) -> Optional[MediaStudioJob]:
        """Return the newest tenant-owned job from Firestore, local mirror, or memory."""
        candidates: Dict[str, MediaStudioJob] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.production_brief_job_id == production_brief_job_id:
                    candidates[loaded.job_id] = loaded
        except Exception:
            logger.exception("Could not list Media Studio jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("*/job.json"):
            loaded = self._load_local(path.parent.name)
            if loaded and loaded.production_brief_job_id == production_brief_job_id:
                candidates[loaded.job_id] = loaded
                if self._load_cloud(loaded.job_id) is None:
                    self._backfill_cloud(loaded)

        with self._lock:
            for item in self._jobs.values():
                if item.production_brief_job_id == production_brief_job_id:
                    candidates[item.job_id] = item.model_copy(deep=True)

        if not candidates:
            return None
        latest = max(candidates.values(), key=lambda item: (item.updated_at, item.created_at, item.job_id))
        return self.get(latest.job_id)

    def save(self, job: MediaStudioJob) -> None:
        self._refresh_gate(job)
        job.updated_at = datetime.now(timezone.utc)
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)

    def asset_path(self, job_id: str, asset_id: str) -> tuple[Path, str]:
        job = self.get(job_id)
        if not job.result:
            raise MediaStudioJobNotFoundError(asset_id)
        assets = []
        if job.result.reference_asset:
            assets.append(job.result.reference_asset)
        assets.extend(job.result.keyframes)
        assets.extend(job.result.video_clips)
        asset = next((a for a in assets if a.asset_id == asset_id), None)
        if not asset:
            raise MediaStudioJobNotFoundError(asset_id)
        path = self.assets_dir(job_id) / asset.filename
        if not path.exists():
            self._artifacts.ensure_local(
                path, owner_id=job_id, relative_path=f"assets/{asset.filename}", gcs_uri=getattr(asset, "gcs_uri", None)
            )
        if not path.exists():
            raise MediaStudioJobNotFoundError(asset_id)
        return path, asset.mime_type

    def approve_reference(self, job_id: str, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result or not job.result.reference_asset:
            raise ValueError("Generate a character reference before approving it.")
        evidence = job.result.source_snapshot.character_identity_evidence
        asset = job.result.reference_asset
        if evidence and evidence.source_videos and asset.identity_grounding_images_supplied < 1:
            raise ValueError(
                "Historical character appearances are available, but none were supplied to the image model. "
                "Regenerate the character reference before approval."
            )
        job.result.reference_asset.review_status = MediaAssetReviewStatus.APPROVED
        job.result.reference_asset.review_note = note
        job.result.reference_approved = True
        job.stage = MediaStudioJobStage.GENERATING_KEYFRAMES
        job.message = "Approved reference locked; storyboard keyframes queued"
        self.save(job)
        return job

    def approve_keyframe(self, job_id: str, shot_number: int, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result:
            raise ValueError("Media Studio result is unavailable.")
        asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
        if not asset:
            raise ValueError(f"Shot {shot_number} keyframe is not available.")
        if asset.fidelity_report is None:
            raise ValueError(f"Run the fidelity review for shot {shot_number} before human approval.")
        if asset.fidelity_report.status == KeyframeFidelityStatus.REVIEW_REQUIRED:
            raise ValueError(
                f"Shot {shot_number} has storyboard-fidelity issues. Regenerate to match the shot or explicitly accept the adaptation first."
            )
        asset.review_status = MediaAssetReviewStatus.APPROVED
        asset.review_note = note
        self.save(job)
        return job

    def accept_keyframe_adaptation(self, job_id: str, shot_number: int, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result:
            raise ValueError("Media Studio result is unavailable.")
        asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
        if not asset or asset.fidelity_report is None:
            raise ValueError(f"Run the fidelity review for shot {shot_number} before accepting an adaptation.")
        if asset.fidelity_report.status != KeyframeFidelityStatus.REVIEW_REQUIRED:
            raise ValueError(f"Shot {shot_number} does not currently require an adaptation decision.")
        asset.fidelity_report.status = KeyframeFidelityStatus.ADAPTATION_ACCEPTED
        asset.fidelity_report.creator_override = True
        if note:
            asset.review_note = note
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = f"Shot {shot_number} adaptation accepted; human image approval is still required"
        self.save(job)
        return job

    def begin_keyframe_regeneration(self, job_id: str, shot_number: int, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result or not job.result.reference_asset or not job.result.reference_approved:
            raise ValueError("Approve the canonical character reference before regenerating a keyframe.")
        asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
        if not asset:
            raise ValueError(f"Shot {shot_number} keyframe is not available.")
        existing_operation = job.result.shot_operations.get(shot_number)
        if existing_operation and existing_operation.status in {ShotOperationStatus.REGENERATING, ShotOperationStatus.FIDELITY_REVIEW}:
            raise ValueError(f"Shot {shot_number} is already being regenerated.")

        now = datetime.now(timezone.utc)
        previous_review_status = asset.review_status
        asset.review_status = MediaAssetReviewStatus.NEEDS_REVIEW
        if note:
            asset.review_note = note
        job.result.animation_ready = False
        job.result.shot_operations[shot_number] = ShotOperation(
            shot_number=shot_number,
            status=ShotOperationStatus.REGENERATING,
            message=f"Regenerating shot {shot_number} while preserving the approved identity and other keyframes",
            started_at=now,
            updated_at=now,
            target_generation_attempt=asset.generation_attempt + 1,
            previous_review_status=previous_review_status,
        )
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = f"Shot {shot_number} is regenerating locally; other keyframes remain available"
        job.error = None
        self.save(job)
        return job

    def update_shot_operation(
        self,
        job_id: str,
        shot_number: int,
        *,
        status: ShotOperationStatus,
        message: str,
        error: Optional[str] = None,
        updated_asset_id: Optional[str] = None,
    ) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result:
            raise ValueError("Media Studio result is unavailable.")
        now = datetime.now(timezone.utc)
        operation = job.result.shot_operations.get(shot_number)
        if operation is None:
            asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
            target_attempt = (asset.generation_attempt + 1) if asset else 1
            operation = ShotOperation(
                shot_number=shot_number,
                status=status,
                message=message,
                started_at=now,
                updated_at=now,
                target_generation_attempt=target_attempt,
            )
            job.result.shot_operations[shot_number] = operation
        else:
            operation.status = status
            operation.message = message
            operation.updated_at = now
            operation.error = error
            operation.updated_asset_id = updated_asset_id
        if status == ShotOperationStatus.FAILED and operation.previous_review_status is not None:
            asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
            if asset is not None:
                asset.review_status = operation.previous_review_status
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Review storyboard fidelity and approve each keyframe before animation"
        self.save(job)
        return job

    @staticmethod
    def _video_estimate(settings: Settings, duration_seconds: int) -> tuple[float, float]:
        units = round(
            max(0, int(duration_seconds))
            * float(settings.video_estimated_units_per_generated_second),
            6,
        )
        cost = round(units * float(settings.video_estimated_cost_per_unit_usd), 6)
        return units, cost

    def _job_estimated_video_cost(self, job: MediaStudioJob) -> float:
        if not job.result:
            return 0.0
        return round(
            sum(float(item.estimated_cost_usd) for item in job.result.video_generation_charges),
            6,
        )

    def claim_video_generation(
        self,
        job_id: str,
        shot_number: int,
        generation_attempt: int,
        duration_seconds: int,
        settings: Settings,
    ) -> tuple[str, float, float]:
        """Create one append-only cost record before the paid provider call."""
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None or not job.result:
                raise MediaStudioJobNotFoundError(job_id)

            op = job.result.clip_operations.get(shot_number)
            if op and op.generation_claim_id and op.status == ClipOperationStatus.GENERATING:
                raise ValueError(f"Shot {shot_number} already has an active Veo generation claim.")

            units, estimated_cost = self._video_estimate(settings, duration_seconds)
            current_total = self._job_estimated_video_cost(job)
            budget = float(settings.video_production_budget_usd)
            # Production-scoped generation is authorized by FirestoreBudgetService.reserve()
            # in MediaGenerationService. Its immutable, tenant-scoped allocation includes
            # non-video spending and is enforced atomically for concurrent shots.
            # Do not also apply the legacy $2 Media Studio-only cap to these jobs.
            # Both animation entrypoints initialize the durable production budget first.
            legacy_unscoped_job = not bool(getattr(job, "production_brief_job_id", None))
            if (
                legacy_unscoped_job
                and settings.video_budget_enforced
                and budget > 0
                and current_total + estimated_cost > budget + 1e-9
            ):
                # Budget protection is a business condition, not a technical failure.
                # Keep the production alive so completed shots can proceed to assembly.
                now = datetime.now(timezone.utc)
                if op is None:
                    op = ClipOperation(
                        shot_number=shot_number,
                        status=ClipOperationStatus.BUDGET_EXCEEDED,
                        message="Animation skipped because the Veo budget limit was reached.",
                        started_at=now,
                        updated_at=now,
                        target_generation_attempt=generation_attempt,
                        error=f"Estimated Veo production budget would be exceeded (${current_total + estimated_cost:.2f} > ${budget:.2f}).",
                        estimated_units=units,
                        estimated_cost_usd=estimated_cost,
                    )
                    job.result.clip_operations[shot_number] = op
                else:
                    op.status = ClipOperationStatus.BUDGET_EXCEEDED
                    op.message = "Animation skipped because the Veo budget limit was reached."
                    op.error = f"Estimated Veo production budget would be exceeded (${current_total + estimated_cost:.2f} > ${budget:.2f})."
                    op.updated_at = now
                job.updated_at = now
                self._jobs[job_id] = job
                self._persist(job)
                return "budget_exceeded", units, estimated_cost

            now = datetime.now(timezone.utc)
            claim_id = f"veo_{job_id}_{shot_number}_{generation_attempt}_{uuid4().hex}"
            charge = VideoGenerationCharge(
                charge_id=f"charge_{uuid4().hex}",
                shot_number=shot_number,
                generation_attempt=generation_attempt,
                model=settings.video_generation_model,
                resolution=settings.video_generation_resolution,
                audio_enabled=settings.video_generation_audio,
                requested_duration_seconds=duration_seconds,
                estimated_units=units,
                unit_rate_usd=float(settings.video_estimated_cost_per_unit_usd),
                estimated_cost_usd=estimated_cost,
                status=VideoGenerationChargeStatus.CLAIMED,
                created_at=now,
                updated_at=now,
                generation_claim_id=claim_id,
            )
            job.result.video_generation_charges.append(charge)

            if op is None:
                op = ClipOperation(
                    shot_number=shot_number,
                    status=ClipOperationStatus.GENERATING,
                    message=f"Animating shot {shot_number} with Veo",
                    started_at=now,
                    updated_at=now,
                    target_generation_attempt=generation_attempt,
                )
                job.result.clip_operations[shot_number] = op
            op.status = ClipOperationStatus.GENERATING
            op.message = f"Animating shot {shot_number} with Veo"
            op.updated_at = now
            op.target_generation_attempt = generation_attempt
            op.generation_claim_id = claim_id
            op.provider_operation_name = None
            op.estimated_units = units
            op.estimated_cost_usd = estimated_cost
            op.error = None
            job.updated_at = now
            self._jobs[job_id] = job
            self._persist(job)
            return claim_id, units, estimated_cost

    def mark_video_submitted(
        self, job_id: str, shot_number: int, claim_id: str, provider_operation_name: str
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None or not job.result:
                return
            now = datetime.now(timezone.utc)
            op = job.result.clip_operations.get(shot_number)
            if op and op.generation_claim_id == claim_id:
                op.provider_operation_name = provider_operation_name or None
                op.updated_at = now
            for charge in reversed(job.result.video_generation_charges):
                if charge.generation_claim_id == claim_id:
                    charge.status = VideoGenerationChargeStatus.SUBMITTED
                    charge.provider_operation_name = provider_operation_name or None
                    charge.updated_at = now
                    break
            job.updated_at = now
            self._jobs[job_id] = job
            self._persist(job)

    def finalize_video_charge(
        self,
        job_id: str,
        claim_id: str,
        *,
        succeeded: bool,
        asset_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load(job_id)
            if job is None or not job.result:
                return
            now = datetime.now(timezone.utc)
            for charge in reversed(job.result.video_generation_charges):
                if charge.generation_claim_id == claim_id:
                    charge.status = (
                        VideoGenerationChargeStatus.SUCCEEDED
                        if succeeded
                        else VideoGenerationChargeStatus.FAILED
                    )
                    charge.asset_id = asset_id
                    charge.error = error
                    charge.updated_at = now
                    break
            job.updated_at = now
            self._jobs[job_id] = job
            self._persist(job)

    def begin_clip_generation(self, job_id: str) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result or not job.result.animation_ready:
            raise ValueError("Approve and fidelity-clear every keyframe before starting Veo animation.")
        if any(op.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING} for op in job.result.clip_operations.values()):
            raise ValueError("Veo animation is already running for this Media Studio job.")
        now = datetime.now(timezone.utc)
        existing = {clip.shot_number: clip for clip in job.result.video_clips}
        for shot in job.result.source_snapshot.storyboard.shots:
            if shot.shot_number in existing:
                continue
            job.result.clip_operations[shot.shot_number] = ClipOperation(
                shot_number=shot.shot_number,
                status=ClipOperationStatus.QUEUED,
                message=f"Shot {shot.shot_number} queued for Veo animation",
                started_at=now,
                updated_at=now,
                target_generation_attempt=1,
            )
        job.stage = MediaStudioJobStage.GENERATING_CLIPS
        job.message = "Animating approved storyboard keyframes with Veo"
        job.error = None
        self.save(job)
        return job

    def begin_clip_regeneration(self, job_id: str, shot_number: int, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result or not job.result.animation_ready:
            raise ValueError("The approved keyframe set is no longer animation-ready.")
        clip = next((c for c in job.result.video_clips if c.shot_number == shot_number), None)
        current = job.result.clip_operations.get(shot_number)
        if current and current.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING}:
            raise ValueError(f"Shot {shot_number} is already animating.")
        if clip is None and (current is None or current.status != ClipOperationStatus.FAILED):
            raise ValueError(f"Shot {shot_number} has no generated clip or failed animation to retry.")
        now = datetime.now(timezone.utc)
        previous = clip.review_status if clip else None
        if clip is not None:
            clip.review_status = MediaAssetReviewStatus.NEEDS_REVIEW
            if note:
                clip.review_note = note
        previous_attempt = clip.generation_attempt if clip else int(getattr(current, "target_generation_attempt", 1) or 1)
        job.result.assembly_ready = False
        job.result.clip_operations[shot_number] = ClipOperation(
            shot_number=shot_number,
            status=ClipOperationStatus.GENERATING,
            message=(f"Regenerating animated shot {shot_number}; other clips remain available" if clip else f"Retrying failed animation for shot {shot_number}; other shots remain available"),
            started_at=now,
            updated_at=now,
            target_generation_attempt=previous_attempt + 1,
            previous_review_status=previous,
        )
        job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
        job.message = f"Shot {shot_number} is regenerating locally; other clips remain available"
        self.save(job)
        return job

    def update_clip_operation(
        self, job_id: str, shot_number: int, *, status: ClipOperationStatus, message: str,
        error: Optional[str] = None, updated_asset_id: Optional[str] = None,
    ) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result:
            raise ValueError("Media Studio result is unavailable.")
        now = datetime.now(timezone.utc)
        operation = job.result.clip_operations.get(shot_number)
        if operation is None:
            clip = next((c for c in job.result.video_clips if c.shot_number == shot_number), None)
            operation = ClipOperation(
                shot_number=shot_number, status=status, message=message, started_at=now, updated_at=now,
                target_generation_attempt=(clip.generation_attempt + 1) if clip else 1,
            )
            job.result.clip_operations[shot_number] = operation
        else:
            operation.status = status
            operation.message = message
            operation.updated_at = now
            operation.error = error
            operation.updated_asset_id = updated_asset_id
        if status == ClipOperationStatus.FAILED and operation.previous_review_status is not None:
            clip = next((c for c in job.result.video_clips if c.shot_number == shot_number), None)
            if clip is not None:
                clip.review_status = operation.previous_review_status
        if job.stage != MediaStudioJobStage.GENERATING_CLIPS:
            job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
        self.save(job)
        return job

    def approve_clip(self, job_id: str, shot_number: int, note: Optional[str] = None) -> MediaStudioJob:
        job = self.get(job_id)
        if not job.result:
            raise ValueError("Media Studio result is unavailable.")
        operation = job.result.clip_operations.get(shot_number)
        if operation and operation.status in {ClipOperationStatus.QUEUED, ClipOperationStatus.GENERATING}:
            raise ValueError(f"Shot {shot_number} is still generating.")
        clip = next((c for c in job.result.video_clips if c.shot_number == shot_number), None)
        if not clip:
            raise ValueError(f"Shot {shot_number} video clip is not available.")
        clip.review_status = MediaAssetReviewStatus.APPROVED
        clip.review_note = note
        job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
        job.message = "Review and approve each animated shot before final assembly"
        self.save(job)
        return self.get(job_id)

    def fail(self, job_id: str, error: str) -> None:
        job = self.get(job_id)
        job.stage = MediaStudioJobStage.FAILED
        job.message = "Media generation paused"
        job.error = error
        self.save(job)


media_studio_job_store = MediaStudioJobStore(get_settings().content_dna_checkpoint_dir)


async def _review_asset_fidelity(
    *,
    service: MediaGenerationService,
    store: MediaStudioJobStore,
    job: MediaStudioJob,
    asset,
    shot,
):
    assert job.result is not None and job.result.reference_asset is not None
    reference = job.result.reference_asset
    reference_bytes = store.asset_path(job.job_id, reference.asset_id)[0].read_bytes()
    keyframe_bytes = store.asset_path(job.job_id, asset.asset_id)[0].read_bytes()
    return await service.review_keyframe_fidelity(
        source=job.result.source_snapshot,
        reference_asset=reference,
        reference_bytes=reference_bytes,
        keyframe_asset=asset,
        keyframe_bytes=keyframe_bytes,
        shot=shot,
        channel_id=job.channel_id,
    )


async def generate_reference_for_job(job_id: str, settings: Settings) -> None:
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result:
        store.fail(job_id, "Media source snapshot is unavailable.")
        return
    service = MediaGenerationService(settings)
    try:
        job.stage = MediaStudioJobStage.GENERATING_REFERENCE
        job.message = "Generating canonical character reference"
        job.detail = {**job.detail, "current_asset": "character_reference"}
        store.save(job)
        attempt = (job.result.reference_asset.generation_attempt + 1) if job.result.reference_asset else 1
        asset = await service.generate_reference(job.result.source_snapshot, store.assets_dir(job_id), generation_attempt=attempt, channel_id=job.channel_id)
        asset.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{asset.asset_id}"
        job = store.get(job_id)
        assert job.result is not None
        job.result.reference_asset = asset
        job.result.reference_approved = False
        evidence = job.result.source_snapshot.character_identity_evidence
        job.detail = {
            **job.detail,
            "identity_grounding": {
                "character": evidence.character_name if evidence else job.result.source_snapshot.production_identity.character_name,
                "resolved_from_content_dna": bool(evidence and evidence.resolved_from_content_dna),
                "available_sources": len(evidence.source_videos) if evidence else 0,
                "images_supplied": asset.identity_grounding_images_supplied,
                "source_video_ids": list(asset.identity_grounding_video_ids),
            },
        }
        job.result.keyframes = []
        job.result.approved_keyframes = 0
        job.result.fidelity_reviewed_keyframes = 0
        job.result.fidelity_passed_keyframes = 0
        job.result.animation_ready = False
        job.stage = MediaStudioJobStage.AWAITING_REFERENCE_APPROVAL
        job.message = "Review and approve the canonical character reference"
        job.progress_current = 1
        job.error = None
        store.save(job)
    except MediaGenerationError as exc:
        store.fail(job_id, str(exc))
    except Exception:
        store.fail(job_id, "ReviveAI could not generate the canonical character reference. Retry the reference generation.")


async def generate_keyframes_for_job(job_id: str, settings: Settings) -> None:
    """Generate and fidelity-review storyboard keyframes with bounded concurrency.

    Workers never persist whole-job snapshots while running. They return independent
    shot results and the coordinator performs one merge, avoiding lost updates in the
    JSON checkpoint store while still allowing multiple Vertex calls in flight.
    """
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result or not job.result.reference_asset or not job.result.reference_approved:
        store.fail(job_id, "Approve the canonical character reference before generating storyboard keyframes.")
        return

    service = MediaGenerationService(settings)
    result = job.result
    reference = result.reference_asset
    reference_bytes = store.asset_path(job_id, reference.asset_id)[0].read_bytes()
    shots = list(result.source_snapshot.storyboard.shots)
    existing_by_shot = {asset.shot_number: asset for asset in result.keyframes}
    concurrency = max(1, int(getattr(settings, "media_keyframe_concurrency", 3) or 3))
    semaphore = asyncio.Semaphore(concurrency)

    job.stage = MediaStudioJobStage.GENERATING_KEYFRAMES
    job.message = f"Generating {len(shots)} storyboard keyframes with up to {concurrency} parallel workers"
    job.error = None
    job.detail = {
        **job.detail,
        "current_task": "parallel_keyframe_generation",
        "keyframe_concurrency": concurrency,
        "keyframes_total": len(shots),
        "keyframes_completed": 0,
    }
    store.save(job)

    async def build_one(shot):
        async with semaphore:
            # The local semaphore limits this production; the global scheduler limits
            # all productions combined so future wave execution cannot stampede Vertex.
            async with global_resource_scheduler.acquire("image"):
                old = existing_by_shot.get(shot.shot_number)
                attempt = (old.generation_attempt + 1) if old else 1
                asset = await service.generate_keyframe(
                    result.source_snapshot,
                    reference,
                    reference_bytes,
                    shot,
                    store.assets_dir(job_id),
                    generation_attempt=attempt,
                    channel_id=job.channel_id,
                )
                asset.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{asset.asset_id}"
                fidelity_error = None
                try:
                    keyframe_bytes = (store.assets_dir(job_id) / asset.filename).read_bytes()
                    asset.fidelity_report = await service.review_keyframe_fidelity(
                        source=result.source_snapshot,
                        reference_asset=reference,
                        reference_bytes=reference_bytes,
                        keyframe_asset=asset,
                        keyframe_bytes=keyframe_bytes,
                        shot=shot,
                        channel_id=job.channel_id,
                    )
                except MediaGenerationError as exc:
                    fidelity_error = str(exc)
                    logger.warning("Fidelity review deferred for shot %s: %s", shot.shot_number, exc)
                return shot.shot_number, asset, fidelity_error

    try:
        tasks = [asyncio.create_task(build_one(shot)) for shot in shots]
        outputs = []
        completed = 0
        for future in asyncio.as_completed(tasks):
            outputs.append(await future)
            completed += 1
            # Progress persistence is coordinator-only, so concurrent workers cannot
            # overwrite each other's job snapshots.
            current = store.get(job_id)
            current.progress_current = 1 + completed
            current.detail = {
                **current.detail,
                "keyframes_completed": completed,
                "keyframes_total": len(shots),
            }
            current.message = f"Generated and reviewed {completed} of {len(shots)} storyboard keyframes"
            store.save(current)

        outputs.sort(key=lambda item: item[0])
        assets = [item[1] for item in outputs]
        missing = sum(1 for _shot, _asset, error in outputs if error is not None)
        job = store.get(job_id)
        assert job.result is not None
        job.result.keyframes = assets
        job.result.animation_ready = False
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Review storyboard fidelity and approve each keyframe before animation"
        job.progress_current = job.progress_total
        job.detail = {
            **job.detail,
            "keyframes_generated": len(assets),
            "keyframes_completed": len(assets),
            "fidelity_reviews_missing": missing,
            "current_shot": None,
            "current_task": None,
        }
        store.save(job)
    except MediaGenerationError as exc:
        for task in locals().get("tasks", []):
            if not task.done():
                task.cancel()
        store.fail(job_id, str(exc))
    except Exception:
        for task in locals().get("tasks", []):
            if not task.done():
                task.cancel()
        logger.exception("Parallel keyframe generation failed")
        store.fail(job_id, "ReviveAI could not finish storyboard keyframe generation. Retry keyframes from the approved reference.")


async def review_keyframe_fidelity_for_job(job_id: str, shot_number: int, settings: Settings) -> None:
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result or not job.result.reference_asset or not job.result.reference_approved:
        store.fail(job_id, "Approve the canonical character reference before reviewing keyframe fidelity.")
        return
    shot = next((s for s in job.result.source_snapshot.storyboard.shots if s.shot_number == shot_number), None)
    asset = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
    if not shot or not asset:
        store.fail(job_id, f"Storyboard shot {shot_number} is unavailable for fidelity review.")
        return
    service = MediaGenerationService(settings)
    try:
        job.stage = MediaStudioJobStage.REVIEWING_KEYFRAME_FIDELITY
        job.message = f"Reviewing storyboard fidelity for shot {shot_number}"
        job.detail = {**job.detail, "current_shot": shot_number, "current_task": "fidelity_review"}
        store.save(job)
        report = await _review_asset_fidelity(service=service, store=store, job=job, asset=asset, shot=shot)
        job = store.get(job_id)
        assert job.result is not None
        asset = next(a for a in job.result.keyframes if a.shot_number == shot_number)
        asset.fidelity_report = report
        if report.status == KeyframeFidelityStatus.REVIEW_REQUIRED and asset.review_status == MediaAssetReviewStatus.APPROVED:
            asset.review_status = MediaAssetReviewStatus.NEEDS_REVIEW
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Review storyboard fidelity and approve each keyframe before animation"
        job.detail = {**job.detail, "current_shot": None, "current_task": None}
        store.save(job)
    except MediaGenerationError as exc:
        job = store.get(job_id)
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Fidelity review could not complete; retry the fidelity review for this shot"
        job.error = str(exc)
        store.save(job)
    except Exception:
        logger.exception("Keyframe fidelity review failed")
        job = store.get(job_id)
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Fidelity review could not complete; retry the fidelity review for this shot"
        job.error = f"ReviveAI could not review storyboard fidelity for shot {shot_number}."
        store.save(job)


async def review_all_keyframe_fidelity_for_job(job_id: str, settings: Settings) -> None:
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result:
        store.fail(job_id, "Media Studio result is unavailable.")
        return
    for asset in list(job.result.keyframes):
        if asset.fidelity_report is None:
            await review_keyframe_fidelity_for_job(job_id, asset.shot_number or 0, settings)
    job = store.get(job_id)
    if job.stage != MediaStudioJobStage.FAILED:
        job.stage = MediaStudioJobStage.AWAITING_KEYFRAME_REVIEW
        job.message = "Review storyboard fidelity and approve each keyframe before animation"
        job.error = None
        store.save(job)


async def regenerate_keyframe_for_job(job_id: str, shot_number: int, settings: Settings, creator_note: Optional[str] = None) -> None:
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result or not job.result.reference_asset or not job.result.reference_approved:
        try:
            store.update_shot_operation(
                job_id, shot_number, status=ShotOperationStatus.FAILED,
                message=f"Shot {shot_number} regeneration could not start",
                error="Approve the canonical character reference before regenerating a keyframe.",
            )
        except Exception:
            logger.exception("Could not record localized shot failure")
        return
    shot = next((s for s in job.result.source_snapshot.storyboard.shots if s.shot_number == shot_number), None)
    if not shot:
        store.update_shot_operation(
            job_id, shot_number, status=ShotOperationStatus.FAILED,
            message=f"Shot {shot_number} regeneration could not start",
            error=f"Storyboard shot {shot_number} was not found in the approved production brief.",
        )
        return

    service = MediaGenerationService(settings)
    try:
        reference = job.result.reference_asset
        reference_bytes = store.asset_path(job_id, reference.asset_id)[0].read_bytes()
        old = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
        attempt = (old.generation_attempt + 1) if old else 1
        correction = old.fidelity_report.corrective_instruction if old and old.fidelity_report else None

        asset = await service.generate_keyframe(
            job.result.source_snapshot,
            reference,
            reference_bytes,
            shot,
            store.assets_dir(job_id),
            generation_attempt=attempt,
            corrective_instruction=correction,
            creator_note=creator_note,
            channel_id=job.channel_id,
        )
        asset.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{asset.asset_id}"

        store.update_shot_operation(
            job_id, shot_number, status=ShotOperationStatus.FIDELITY_REVIEW,
            message=f"Updated shot {shot_number} is ready; checking storyboard fidelity",
            updated_asset_id=asset.asset_id,
        )

        try:
            current_job = store.get(job_id)
            assert current_job.result is not None
            keyframe_bytes = (store.assets_dir(job_id) / asset.filename).read_bytes()
            asset.fidelity_report = await service.review_keyframe_fidelity(
                source=current_job.result.source_snapshot,
                reference_asset=reference,
                reference_bytes=reference_bytes,
                keyframe_asset=asset,
                keyframe_bytes=keyframe_bytes,
                shot=shot,
                channel_id=job.channel_id,
            )
        except MediaGenerationError as exc:
            logger.warning("Fidelity review deferred after shot %s regeneration: %s", shot_number, exc)

        job = store.get(job_id)
        assert job.result is not None
        job.result.keyframes = [a for a in job.result.keyframes if a.shot_number != shot_number] + [asset]
        job.result.keyframes.sort(key=lambda a: a.shot_number or 0)
        job.result.animation_ready = False
        store.save(job)

        report_status = asset.fidelity_report.status.value if asset.fidelity_report else "PENDING_REVIEW"
        store.update_shot_operation(
            job_id, shot_number, status=ShotOperationStatus.READY,
            message=f"Shot {shot_number} version {attempt} is ready ({report_status})",
            updated_asset_id=asset.asset_id,
        )
    except MediaGenerationError as exc:
        logger.warning("Localized keyframe regeneration failed for shot %s: %s", shot_number, exc)
        store.update_shot_operation(
            job_id, shot_number, status=ShotOperationStatus.FAILED,
            message=f"Shot {shot_number} regeneration failed; the previous image was preserved",
            error=str(exc),
        )
    except Exception:
        logger.exception("Localized keyframe regeneration failed for shot %s", shot_number)
        store.update_shot_operation(
            job_id, shot_number, status=ShotOperationStatus.FAILED,
            message=f"Shot {shot_number} regeneration failed; the previous image was preserved",
            error=f"ReviveAI could not regenerate storyboard keyframe {shot_number}.",
        )


def recover_existing_veo_clip(job_id: str, shot_number: int, settings: Settings) -> bool:
    """Adopt an accepted provider operation without submitting another paid request.

    A missing or indeterminate provider outcome is a hard stop; never retry a
    claimed operation merely because the local clip asset is missing.
    """
    from app.services.veo_existing_operation_adoption import adopt_existing_veo_operation
    return adopt_existing_veo_operation(media_studio_job_store, job_id, shot_number, settings)


async def generate_video_clips_for_job(job_id: str, settings: Settings) -> None:
    """Generate independent Veo shots concurrently with a bounded worker pool."""
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result or not job.result.animation_ready:
        try:
            store.fail(job_id, "All approved keyframes must remain animation-ready before Veo generation.")
        except Exception:
            logger.exception("Could not record Veo gate failure")
        return

    service = MediaGenerationService(settings)
    result = job.result
    shots = list(result.source_snapshot.storyboard.shots)
    # Recover previously submitted shots before resetting clip-operation state.
    # A successful provider operation must never cause another paid Veo request.
    for shot in shots:
        if shot.shot_number not in {clip.shot_number for clip in store.get(job_id).result.video_clips}:
            recover_existing_veo_clip(job_id, shot.shot_number, settings)
    job = store.get(job_id)
    result = job.result
    existing_by_shot = {clip.shot_number: clip for clip in result.video_clips}
    pending_shots = [shot for shot in shots if shot.shot_number not in existing_by_shot]
    concurrency = max(1, int(getattr(settings, "media_video_concurrency", 2) or 2))
    semaphore = asyncio.Semaphore(concurrency)

    job.stage = MediaStudioJobStage.GENERATING_CLIPS
    job.message = f"Animating {len(pending_shots)} shots with up to {concurrency} parallel Veo workers"
    job.error = None
    job.detail = {
        **job.detail,
        "current_task": "parallel_veo_generation",
        "video_concurrency": concurrency,
        "clips_total": len(pending_shots),
        "clips_completed": 0,
    }
    now = datetime.now(timezone.utc)
    for shot in pending_shots:
        job.result.clip_operations[shot.shot_number] = ClipOperation(
            shot_number=shot.shot_number,
            status=ClipOperationStatus.QUEUED,
            message=f"Shot {shot.shot_number} queued for parallel Veo animation",
            started_at=now,
            updated_at=now,
            target_generation_attempt=1,
        )
    store.save(job)

    async def animate_one(shot):
        async with semaphore:
            keyframe = next((a for a in result.keyframes if a.shot_number == shot.shot_number), None)
            if not keyframe or keyframe.review_status != MediaAssetReviewStatus.APPROVED:
                return shot.shot_number, None, "The source keyframe is not human-approved."
            claim_id: Optional[str] = None
            try:
                duration = service.supported_video_duration(shot.duration_seconds)
                from app.services.channel_autonomy_policy import channel_policy_store
                from app.services.firestore_budget_service import FirestoreBudgetService
                FirestoreBudgetService().ensure_production_budget(
                    job.production_brief_job_id, job.channel_id,
                    channel_policy_store.get(job.channel_id).max_total_production_cost_usd,
                )
                claim_id, _, claim_cost = store.claim_video_generation(
                    job_id, shot.shot_number, 1, duration, settings
                )
                if claim_id == "budget_exceeded":
                    return shot.shot_number, None, "BUDGET_EXCEEDED"

                def on_started(operation_name: str) -> None:
                    store.mark_video_submitted(
                        job_id, shot.shot_number, claim_id, operation_name
                    )

                # The global scheduler limits provider submissions in this process.
                async with global_resource_scheduler.acquire("video"):
                    clip = await service.generate_video_clip(
                        source=result.source_snapshot,
                        keyframe_asset=keyframe,
                        keyframe_path=store.asset_path(job_id, keyframe.asset_id)[0],
                        shot=shot,
                        assets_dir=store.assets_dir(job_id),
                        job_id=job_id,
                        generation_attempt=1,
                        on_operation_started=on_started,
                        production_id=job.production_brief_job_id,
                        operation_id=claim_id,
                        estimated_cost=claim_cost,
                    )
                clip.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{clip.asset_id}"
                store.finalize_video_charge(
                    job_id, claim_id, succeeded=True, asset_id=clip.asset_id
                )
                return shot.shot_number, clip, None
            except (MediaGenerationError, ValueError) as exc:
                if str(exc).startswith("BUDGET_EXCEEDED"):
                    store.update_clip_operation(
                        job_id,
                        shot.shot_number,
                        status=ClipOperationStatus.BUDGET_EXCEEDED,
                        message="Animation skipped because generation budget was exceeded.",
                        error="Additional budget is required for this Veo generation."
                    )
                    return shot.shot_number, None, "BUDGET_EXCEEDED"

                if claim_id:
                    store.finalize_video_charge(
                        job_id, claim_id, succeeded=False, error=str(exc)
                    )
                    try:
                        from app.services.firestore_budget_service import FirestoreBudgetService
                        # Only release if no provider operation was submitted.
                        latest = store.get(job_id)
                        current_op = latest.result.clip_operations.get(shot.shot_number) if latest.result else None
                        if current_op and not current_op.provider_operation_name:
                            FirestoreBudgetService().release(claim_id)
                    except Exception:
                        logger.exception("Failed releasing budget reservation")
                logger.warning("Veo generation failed/skipped for shot %s: %s", shot.shot_number, exc)
                return shot.shot_number, None, str(exc)

    try:
        tasks = [asyncio.create_task(animate_one(shot)) for shot in pending_shots]
        generated = dict(existing_by_shot)
        completed = 0
        for future in asyncio.as_completed(tasks):
            shot_number, clip, error = await future
            completed += 1
            current = store.get(job_id)
            assert current.result is not None
            operation = current.result.clip_operations.get(shot_number)
            if operation is None:
                operation = ClipOperation(
                    shot_number=shot_number, status=ClipOperationStatus.QUEUED,
                    message=f"Shot {shot_number} queued", started_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc), target_generation_attempt=1,
                )
                current.result.clip_operations[shot_number] = operation
            operation.updated_at = datetime.now(timezone.utc)
            if clip is not None:
                generated[shot_number] = clip
                operation.status = ClipOperationStatus.READY
                operation.message = f"Animated shot {shot_number} is ready for AI review"
                operation.error = None
                operation.updated_asset_id = clip.asset_id
            else:
                operation.status = ClipOperationStatus.FAILED
                operation.message = f"Shot {shot_number} animation failed; other clips were preserved"
                operation.error = error
            current.result.video_clips = sorted(generated.values(), key=lambda item: item.shot_number)
            current.detail = {
                **current.detail,
                "clips_completed": completed,
                "clips_total": len(pending_shots),
            }
            current.message = f"Finished {completed} of {len(pending_shots)} parallel Veo shots"
            store.save(current)

        job = store.get(job_id)
        if job.stage != MediaStudioJobStage.FAILED:
            job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
            failed = sum(
                1
                for op in job.result.clip_operations.values()
                if op.status == ClipOperationStatus.FAILED
            )
            budget_blocked = sum(
                1
                for op in job.result.clip_operations.values()
                if op.status == ClipOperationStatus.BUDGET_EXCEEDED
            ) if job.result else 0
            job.message = (
                f"{failed} animated shot{'s' if failed != 1 else ''} failed; AI can retry only those shots"
                if failed else "All animated shots are ready for AI review"
            )
            job.detail = {**job.detail, "current_clip_shot": None, "current_task": None}
            store.save(job)
    except Exception:
        for task in locals().get("tasks", []):
            if not task.done():
                task.cancel()
        logger.exception("Parallel Veo clip generation failed")
        job = store.get(job_id)
        job.stage = MediaStudioJobStage.AWAITING_CLIP_REVIEW
        job.message = "Veo animation paused; completed clips were preserved"
        job.error = "ReviveAI could not finish all parallel Veo animations. Retry only the failed shots."
        store.save(job)


async def regenerate_video_clip_for_job(job_id: str, shot_number: int, settings: Settings, creator_note: Optional[str] = None) -> None:
    store = media_studio_job_store
    job = store.get(job_id)
    if not job.result or not job.result.animation_ready:
        store.update_clip_operation(
            job_id, shot_number, status=ClipOperationStatus.FAILED,
            message=f"Shot {shot_number} animation could not start",
            error="The approved keyframe set is no longer animation-ready.",
        )
        return
    shot = next((s for s in job.result.source_snapshot.storyboard.shots if s.shot_number == shot_number), None)
    keyframe = next((a for a in job.result.keyframes if a.shot_number == shot_number), None)
    old = next((c for c in job.result.video_clips if c.shot_number == shot_number), None)
    if not shot or not keyframe:
        store.update_clip_operation(
            job_id, shot_number, status=ClipOperationStatus.FAILED,
            message=f"Shot {shot_number} animation could not start",
            error="The storyboard shot or approved keyframe is unavailable.",
        )
        return
    # The old attempt may already have finished remotely, even if Media Studio
    # recorded FAILED after an application exception. Reattach before retrying.
    # Adoption is only for a missing local clip. A review-rejected clip already
    # exists and must be replaced by a NEW attempt, never mistaken for recovery.
    if old is None and recover_existing_veo_clip(job_id, shot_number, settings):
        return
    service = MediaGenerationService(settings)
    operation = job.result.clip_operations.get(shot_number)
    attempt = old.generation_attempt + 1 if old else int(getattr(operation, "target_generation_attempt", 2) or 2)
    claim_id: Optional[str] = None
    try:
        duration = service.supported_video_duration(shot.duration_seconds)
        from app.services.channel_autonomy_policy import channel_policy_store
        from app.services.firestore_budget_service import FirestoreBudgetService
        FirestoreBudgetService().ensure_production_budget(
            job.production_brief_job_id, job.channel_id,
            channel_policy_store.get(job.channel_id).max_total_production_cost_usd,
        )
        claim_id, _, claim_cost = store.claim_video_generation(
            job_id, shot_number, attempt, duration, settings
        )
        if claim_id == "budget_exceeded":
            raise MediaGenerationError("BUDGET_EXCEEDED")

        def on_started(operation_name: str) -> None:
            store.mark_video_submitted(job_id, shot_number, claim_id, operation_name)

        async with global_resource_scheduler.acquire("video"):
            clip = await service.generate_video_clip(
                source=job.result.source_snapshot,
                keyframe_asset=keyframe,
                keyframe_path=store.asset_path(job_id, keyframe.asset_id)[0],
                shot=shot,
                assets_dir=store.assets_dir(job_id),
                job_id=job_id,
                generation_attempt=attempt,
                on_operation_started=on_started,
                production_id=job.production_brief_job_id,
                operation_id=claim_id,
                estimated_cost=claim_cost,
                corrective_instruction=creator_note,
            )
        store.finalize_video_charge(
            job_id, claim_id, succeeded=True, asset_id=clip.asset_id
        )
        if creator_note:
            clip.review_note = creator_note
        clip.asset_url = f"/api/v1/youtube/media-jobs/{job_id}/assets/{clip.asset_id}"
        job = store.get(job_id)
        assert job.result is not None
        job.result.video_clips = [c for c in job.result.video_clips if c.shot_number != shot_number] + [clip]
        job.result.video_clips.sort(key=lambda c: c.shot_number)
        store.save(job)
        store.update_clip_operation(
            job_id, shot_number, status=ClipOperationStatus.READY,
            message=f"Shot {shot_number} animation version {attempt} is ready for review",
            updated_asset_id=clip.asset_id,
        )
    except (MediaGenerationError, ValueError) as exc:
        # A rejected budget reservation is not a Veo generation failure. Preserve
        # the previously accepted keyframe/clip and stop without another paid retry.
        # The claim may exist locally even if the provider was never submitted;
        # finalize it using the existing ledger reconciliation mechanism.
        if claim_id and claim_id != "budget_exceeded":
            store.finalize_video_charge(job_id, claim_id, succeeded=False, error=str(exc))
        budget_blocked = "BUDGET_EXCEEDED" in str(exc).upper()
        logger.warning("Localized Veo regeneration %s for shot %s: %s",
                       "budget-blocked" if budget_blocked else "failed", shot_number, exc)
        store.update_clip_operation(
            job_id, shot_number,
            status=ClipOperationStatus.BUDGET_EXCEEDED if budget_blocked else ClipOperationStatus.FAILED,
            message=(f"Shot {shot_number} paused: available Veo production budget is insufficient; approved assets preserved"
                     if budget_blocked else
                     (f"Shot {shot_number} regeneration failed; previous clip preserved" if old else f"Shot {shot_number} retry failed; approved keyframe preserved")),
            error=str(exc),
        )
    except Exception as exc:
        if claim_id:
            store.finalize_video_charge(job_id, claim_id, succeeded=False, error=str(exc))
        logger.exception("Localized Veo regeneration failed for shot %s", shot_number)
        store.update_clip_operation(
            job_id, shot_number, status=ClipOperationStatus.FAILED,
            message=(f"Shot {shot_number} regeneration failed; previous clip preserved" if old else f"Shot {shot_number} retry failed; approved keyframe preserved"),
            error=f"ReviveAI could not regenerate animated shot {shot_number}.",
        )
