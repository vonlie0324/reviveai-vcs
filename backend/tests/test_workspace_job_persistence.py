from app.services.content_dna_job_service import ContentDnaJobStore
from app.services.job_service import AnalysisJobStore
from app.services.recovery_job_service import RecoveryJobStore


def test_analysis_job_survives_store_recreation(tmp_path):
    store = AnalysisJobStore(str(tmp_path))
    created = store.create("https://youtube.com/@example")

    restored = AnalysisJobStore(str(tmp_path)).get(created.job_id)

    assert restored.job_id == created.job_id
    assert restored.url == created.url
    assert restored.stage == created.stage


def test_content_dna_job_survives_store_recreation(tmp_path):
    store = ContentDnaJobStore(str(tmp_path))
    created = store.create("ana_test", 12)

    restored = ContentDnaJobStore(str(tmp_path)).get(created.job_id)

    assert restored.job_id == created.job_id
    assert restored.analysis_job_id == "ana_test"
    assert restored.progress_total == 12


def test_recovery_job_survives_store_recreation(tmp_path):
    store = RecoveryJobStore(str(tmp_path))
    created = store.create("dna_test", "ana_test")

    restored = RecoveryJobStore(str(tmp_path)).get(created.job_id)

    assert restored.job_id == created.job_id
    assert restored.content_dna_job_id == "dna_test"
    assert restored.analysis_job_id == "ana_test"
