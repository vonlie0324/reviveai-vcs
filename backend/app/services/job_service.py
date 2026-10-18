from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.youtube import AnalysisJob, JobStage
from app.services.firestore_job_repository import FirestoreJobRepository


logger = logging.getLogger(__name__)


class JobNotFoundError(KeyError):
    pass


class AnalysisJobStore:
    """Tenant-scoped channel-analysis jobs with Firestore durability.

    Firestore is authoritative across local development and Cloud Run. Existing
    JSON checkpoints are retained as a local mirror and are transparently
    backfilled into Firestore when encountered.
    """

    def __init__(self, checkpoint_root: str = ".reviveai_checkpoints"):
        self._jobs: TenantScopedDict[str, AnalysisJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "channel_analysis"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("analysis_jobs")

    def _path(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / f"{job_id}.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[AnalysisJob]:
        if not payload:
            return None
        try:
            return AnalysisJob.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, job: AnalysisJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud(self, job: AnalysisJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: AnalysisJob) -> None:
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist analysis job %s to Firestore", job.job_id)

        self._persist_local(job)

        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the analysis job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[AnalysisJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read analysis job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[AnalysisJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return AnalysisJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _backfill_cloud(self, job: AnalysisJob) -> None:
        try:
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill local analysis job %s to Firestore", job.job_id)

    def _load_persisted(self, job_id: str) -> Optional[AnalysisJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud

        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    def create(self, url: str) -> AnalysisJob:
        now = datetime.now(timezone.utc)
        job = AnalysisJob(
            job_id=f"ana_{uuid4().hex}",
            url=url,
            stage=JobStage.QUEUED,
            message="Analysis queued",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> AnalysisJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def _iter_persisted_jobs(self):
        """Yield tenant-scoped persisted analysis jobs, preferring Firestore.

        Firestore is authoritative in production. Local JSON checkpoints are included
        as a development/backward-compatibility fallback and are de-duplicated by id.
        """
        seen: set[str] = set()

        try:
            for job_id, payload in self._cloud.stream():
                job = self._validate_payload(payload)
                if job is None:
                    continue
                seen.add(job_id)
                yield job
        except Exception:
            logger.exception("Could not enumerate analysis jobs from Firestore")

        try:
            root = tenant_scoped_root(self._root)
            if root.exists():
                for path in root.glob("ana_*.json"):
                    job_id = path.stem
                    if job_id in seen:
                        continue
                    try:
                        job = AnalysisJob.model_validate_json(path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    seen.add(job_id)
                    yield job
        except Exception:
            logger.exception("Could not enumerate local analysis checkpoints")

    def latest_completed_for_channel(self, channel_id: str) -> AnalysisJob:
        """Return the newest durable completed analysis for a YouTube channel."""
        wanted = (channel_id or "").strip()
        if not wanted:
            raise JobNotFoundError(channel_id)

        matches: list[AnalysisJob] = []
        with self._lock:
            for job in self._iter_persisted_jobs():
                if job.stage != JobStage.COMPLETED or not job.result:
                    continue
                channel = getattr(job.result, "channel", None)
                if str(getattr(channel, "channel_id", "") or "").strip() != wanted:
                    continue
                matches.append(job)

        if not matches:
            raise JobNotFoundError(channel_id)

        matches.sort(key=lambda item: item.updated_at, reverse=True)
        latest = matches[0]
        with self._lock:
            self._jobs[latest.job_id] = latest
        return latest.model_copy(deep=True)

    def completed_channel_index(self) -> list[dict]:
        """Return one lightweight, newest-analysis summary per channel.

        This is intentionally metadata-only so a new browser/device can reconstruct
        the channel workspace without downloading every historical analysis payload.
        """
        latest_by_channel: dict[str, AnalysisJob] = {}
        with self._lock:
            for job in self._iter_persisted_jobs():
                if job.stage != JobStage.COMPLETED or not job.result:
                    continue
                channel = getattr(job.result, "channel", None)
                channel_id = str(getattr(channel, "channel_id", "") or "").strip()
                if not channel_id:
                    continue
                current = latest_by_channel.get(channel_id)
                if current is None or job.updated_at > current.updated_at:
                    latest_by_channel[channel_id] = job

        items: list[dict] = []
        for channel_id, job in latest_by_channel.items():
            result = job.result
            channel = result.channel
            thumbnails = getattr(channel, "thumbnails", None)
            thumbnail_url = None
            if thumbnails is not None:
                for key in ("high", "medium", "default"):
                    value = getattr(thumbnails, key, None)
                    if value:
                        thumbnail_url = str(value)
                        break

            summary = getattr(result, "summary", None)
            retrieved_videos = getattr(summary, "retrieved_videos", None) if summary is not None else None
            public_video_count = getattr(channel, "public_video_count_reported", None)

            items.append({
                "channel_id": channel_id,
                "analysis_job_id": job.job_id,
                "channel_url": str(getattr(channel, "channel_url", "") or job.url),
                "title": str(getattr(channel, "title", "") or "YouTube channel"),
                "handle": getattr(channel, "custom_url", None),
                "thumbnail_url": thumbnail_url,
                "subscriber_count": getattr(channel, "subscriber_count", None),
                "public_video_count": public_video_count if public_video_count is not None else retrieved_videos,
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
            })

        items.sort(key=lambda item: item["updated_at"], reverse=True)
        return items

    def update_stage(self, job_id: str, stage: JobStage, message: str, detail: Dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            job.stage = stage
            job.message = message
            job.detail = detail
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def complete(self, job_id: str, result) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            job.stage = JobStage.COMPLETED
            job.message = "Channel intelligence ready"
            job.detail = {"videos_loaded": len(result.videos)}
            job.result = result
            job.error = None
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise JobNotFoundError(job_id)
            job.stage = JobStage.FAILED
            job.message = "Analysis failed"
            job.error = error
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)


_settings = get_settings()
job_store = AnalysisJobStore(_settings.content_dna_checkpoint_dir)


async def run_analysis_job(job_id: str, url: str, settings: Settings) -> None:
    from app.services.youtube_service import YouTubeService

    service = YouTubeService(settings)

    def on_stage(stage: JobStage, message: str, detail: Dict) -> None:
        job_store.update_stage(job_id, stage, message, detail)

    try:
        result = await service.analyze(url, on_stage)
        job_store.complete(job_id, result)
    except Exception as exc:
        # Persist the user-facing failure state and also emit a Cloud Run traceback.
        # This makes asynchronous Cloud Task failures diagnosable without changing
        # the API contract returned to the frontend.
        logger.exception("Channel analysis job %s failed", job_id)
        job_store.fail(job_id, str(exc))
