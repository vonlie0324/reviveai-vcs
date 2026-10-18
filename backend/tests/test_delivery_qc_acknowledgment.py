from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from app.models.delivery_qc import (DeliveryQcCheck, DeliveryQcCheckStatus, DeliveryQcOverallStatus,
                                    DeliveryQcReport)
from app.services import delivery_qc_service as svc


def report(status=DeliveryQcOverallStatus.REVIEW):
    return DeliveryQcReport(
        report_id="qc_1", audio_job_id="audio_1", assembly_job_id="assembly_1", audio_version=1,
        generated_at=datetime.now(timezone.utc), overall_status=status,
        ready_for_delivery=status != DeliveryQcOverallStatus.BLOCKED,
        warn_count=1 if status == DeliveryQcOverallStatus.REVIEW else 0,
        fail_count=1 if status == DeliveryQcOverallStatus.BLOCKED else 0,
        delivery_asset_id="master_1",
        checks=[DeliveryQcCheck(key="caption_alignment",category="Review",label="Caption warning",
                 status=DeliveryQcCheckStatus.WARN, summary="Review captions")],
    )


def test_review_requires_human_acknowledgment():
    assert not svc.qc_allows_manual_delivery(report())


def test_acknowledgment_is_tied_to_current_report_and_warning_set(monkeypatch):
    current=report()
    monkeypatch.setattr(svc.delivery_qc_store,"get",lambda _id:current.model_copy(deep=True))
    monkeypatch.setattr(svc.delivery_qc_store,"save",lambda updated:None)
    from app.services import audio_finishing_job_service as audio
    monkeypatch.setattr(audio.audio_finishing_job_store,"get",lambda _id:SimpleNamespace(version_number=1,result=SimpleNamespace(delivery_video=SimpleNamespace(asset_id="master_1"))))
    approved=svc.acknowledge_delivery_qc_warnings("audio_1","qc_1","user_1")
    assert svc.qc_allows_manual_delivery(approved)
    approved.checks[0].key="changed_warning"
    assert not svc.qc_allows_manual_delivery(approved)
    approved=approved.model_copy(deep=True)
    approved.report_id="qc_2"
    assert not svc.qc_allows_manual_delivery(approved)


def test_blocked_review_cannot_be_acknowledged(monkeypatch):
    blocked=report(DeliveryQcOverallStatus.BLOCKED)
    assert not svc.qc_allows_manual_delivery(blocked)
    monkeypatch.setattr(svc.delivery_qc_store,"get",lambda _id:blocked)
    from app.services import audio_finishing_job_service as audio
    monkeypatch.setattr(audio.audio_finishing_job_store,"get",lambda _id:SimpleNamespace(version_number=1,result=SimpleNamespace(delivery_video=SimpleNamespace(asset_id="master_1"))))
    with pytest.raises(svc.DeliveryQcError,match="Blocking"):
        svc.acknowledge_delivery_qc_warnings("audio_1","qc_1","user_1")


def test_stale_report_is_rejected(monkeypatch):
    monkeypatch.setattr(svc.delivery_qc_store,"get",lambda _id:report())
    with pytest.raises(svc.DeliveryQcError,match="no longer current"):
        svc.acknowledge_delivery_qc_warnings("audio_1","qc_old","user_1")
