from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from app.core.tenant import (
    TenantScopedDict,
    current_tenant_id,
    tenant_bound,
    tenant_context,
    tenant_namespace,
)
from app.models.delivery_qc import DeliveryQcOverallStatus, DeliveryQcReport
from app.services.delivery_qc_service import DeliveryQcReportNotFoundError, DeliveryQcStore
from app.services.job_service import AnalysisJobStore, JobNotFoundError


def test_analysis_jobs_are_isolated_in_memory_and_on_disk(tmp_path):
    store = AnalysisJobStore(str(tmp_path))

    with tenant_context("firebase-user-a"):
        job = store.create("https://youtube.com/@creator-a")
        assert store.get(job.job_id).url.endswith("@creator-a")
        tenant_a_namespace = tenant_namespace()

    with tenant_context("firebase-user-b"):
        assert tenant_namespace() != tenant_a_namespace
        with pytest.raises(JobNotFoundError):
            store.get(job.job_id)

    with tenant_context("firebase-user-a"):
        assert store.get(job.job_id).job_id == job.job_id

    # The raw Firebase UID is never used as a filesystem path segment.
    persisted = list(tmp_path.rglob(f"{job.job_id}.json"))
    assert len(persisted) == 1
    assert "firebase-user-a" not in str(persisted[0])
    assert tenant_a_namespace in str(persisted[0])


def test_delivery_qc_cache_cannot_leak_between_tenants(tmp_path):
    store = DeliveryQcStore(str(tmp_path))
    report = DeliveryQcReport(
        report_id="qc_private",
        audio_job_id="audio_private",
        assembly_job_id="assembly_private",
        audio_version=1,
        generated_at=datetime.now(timezone.utc),
        overall_status=DeliveryQcOverallStatus.READY,
        ready_for_delivery=True,
    )

    with tenant_context("owner-a"):
        store.save(report)
        assert store.get("audio_private").report_id == "qc_private"

    with tenant_context("owner-b"):
        with pytest.raises(DeliveryQcReportNotFoundError):
            store.get("audio_private")


def test_tenant_scoped_dict_hides_same_key_from_other_user():
    values: TenantScopedDict[str, str] = TenantScopedDict()
    with tenant_context("one"):
        values["same-resource-id"] = "one-value"
        assert values.get("same-resource-id") == "one-value"

    with tenant_context("two"):
        assert values.get("same-resource-id") is None
        values["same-resource-id"] = "two-value"
        assert values.get("same-resource-id") == "two-value"

    with tenant_context("one"):
        assert values.get("same-resource-id") == "one-value"


def test_background_task_keeps_creator_tenant_context():
    seen: list[str] = []

    async def task():
        seen.append(current_tenant_id())

    with tenant_context("creator-a"):
        bound = tenant_bound(task)

    # Execute after the caller has switched context; the captured owner must win.
    with tenant_context("creator-b"):
        asyncio.run(bound())
        assert current_tenant_id() == "creator-b"

    assert seen == ["creator-a"]


def test_creator_youtube_audio_library_paths_are_tenant_scoped(tmp_path):
    from app.core.config import Settings
    from app.services.youtube_audio_library_service import YouTubeAudioLibrary

    settings = Settings(
        _env_file=None,
        audio_youtube_library_catalog_path=str(tmp_path / "music" / "catalog.json"),
        audio_youtube_library_dir=str(tmp_path / "music" / "youtube"),
    )
    library = YouTubeAudioLibrary()

    with tenant_context("creator-one"):
        one_catalog = library._catalog_path(settings)
        one_root = library._root(settings)

    with tenant_context("creator-two"):
        two_catalog = library._catalog_path(settings)
        two_root = library._root(settings)

    assert one_catalog != two_catalog
    assert one_root != two_root
    assert "creator-one" not in str(one_catalog)
    assert "creator-two" not in str(two_catalog)
    assert one_catalog.parent.name != two_catalog.parent.name
