"""Regression checks for server-authoritative Autopilot storage failures."""
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import pytest

from app.services.autopilot_state_service import (
    AutopilotSessionPayload, AutopilotStateConflictError,
    AutopilotStateRecord, AutopilotStateStore,
)


def fake_store(tmp_path, cloud):
    store = object.__new__(AutopilotStateStore)
    store._root = tmp_path
    store._lock = Lock()
    store._cloud = cloud
    store._sync_supervisor_queue_unlocked = lambda record: None
    return store


def record(revision=5, scope='PRODUCTION'):
    return AutopilotStateRecord(
        revision=revision,
        saved_at=datetime.now(timezone.utc),
        session=AutopilotSessionPayload(
            scope=scope, status='NEEDS_ATTENTION', executionOwner='BACKEND',
            currentProductionJobId='production_preserve',
            currentMediaJobId='media_preserve',
            updatedAt=datetime.now(timezone.utc).isoformat(),
        ),
    )


def test_firestore_transport_error_does_not_fallback_to_local(tmp_path):
    def raise_error(_):
        raise ConnectionError('simulated Firestore outage')
    store = fake_store(tmp_path, SimpleNamespace(load=raise_error))
    store._load_local_unlocked = lambda: record()
    with pytest.raises(ConnectionError, match='outage'):
        store.get()


def test_missing_firestore_with_existing_local_requires_manual_reconciliation(tmp_path):
    store = fake_store(tmp_path, SimpleNamespace(load=lambda _: None))
    store._load_local_unlocked = lambda: record()
    with pytest.raises(RuntimeError, match='manual reconciliation'):
        store.get()


def test_failed_cloud_commit_does_not_write_local(tmp_path):
    store = fake_store(tmp_path, SimpleNamespace())
    store._persist_cloud_unlocked = lambda _: (_ for _ in ()).throw(ConnectionError('write unavailable'))
    local_writes = []
    store._persist_local_unlocked = lambda value: local_writes.append(value)
    with pytest.raises(ConnectionError):
        store._persist_unlocked(record())
    assert local_writes == []


def test_generic_put_cannot_discard_production_lineage(tmp_path):
    store = fake_store(tmp_path, SimpleNamespace())
    current = record()
    store._load_unlocked = lambda: current
    store._persist_unlocked = lambda _: pytest.fail('should not persist a reset')
    incoming = AutopilotSessionPayload(
        scope='CAMPAIGN', status='IDLE', executionOwner='BACKEND',
        updatedAt=datetime.now(timezone.utc).isoformat(),
    )
    with pytest.raises(AutopilotStateConflictError):
        store.save(incoming, expected_revision=current.revision)
