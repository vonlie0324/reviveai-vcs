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
from app.models.content_dna import ContentDnaResult
from app.models.recovery import RecoveryJob, RecoveryJobStage
from app.models.youtube import AnalysisResult
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.recovery_service import RecoveryError, RecoveryService


logger = logging.getLogger(__name__)


class RecoveryJobNotFoundError(KeyError):
    pass


class RecoveryJobStore:
    """Tenant-scoped Recovery Intelligence jobs with Firestore durability."""

    def __init__(self, checkpoint_root: str = ".reviveai_checkpoints"):
        self._jobs: TenantScopedDict[str, RecoveryJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "recovery_jobs"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cloud = FirestoreJobRepository("recovery_jobs")

    def _path(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / f"{job_id}.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[RecoveryJob]:
        if not payload:
            return None
        try:
            return RecoveryJob.model_validate(payload)
        except Exception:
            return None

    def _persist_local(self, job: RecoveryJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud(self, job: RecoveryJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: RecoveryJob) -> None:
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist Recovery Intelligence job %s to Firestore", job.job_id)

        self._persist_local(job)

        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the Recovery Intelligence job") from cloud_error

    def _load_cloud(self, job_id: str) -> Optional[RecoveryJob]:
        try:
            return self._validate_payload(self._cloud.load(job_id))
        except Exception:
            logger.exception("Could not read Recovery Intelligence job %s from Firestore", job_id)
            return None

    def _load_local(self, job_id: str) -> Optional[RecoveryJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            return RecoveryJob.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _backfill_cloud(self, job: RecoveryJob) -> None:
        try:
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill local Recovery Intelligence job %s to Firestore", job.job_id)

    def _load_persisted(self, job_id: str) -> Optional[RecoveryJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud
        local = self._load_local(job_id)
        if local is not None:
            self._backfill_cloud(local)
        return local

    def create(self, content_dna_job_id: str, analysis_job_id: str) -> RecoveryJob:
        now = datetime.now(timezone.utc)
        job = RecoveryJob(
            job_id=f"recovery_{uuid4().hex}",
            content_dna_job_id=content_dna_job_id,
            analysis_job_id=analysis_job_id,
            stage=RecoveryJobStage.QUEUED,
            message="Recovery Intelligence queued",
            progress_current=0,
            progress_total=5,
            created_at=now,
            updated_at=now,
            detail={"methodology": "evidence_first"},
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def get(self, job_id: str) -> RecoveryJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise RecoveryJobNotFoundError(job_id)
            self._jobs[job_id] = job
            return job.model_copy(deep=True)

    def latest_for_analysis(self, analysis_job_id: str) -> Optional[RecoveryJob]:
        candidates: dict[str, RecoveryJob] = {}

        try:
            for _doc_id, payload in self._cloud.stream():
                job = self._validate_payload(payload)
                if job is not None and job.analysis_job_id == analysis_job_id:
                    candidates[job.job_id] = job
        except Exception:
            logger.exception("Could not list Recovery Intelligence jobs from Firestore; using local mirror")

        for path in tenant_scoped_root(self._root).glob("recovery_*.json"):
            try:
                job = RecoveryJob.model_validate_json(path.read_text(encoding="utf-8"))
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
            key=lambda item: (item.stage == RecoveryJobStage.COMPLETED, item.updated_at),
            reverse=True,
        )
        return items[0].model_copy(deep=True)

    def update_stage(self, job_id: str, stage: RecoveryJobStage, message: str, current: int, total: int, detail: Dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise RecoveryJobNotFoundError(job_id)
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
            if job is None:
                raise RecoveryJobNotFoundError(job_id)
            job.stage = RecoveryJobStage.COMPLETED
            job.message = "Recovery Intelligence ready"
            job.progress_current = job.progress_total
            job.detail = {
                "gemini_calls": result.gemini_calls,
                "content_gaps": len(result.content_gaps),
                "revival_opportunities": len(result.revival_opportunities),
                "recommendations": len(result.recommendations),
                "canonical_ideas": len(result.canonical_ideas),
                "diversity_balanced": True,
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
            if job is None:
                raise RecoveryJobNotFoundError(job_id)
            job.stage = RecoveryJobStage.FAILED
            job.message = "Recovery Intelligence stopped"
            job.error = error
            job.detail = {**job.detail, "retry_recommended": True}
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)


_settings = get_settings()
recovery_job_store = RecoveryJobStore(_settings.content_dna_checkpoint_dir)


async def run_recovery_job(
    job_id: str,
    analysis: AnalysisResult,
    dna: ContentDnaResult,
    settings: Settings,
) -> None:
    service = RecoveryService(settings)

    def on_stage(stage, message, current, total, detail):
        recovery_job_store.update_stage(job_id, stage, message, current, total, detail)

    try:
        result = await service.build(analysis, dna, on_stage)
        recovery_job_store.complete(job_id, result)
    except RecoveryError as exc:
        recovery_job_store.fail(job_id, str(exc))
    except Exception as exc:  # Defensive boundary: keep raw internals out of UI.
        recovery_job_store.fail(
            job_id,
            "Recovery Intelligence could not complete this pass. Retry the recovery analysis; your completed Content DNA remains intact.",
        )
