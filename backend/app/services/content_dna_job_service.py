from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.content_dna import (
    AiCharacterSynthesis,
    AiIdentityVoiceSynthesis,
    AiPatternSynthesis,
    AiThemeSynthesis,
    ContentDnaJob,
    ContentDnaJobStage,
    VideoContentClassification,
)
from app.models.youtube import AnalysisResult
from app.services.content_dna_service import ContentDnaCheckpoint, ContentDnaService, select_content_dna_videos
from app.services.firestore_job_repository import FirestoreJobRepository


logger = logging.getLogger(__name__)


class ContentDnaJobNotFoundError(KeyError):
    pass


class ContentDnaJobStore:
    """Tenant-scoped Content DNA jobs with Firestore durability and local mirroring."""

    def __init__(self, checkpoint_root: str = ".reviveai_checkpoints"):
        self._jobs: TenantScopedDict[str, ContentDnaJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "content_dna_jobs"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("content_dna_jobs")

    def _path(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / f"{job_id}.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[ContentDnaJob]:
        if not payload:
            return None
        try:
            return ContentDnaJob.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, job: ContentDnaJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud(self, job: ContentDnaJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: ContentDnaJob) -> None:
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Content DNA job %s to Firestore", job.job_id)

        self._persist_local(job)

        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the Content DNA job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[ContentDnaJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read Content DNA job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[ContentDnaJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return ContentDnaJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _backfill_cloud(self, job: ContentDnaJob) -> None:
        try:
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill local Content DNA job %s to Firestore", job.job_id)

    def _load_persisted(self, job_id: str) -> Optional[ContentDnaJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud
        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    def create(self, analysis_job_id: str, total_videos: int) -> ContentDnaJob:
        now = datetime.now(timezone.utc)
        job = ContentDnaJob(
            job_id=f"dna_{uuid4().hex}",
            analysis_job_id=analysis_job_id,
            stage=ContentDnaJobStage.QUEUED,
            message="Content DNA queued",
            progress_current=0,
            progress_total=total_videos,
            created_at=now,
            updated_at=now,
            detail={"performance_hidden_from_gemini": True},
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> ContentDnaJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise ContentDnaJobNotFoundError(job_id)
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def latest_for_analysis(self, analysis_job_id: str) -> Optional[ContentDnaJob]:
        candidates: dict[str, ContentDnaJob] = {}

        try:
            for _doc_id, payload in self._cloud.stream():
                job = self._validate_payload(payload)
                if job is not None and job.analysis_job_id == analysis_job_id:
                    candidates[job.job_id] = job
        except Exception:
            logger.exception("Could not list Content DNA jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("dna_*.json"):
            try:
                job = ContentDnaJob.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if job.analysis_job_id != analysis_job_id:
                continue
            if job.job_id not in candidates:
                candidates[job.job_id] = job
                self._backfill_cloud(job)

        with self._lock:
            for job in self._jobs.values():
                if job.analysis_job_id == analysis_job_id:
                    candidates[job.job_id] = job

        if not candidates:
            return None
        items = list(candidates.values())
        items.sort(
            key=lambda item: (item.stage == ContentDnaJobStage.COMPLETED, item.updated_at),
            reverse=True,
        )
        return items[0].model_copy(deep=True)

    def update_stage(self, job_id: str, stage: ContentDnaJobStage, message: str, current: int, total: int, detail: Dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise ContentDnaJobNotFoundError(job_id)
            job.stage = stage
            job.message = message
            job.progress_current = current
            job.progress_total = total
            job.detail = detail
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def complete(self, job_id: str, result) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise ContentDnaJobNotFoundError(job_id)
            job.stage = ContentDnaJobStage.COMPLETED
            job.message = "Content DNA ready"
            job.progress_current = job.progress_total
            job.detail = {
                "videos_classified": result.videos_classified,
                "visuals_analyzed": result.visuals_analyzed,
                "gemini_calls": result.gemini_calls,
                "performance_hidden_from_gemini": True,
                "performance_connection": "backend_only",
                "overall_percent": 100,
            }
            job.result = result
            job.error = None
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if not job:
                raise ContentDnaJobNotFoundError(job_id)
            job.stage = ContentDnaJobStage.FAILED
            job.message = "Content DNA stopped"
            job.error = error
            job.detail = {**job.detail, "retry_recommended": True}
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)


class ContentDnaCheckpointStore:
    """Persistent checkpoint cache for expensive blind video classifications.

    Checkpoints are keyed by a fingerprint of channel_id + selected video IDs, not
    by the transient analysis job ID. Re-running M1B after a backend restart can
    therefore still reuse the same classifications when the public archive is
    unchanged.
    """

    def __init__(self):
        self._memory: TenantScopedDict[str, ContentDnaCheckpoint] = TenantScopedDict()
        self._lock = Lock()

    @staticmethod
    def fingerprint(analysis: AnalysisResult, settings: Settings) -> str:
        videos = select_content_dna_videos(analysis.videos, settings.content_dna_max_videos)
        raw = analysis.channel.channel_id + "|fast-dna-v1|" + "|".join(video.video_id for video in videos)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _path(settings: Settings, fingerprint: str) -> Path:
        base = Path(settings.content_dna_checkpoint_dir)
        if not base.is_absolute():
            base = Path.cwd() / base
        return tenant_scoped_root(base) / "content_dna_cache" / f"{fingerprint}.json"

    def get(self, analysis, settings: Optional[Settings] = None) -> Optional[ContentDnaCheckpoint]:
        # Backward-compatible string keys are kept for unit tests and simple in-memory use.
        if isinstance(analysis, str):
            with self._lock:
                item = self._memory.get(analysis)
                return self._copy(item) if item is not None else None
        if settings is None:
            raise TypeError("settings is required when reading a persistent analysis checkpoint")
        fingerprint = self.fingerprint(analysis, settings)
        with self._lock:
            item = self._memory.get(fingerprint)
            if item is not None:
                return self._copy(item)

        path = self._path(settings, fingerprint)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            checkpoint = ContentDnaCheckpoint(
                classifications=[VideoContentClassification.model_validate(item) for item in payload["classifications"]],
                visuals_analyzed=int(payload.get("visuals_analyzed", 0)),
                successful_classifications=int(payload.get("successful_classifications", 0)),
                total_videos=int(payload["total_videos"]),
                identity_voice=(
                    AiIdentityVoiceSynthesis.model_validate(payload["identity_voice"])
                    if payload.get("synthesis_checkpoint_version") == "m1c6" and payload.get("identity_voice")
                    else None
                ),
                themes=(
                    AiThemeSynthesis.model_validate(payload["themes"])
                    if payload.get("synthesis_checkpoint_version") == "m1c6" and payload.get("themes")
                    else None
                ),
                characters=(
                    AiCharacterSynthesis.model_validate(payload["characters"])
                    if payload.get("synthesis_checkpoint_version") == "m1c6" and payload.get("characters")
                    else None
                ),
                patterns=(
                    AiPatternSynthesis.model_validate(payload["patterns"])
                    if payload.get("synthesis_checkpoint_version") == "m1c6" and payload.get("patterns")
                    else None
                ),
            )
        except Exception:
            return None

        with self._lock:
            self._memory[fingerprint] = checkpoint
        return self._copy(checkpoint)

    def put(self, analysis, settings, checkpoint: Optional[ContentDnaCheckpoint] = None) -> None:
        # Backward-compatible put(key, checkpoint) for tests / ephemeral callers.
        if isinstance(analysis, str):
            item = settings if checkpoint is None else checkpoint
            if not isinstance(item, ContentDnaCheckpoint):
                raise TypeError("checkpoint is required")
            with self._lock:
                self._memory[analysis] = self._copy(item)
            return
        if checkpoint is None or not isinstance(settings, Settings):
            raise TypeError("settings and checkpoint are required for persistent analysis checkpoints")
        fingerprint = self.fingerprint(analysis, settings)
        copy = self._copy(checkpoint)
        with self._lock:
            self._memory[fingerprint] = copy

        path = self._path(settings, fingerprint)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fingerprint": fingerprint,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "total_videos": copy.total_videos,
            "visuals_analyzed": copy.visuals_analyzed,
            "successful_classifications": copy.successful_classifications,
            "classifications": [item.model_dump(mode="json") for item in copy.classifications],
            "synthesis_checkpoint_version": "m1c6",
            "identity_voice": copy.identity_voice.model_dump(mode="json") if copy.identity_voice else None,
            "themes": copy.themes.model_dump(mode="json") if copy.themes else None,
            "characters": copy.characters.model_dump(mode="json") if copy.characters else None,
            "patterns": copy.patterns.model_dump(mode="json") if copy.patterns else None,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    @staticmethod
    def _copy(item: ContentDnaCheckpoint) -> ContentDnaCheckpoint:
        return ContentDnaCheckpoint(
            classifications=[record.model_copy(deep=True) for record in item.classifications],
            visuals_analyzed=item.visuals_analyzed,
            successful_classifications=item.successful_classifications,
            total_videos=item.total_videos,
            identity_voice=item.identity_voice.model_copy(deep=True) if item.identity_voice else None,
            themes=item.themes.model_copy(deep=True) if item.themes else None,
            characters=item.characters.model_copy(deep=True) if item.characters else None,
            patterns=item.patterns.model_copy(deep=True) if item.patterns else None,
        )


_settings = get_settings()
content_dna_job_store = ContentDnaJobStore(_settings.content_dna_checkpoint_dir)
content_dna_checkpoint_store = ContentDnaCheckpointStore()


async def run_content_dna_job(job_id: str, analysis: AnalysisResult, settings: Settings) -> None:
    service = ContentDnaService(settings)
    checkpoint = content_dna_checkpoint_store.get(analysis, settings)

    def on_stage(stage, message, current, total, detail) -> None:
        content_dna_job_store.update_stage(job_id, stage, message, current, total, detail)

    def on_checkpoint(next_checkpoint: ContentDnaCheckpoint) -> None:
        content_dna_checkpoint_store.put(analysis, settings, next_checkpoint)

    try:
        result = await service.build(
            analysis,
            on_stage,
            checkpoint=checkpoint,
            on_checkpoint=on_checkpoint,
        )
        content_dna_job_store.complete(job_id, result)
    except Exception as exc:
        content_dna_job_store.fail(job_id, str(exc))
