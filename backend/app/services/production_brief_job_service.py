from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.services.firestore_job_repository import FirestoreJobRepository
from app.models.content_dna import ContentDnaResult
from app.models.production_brief import (
    DirectionFidelityStatus,
    ProductionBriefHistoryEntry,
    ProductionBriefJob,
    ProductionBriefJobStage,
    ProductionFidelityMode,
    ProductionReviewStatus,
    SourceDirectionSnapshot,
)
from app.models.recovery import NextContentRecommendation
from app.models.youtube import AnalysisResult
from app.services.production_brief_service import ProductionBriefError, ProductionBriefService


logger = logging.getLogger(__name__)


class ProductionBriefJobNotFoundError(KeyError):
    pass


class ProductionBriefJobStore:
    """In-memory working set backed by disk history.

    M2A.7 deliberately persists the full ProductionBriefJob document. This makes the
    human-selected M1D direction immutable once production starts and allows completed
    production briefs to remain discoverable even after Recovery Intelligence is rerun
    or the backend process restarts.
    """

    def __init__(
        self,
        checkpoint_root: str = ".reviveai_checkpoints",
        stale_after_seconds: float = 240.0,
    ):
        self._jobs: TenantScopedDict[str, ProductionBriefJob] = TenantScopedDict()
        self._lock = Lock()
        self._root = Path(checkpoint_root) / "production_history"
        self._cloud = FirestoreJobRepository("production_brief_jobs")
        self._stale_after_seconds = max(60.0, float(stale_after_seconds))
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _is_terminal(job: ProductionBriefJob) -> bool:
        return job.stage in {ProductionBriefJobStage.COMPLETED, ProductionBriefJobStage.FAILED}

    def _mark_stale_if_needed(self, job: ProductionBriefJob) -> bool:
        """Fail orphaned in-progress jobs after a backend reload/worker loss.

        Active Gemini attempts persist a heartbeat before and after each request. A
        job that remains unchanged well beyond the request timeout is therefore no
        longer making progress and should expose Retry instead of polling forever.
        """
        if self._is_terminal(job):
            return False
        now = datetime.now(timezone.utc)
        updated_at = job.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age_seconds = max(0.0, (now - updated_at).total_seconds())
        if age_seconds < self._stale_after_seconds:
            return False

        job.stage = ProductionBriefJobStage.FAILED
        job.message = "Production brief paused after the worker stopped responding"
        job.error = (
            "ReviveAI stopped receiving progress from this production run. "
            "Retry the production brief; completed stages remain checkpointed."
        )
        job.detail = {
            **job.detail,
            "retry_recommended": True,
            "checkpointed_stages_reusable": True,
            "stale_worker_detected": True,
            "stale_after_seconds": self._stale_after_seconds,
            "stale_age_seconds": round(age_seconds, 1),
            "gemini_call_state": "stale_worker",
        }
        job.updated_at = now
        return True

    @staticmethod
    def _snapshot_hash(recommendation: NextContentRecommendation) -> str:
        raw = json.dumps(
            recommendation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

    @classmethod
    def capture_snapshot(
        cls,
        *,
        recovery_job_id: str,
        recovery_generated_at: Optional[datetime],
        channel_id: str,
        channel_title: str,
        recommendation: NextContentRecommendation,
    ) -> SourceDirectionSnapshot:
        return SourceDirectionSnapshot(
            snapshot_id=f"source_{uuid4().hex}",
            captured_at=datetime.now(timezone.utc),
            recovery_job_id=recovery_job_id,
            recovery_generated_at=recovery_generated_at,
            channel_id=channel_id,
            channel_title=channel_title,
            source_hash=cls._snapshot_hash(recommendation),
            immutable=True,
            recommendation=recommendation.model_copy(deep=True),
        )

    def create(
        self,
        *,
        recovery_job_id: str,
        content_dna_job_id: str,
        analysis_job_id: str,
        channel_id: str,
        channel_title: str,
        recommendation: NextContentRecommendation,
        recovery_generated_at: Optional[datetime],
        fidelity_mode: ProductionFidelityMode = ProductionFidelityMode.STANDARD,
        source_snapshot: Optional[SourceDirectionSnapshot] = None,
    ) -> ProductionBriefJob:
        now = datetime.now(timezone.utc)
        snapshot = source_snapshot or self.capture_snapshot(
            recovery_job_id=recovery_job_id,
            recovery_generated_at=recovery_generated_at,
            channel_id=channel_id,
            channel_title=channel_title,
            recommendation=recommendation,
        )
        job = ProductionBriefJob(
            job_id=f"production_{uuid4().hex}",
            source_snapshot=snapshot,
            channel_id=channel_id,
            recovery_job_id=recovery_job_id,
            content_dna_job_id=content_dna_job_id,
            analysis_job_id=analysis_job_id,
            recommendation_id=snapshot.recommendation.recommendation_id,
            fidelity_mode=fidelity_mode,
            stage=ProductionBriefJobStage.QUEUED,
            message="Production brief queued",
            progress_current=0,
            progress_total=5,
            created_at=now,
            updated_at=now,
            detail={
                "human_selected": True,
                "creative_firewall": True,
                "fidelity_mode": fidelity_mode,
                "source_snapshot_id": snapshot.snapshot_id,
                "source_snapshot_hash": snapshot.source_hash,
                "source_captured_at": snapshot.captured_at.isoformat(),
            },
        )
        with self._lock:
            self._jobs[job.job_id] = job
            self._persist(job)
        return job.model_copy(deep=True)

    def create_from_snapshot(
        self,
        source_job: ProductionBriefJob,
        *,
        fidelity_mode: ProductionFidelityMode,
    ) -> ProductionBriefJob:
        """Create a fresh run without consulting the current M1D recommendation set."""
        return self.create(
            recovery_job_id=source_job.recovery_job_id,
            content_dna_job_id=source_job.content_dna_job_id,
            analysis_job_id=source_job.analysis_job_id,
            channel_id=source_job.channel_id,
            channel_title=source_job.source_snapshot.channel_title,
            recommendation=source_job.source_snapshot.recommendation,
            recovery_generated_at=source_job.source_snapshot.recovery_generated_at,
            fidelity_mode=fidelity_mode,
            source_snapshot=source_job.source_snapshot.model_copy(deep=True),
        )

    def _path(self, job_id: str) -> Path:
        return tenant_scoped_root(self._root) / f"{job_id}.json"

    def _persist_local(self, job: ProductionBriefJob) -> None:
        path = self._path(job.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _persist_cloud(self, job: ProductionBriefJob) -> None:
        self._cloud.save(job.job_id, job.model_dump(mode="json"))

    def _persist(self, job: ProductionBriefJob) -> None:
        """Dual-write durable Firestore state plus a local checkpoint mirror.

        Firestore is the cross-environment source of truth. The local file remains
        useful for developer recovery and as a migration source for older jobs.
        Production refuses to silently acknowledge a write that Firestore rejected.
        """
        cloud_error: Exception | None = None
        try:
            self._persist_cloud(job)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist production brief %s to Firestore", job.job_id)

        # Keep the historical local checkpoint behavior as a mirror/fallback.
        self._persist_local(job)

        if cloud_error is not None and get_settings().app_env.strip().lower() in {"production", "prod"}:
            raise RuntimeError("Durable Firestore persistence failed for the production brief") from cloud_error

    def _validate_payload(self, payload: dict) -> Optional[ProductionBriefJob]:
        try:
            job = ProductionBriefJob.model_validate(payload)
            if job.source_snapshot.source_hash != self._snapshot_hash(job.source_snapshot.recommendation):
                logger.warning("Ignoring production brief %s because its immutable source hash is invalid", job.job_id)
                return None
            return job
        except Exception:
            return None

    def _load_cloud(self, job_id: str) -> Optional[ProductionBriefJob]:
        try:
            payload = self._cloud.load(job_id)
        except Exception:
            logger.exception("Could not read production brief %s from Firestore", job_id)
            return None
        return self._validate_payload(payload) if payload else None

    def _load_local(self, job_id: str) -> Optional[ProductionBriefJob]:
        path = self._path(job_id)
        if not path.exists():
            return None
        try:
            job = ProductionBriefJob.model_validate_json(path.read_text(encoding="utf-8"))
            if job.source_snapshot.source_hash != self._snapshot_hash(job.source_snapshot.recommendation):
                return None
            return job
        except Exception:
            return None

    def _backfill_cloud(self, job: ProductionBriefJob) -> None:
        try:
            self._persist_cloud(job)
        except Exception:
            logger.exception("Could not backfill local production brief %s to Firestore", job.job_id)

    def _load_persisted(self, job_id: str) -> Optional[ProductionBriefJob]:
        cloud = self._load_cloud(job_id)
        if cloud is not None:
            return cloud

        local = self._load_local(job_id)
        if local is not None:
            # Transparent one-time migration for existing localhost checkpoints.
            self._backfill_cloud(local)
        return local

    def get(self, job_id: str) -> ProductionBriefJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = self._load_persisted(job_id)
                if job is None:
                    raise ProductionBriefJobNotFoundError(job_id)
                self._jobs[job_id] = job
            if self._mark_stale_if_needed(job):
                self._jobs[job_id] = job
                self._persist(job)
            return job.model_copy(deep=True)

    def update_stage(self, job_id: str, stage, message: str, current: int, total: int, detail: Dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise ProductionBriefJobNotFoundError(job_id)
            job.stage = stage
            job.message = message
            job.progress_current = current
            job.progress_total = total
            job.detail = {**job.detail, **detail}
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def complete(self, job_id: str, result) -> None:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise ProductionBriefJobNotFoundError(job_id)
            job.stage = ProductionBriefJobStage.COMPLETED
            job.message = "Production brief ready for human review"
            job.progress_current = job.progress_total
            job.detail = {
                **job.detail,
                "gemini_calls": result.gemini_calls,
                "storyboard_shots": len(result.storyboard.shots),
                "review_status": result.review_status,
                "creative_firewall": True,
                "direction_fidelity": result.direction_fidelity.status,
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
                raise ProductionBriefJobNotFoundError(job_id)
            job.stage = ProductionBriefJobStage.FAILED
            job.message = "Production brief stopped"
            job.error = error
            job.detail = {**job.detail, "retry_recommended": True, "checkpointed_stages_reusable": True}
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)

    def approve(self, job_id: str) -> ProductionBriefJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise ProductionBriefJobNotFoundError(job_id)
            if job.result is None or job.stage != ProductionBriefJobStage.COMPLETED:
                raise ValueError("Complete the production brief before approving it.")
            if job.result.consistency_report.status != "PASS":
                raise ValueError("Resolve the Production Identity consistency blockers before approving this brief.")
            if job.result.direction_fidelity.status == DirectionFidelityStatus.REVIEW_REQUIRED:
                raise ValueError(
                    "Review the Direction Fidelity changes first. Keep the original direction or explicitly accept the creative adaptation before approval."
                )
            job.result.review_status = ProductionReviewStatus.APPROVED
            job.result.reviewed_at = datetime.now(timezone.utc)
            job.detail = {**job.detail, "review_status": ProductionReviewStatus.APPROVED}
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)
            return job.model_copy(deep=True)

    def accept_adaptation(self, job_id: str) -> ProductionBriefJob:
        with self._lock:
            job = self._jobs.get(job_id) or self._load_persisted(job_id)
            if job is None:
                raise ProductionBriefJobNotFoundError(job_id)
            if job.result is None or job.stage != ProductionBriefJobStage.COMPLETED:
                raise ValueError("Complete the production brief before reviewing direction fidelity.")
            report = job.result.direction_fidelity
            if report.status != DirectionFidelityStatus.REVIEW_REQUIRED:
                return job.model_copy(deep=True)
            report.status = DirectionFidelityStatus.ADAPTATION_ACCEPTED
            report.adaptation_accepted = True
            report.accepted_at = datetime.now(timezone.utc)
            job.detail = {
                **job.detail,
                "direction_fidelity": DirectionFidelityStatus.ADAPTATION_ACCEPTED,
                "creative_adaptation_accepted": True,
            }
            job.updated_at = datetime.now(timezone.utc)
            self._jobs[job_id] = job
            self._persist(job)
            return job.model_copy(deep=True)

    def list_history(self, *, channel_id: Optional[str] = None, analysis_job_id: Optional[str] = None) -> List[ProductionBriefHistoryEntry]:
        jobs: Dict[str, ProductionBriefJob] = {}

        # Firestore is authoritative across localhost, Firebase Hosting, and Cloud Run.
        try:
            for _doc_id, payload in self._cloud.stream():
                job = self._validate_payload(payload)
                if job is not None:
                    jobs[job.job_id] = job
        except Exception:
            logger.exception("Could not list production brief history from Firestore; using local mirror")

        # Merge old/local checkpoints and opportunistically backfill anything that
        # predates Firestore persistence. This is what makes existing localhost
        # productions become visible to Cloud Run without regenerating them.
        for path in sorted(tenant_scoped_root(self._root).glob("production_*.json")):
            try:
                local = ProductionBriefJob.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if local.source_snapshot.source_hash != self._snapshot_hash(local.source_snapshot.recommendation):
                continue
            if local.job_id not in jobs:
                jobs[local.job_id] = local
                self._backfill_cloud(local)

        entries: list[ProductionBriefHistoryEntry] = []
        for job in jobs.values():
            if channel_id and job.channel_id != channel_id:
                continue
            if analysis_job_id and job.analysis_job_id != analysis_job_id:
                continue
            entries.append(
                ProductionBriefHistoryEntry(
                    job_id=job.job_id,
                    channel_id=job.channel_id,
                    analysis_job_id=job.analysis_job_id,
                    recovery_job_id=job.recovery_job_id,
                    captured_at=job.source_snapshot.captured_at,
                    updated_at=job.updated_at,
                    stage=job.stage.value if hasattr(job.stage, "value") else str(job.stage),
                    review_status=job.result.review_status if job.result else None,
                    source_snapshot=job.source_snapshot,
                    working_title=job.result.creative_direction.working_title if job.result else None,
                    consistency_status=job.result.consistency_report.status if job.result else None,
                    direction_fidelity_status=job.result.direction_fidelity.status if job.result else None,
                )
            )
        entries.sort(key=lambda item: item.updated_at, reverse=True)
        return entries


_settings = get_settings()
production_brief_job_store = ProductionBriefJobStore(
    _settings.content_dna_checkpoint_dir,
    stale_after_seconds=_settings.production_brief_stale_seconds,
)


async def run_production_brief_job(
    job_id: str,
    analysis: AnalysisResult,
    dna: ContentDnaResult,
    source_snapshot: SourceDirectionSnapshot,
    settings: Settings,
    fidelity_mode: ProductionFidelityMode = ProductionFidelityMode.STANDARD,
) -> None:
    # Production identity is the immutable brief job ID; do not charge channel
    # intelligence operations to this production ledger.
    service = ProductionBriefService(settings)
    service.configure_budget_identity(job_id, analysis.channel.channel_id)

    def on_stage(stage, message, current, total, detail):
        production_brief_job_store.update_stage(job_id, stage, message, current, total, detail)

    try:
        result = await service.build(
            analysis,
            dna,
            source_snapshot.recommendation,
            on_stage,
            fidelity_mode=fidelity_mode,
            source_snapshot=source_snapshot,
        )
        production_brief_job_store.complete(job_id, result)
    except ProductionBriefError as exc:
        production_brief_job_store.fail(job_id, str(exc))
    except Exception:
        logger.exception("Unexpected production brief worker failure job_id=%s", job_id)
        production_brief_job_store.fail(
            job_id,
            "ReviveAI could not finish this production brief. Retry the brief; the immutable source direction snapshot remains unchanged.",
        )
