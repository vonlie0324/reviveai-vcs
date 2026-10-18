"""Regression coverage for IDLE -> one-video Autopilot trial."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from app.services.autopilot_state_service import (
    AutopilotSessionPayload, AutopilotStateRecord, AutopilotStateStore,
    AutopilotStateConflictError,
)


class InMemoryRepo:
    def __init__(self):
        self.records = {}

    def save(self, key, value):
        self.records[key] = value

    def load(self, key):
        return self.records.get(key)


class TrialTests(unittest.TestCase):
    def setUp(self):
        self.store = object.__new__(AutopilotStateStore)
        self.store._lock = __import__('threading').Lock()
        self.store._archives = InMemoryRepo()
        self.saved = None
        self.store._load_unlocked = lambda: self.saved
        self.store._persist_unlocked = lambda record: setattr(self, 'saved', record)
        self.settings = patch('app.services.autopilot_state_service.get_settings', return_value=SimpleNamespace(autopilot_autonomous_publish_enabled=False))
        self.settings.start()
        self.addCleanup(self.settings.stop)
        recovery = SimpleNamespace(stage='COMPLETED', result=SimpleNamespace(recommendations=[SimpleNamespace(recommendation_id='idea-1')]))
        self.recovery = patch('app.services.recovery_job_service.recovery_job_store.get', return_value=recovery)
        self.recovery.start()
        self.addCleanup(self.recovery.stop)

    def state(self, status='IDLE', revision=1, recovery_id=None):
        self.saved = AutopilotStateRecord(revision=revision, saved_at=datetime.now(timezone.utc), session=AutopilotSessionPayload(
            scope='CAMPAIGN', status=status, recoveryJobId=recovery_id, updatedAt='2026-10-16T00:00:00Z'))

    def test_idle_session_uses_verified_recovery_and_can_restore(self):
        self.state()
        trial = self.store.start_single_trial(expected_revision=1, recommendation_id='idea-1', recovery_job_id='recovery-1', title='My video')
        self.assertEqual(trial.session.scope, 'PRODUCTION')
        self.assertEqual(trial.session.status, 'RUNNING')
        self.assertEqual(trial.session.recoveryJobId, 'recovery-1')
        self.assertEqual(trial.revision, 2)
        self.saved.session.status = 'COMPLETED'
        restored = self.store.restore_trial_campaign(expected_revision=2)
        self.assertEqual(restored.session.scope, 'CAMPAIGN')
        self.assertEqual(restored.session.status, 'IDLE')
        self.assertIsNone(restored.session.recoveryJobId)

    def test_running_session_is_rejected(self):
        self.state('RUNNING')
        with self.assertRaises(ValueError):
            self.store.start_single_trial(expected_revision=1, recommendation_id='idea-1', recovery_job_id='recovery-1', title='My video')

    def test_revision_conflict_prevents_start(self):
        self.state()
        with self.assertRaises(AutopilotStateConflictError):
            self.store.start_single_trial(expected_revision=2, recommendation_id='idea-1', recovery_job_id='recovery-1', title='My video')

    def test_unrelated_checkpoint_is_rejected(self):
        self.state('PAUSED', recovery_id='other-recovery')
        with self.assertRaises(ValueError):
            self.store.start_single_trial(expected_revision=1, recommendation_id='idea-1', recovery_job_id='recovery-1', title='My video')

    def test_automatic_publishing_is_rejected(self):
        self.state()
        with patch('app.services.autopilot_state_service.get_settings', return_value=SimpleNamespace(autopilot_autonomous_publish_enabled=True)):
            with self.assertRaises(ValueError):
                self.store.start_single_trial(expected_revision=1, recommendation_id='idea-1', recovery_job_id='recovery-1', title='My video')


if __name__ == '__main__':
    unittest.main()
