from app.core.tenant import tenant_context
from app.services.content_dna_job_service import ContentDnaJobStore
from app.services.recovery_job_service import RecoveryJobStore


def test_latest_content_dna_for_analysis_is_tenant_scoped(tmp_path):
    store = ContentDnaJobStore(str(tmp_path))
    with tenant_context("creator-a"):
        first = store.create("analysis-a", 3)
        second = store.create("analysis-a", 3)
        assert store.latest_for_analysis("analysis-a").job_id == second.job_id
    with tenant_context("creator-b"):
        assert store.latest_for_analysis("analysis-a") is None
    with tenant_context("creator-a"):
        assert store.latest_for_analysis("analysis-a").job_id in {first.job_id, second.job_id}


def test_latest_recovery_for_analysis_is_tenant_scoped(tmp_path):
    store = RecoveryJobStore(str(tmp_path))
    with tenant_context("creator-a"):
        first = store.create("dna-one", "analysis-a")
        second = store.create("dna-two", "analysis-a")
        assert store.latest_for_analysis("analysis-a").job_id == second.job_id
    with tenant_context("creator-b"):
        assert store.latest_for_analysis("analysis-a") is None
    with tenant_context("creator-a"):
        assert store.latest_for_analysis("analysis-a").job_id in {first.job_id, second.job_id}
