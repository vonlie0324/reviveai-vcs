from datetime import datetime, timezone
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.autopilot_state_service import (
    AutopilotSessionPayload, AutopilotStateRecord, AutopilotStateStore,
    AutopilotStateConflictError,
)
from app.services import autopilot_state_service as state_module
from app.services import recovery_job_service
from app.models.recovery import RecoveryJobStage


def prepared_store(monkeypatch, *, publishing_enabled=False):
    session = AutopilotSessionPayload(
        scope="CAMPAIGN", status="PAUSED", executionOwner="BACKEND",
        recoveryJobId="recovery_trial", programId="program_1", currentRecommendationId="older_idea",
        currentTitle="Existing campaign", completedRecommendationIds=["done_idea"],
        updatedAt=datetime.now(timezone.utc).isoformat(),
    )
    current = AutopilotStateRecord(revision=10, saved_at=datetime.now(timezone.utc), session=session)
    store = object.__new__(AutopilotStateStore)
    store._lock = Lock()
    records = {"active": current}
    archives = {}
    store._load_unlocked = lambda: records["active"]
    store._persist_unlocked = lambda record: records.__setitem__("active", record)
    store._archives = SimpleNamespace(save=lambda name, payload: archives.__setitem__(name, payload),
                                      load=lambda name: archives.get(name))
    monkeypatch.setattr(state_module, "get_settings", lambda: SimpleNamespace(autopilot_autonomous_publish_enabled=publishing_enabled))
    monkeypatch.setattr(recovery_job_service.recovery_job_store, "get", lambda _id: SimpleNamespace(
        stage=RecoveryJobStage.COMPLETED, result=SimpleNamespace(recommendations=[SimpleNamespace(recommendation_id="mars"), SimpleNamespace(recommendation_id="done_idea")])
    ))
    return store, records, archives


def test_trial_archives_paused_campaign_and_restores_it(monkeypatch):
    store, records, archives = prepared_store(monkeypatch)
    trial = store.start_single_trial(expected_revision=10, recommendation_id="mars", recovery_job_id="recovery_trial", title="First Bark on Mars")
    assert trial.revision == 11
    assert trial.session.scope == "PRODUCTION"
    assert trial.session.currentRecommendationId == "mars"
    assert trial.session.completedRecommendationIds == []
    assert len(archives) == 1
    assert next(iter(archives.values()))["session"]["currentTitle"] == "Existing campaign"
    records["active"].session.status = "PAUSED"
    restored = store.restore_trial_campaign(expected_revision=11)
    assert restored.revision == 12
    assert restored.session.scope == "CAMPAIGN"
    assert restored.session.status == "PAUSED"
    assert restored.session.currentRecommendationId == "older_idea"
    assert restored.session.completedRecommendationIds == ["done_idea"]


def test_trial_refuses_when_automatic_publishing_enabled(monkeypatch):
    store, records, archives = prepared_store(monkeypatch, publishing_enabled=True)
    with pytest.raises(ValueError, match="AUTOPILOT_AUTONOMOUS_PUBLISH_ENABLED"):
        store.start_single_trial(expected_revision=10, recommendation_id="mars", recovery_job_id="recovery_trial", title="Mars")
    assert records["active"].revision == 10
    assert not archives


def test_trial_rejects_stale_revision_and_completed_idea(monkeypatch):
    store, records, archives = prepared_store(monkeypatch)
    with pytest.raises(AutopilotStateConflictError):
        store.start_single_trial(expected_revision=9, recommendation_id="mars", recovery_job_id="recovery_trial", title="Mars")
    with pytest.raises(ValueError, match="already complete"):
        store.start_single_trial(expected_revision=10, recommendation_id="done_idea", recovery_job_id="recovery_trial", title="Done")
    assert records["active"].revision == 10
    assert not archives
