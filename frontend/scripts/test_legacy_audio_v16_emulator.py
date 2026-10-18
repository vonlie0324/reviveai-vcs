"""Synthetic Firestore emulator-only queue concurrency tests. NEVER run against production."""
from __future__ import annotations
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


def main():
    if os.environ.get('FIRESTORE_EMULATOR_HOST') not in ('127.0.0.1:8085', 'localhost:8085'):
        raise SystemExit('REFUSED: FIRESTORE_EMULATOR_HOST must be 127.0.0.1:8085')
    if os.environ.get('GOOGLE_CLOUD_PROJECT') != 'reviveai-local-test':
        raise SystemExit('REFUSED: GOOGLE_CLOUD_PROJECT must be reviveai-local-test')
    from google.cloud import firestore
    from app.services import autopilot_supervisor_queue as module
    from types import SimpleNamespace
    db = firestore.Client(project='reviveai-local-test', database='(default)')
    namespace = 'v16-' + uuid.uuid4().hex
    ref = db.collection('reviveai_autopilot_supervisor').document(namespace)
    settings = SimpleNamespace(autopilot_auto_replenish_enabled=False,
                               autopilot_event_driven_enabled=False,
                               autopilot_autonomous_final_approval_enabled=False,
                               autopilot_continuous_campaign_enabled=False)
    with patch.object(module, 'get_runtime_firestore_client', return_value=db), patch.object(module, 'get_settings', return_value=settings):
        queue = module.AutopilotSupervisorQueue()
        now = datetime.now(timezone.utc)
        ref.set({'namespace':namespace,'status':'RUNNING','revision':41,'execution_owner':'BACKEND',
                 'lease_owner':'', 'lease_expires_at':now-timedelta(minutes=1), 'next_run_at':now-timedelta(minutes=1)})
        assert queue.acquire_lease(namespace=namespace,owner='worker-a',lease_seconds=30)
        assert queue.acquire_recovery_maintenance(namespace=namespace,audio_job_id='synthetic-audio',owner='repair-a',expected_revision=41)==0
        assert queue.renew_lease(namespace=namespace,owner='worker-a',lease_seconds=30)
        queue.release_lease(namespace=namespace,owner='worker-a')
        generation=queue.acquire_recovery_maintenance(namespace=namespace,audio_job_id='synthetic-audio',owner='repair-a',expected_revision=41)
        assert generation == 1
        assert queue.get_due(namespace) is None
        assert not queue.acquire_lease(namespace=namespace,owner='worker-b',lease_seconds=30)
        assert not queue.renew_lease(namespace=namespace,owner='worker-a',lease_seconds=30)
        assert queue.acquire_recovery_maintenance(namespace=namespace,audio_job_id='synthetic-audio',owner='repair-b',expected_revision=41)==0
        assert not queue.release_recovery_maintenance(namespace=namespace,owner='repair-b',generation=generation)
        assert queue.renew_recovery_maintenance(namespace=namespace,owner='repair-a',generation=generation)
        assert not queue.renew_recovery_maintenance(namespace=namespace,owner='repair-a',generation=generation+1)
        assert queue.release_recovery_maintenance(namespace=namespace,owner='repair-a',generation=generation)
        assert queue.acquire_lease(namespace=namespace,owner='worker-b',lease_seconds=30)
        queue.release_lease(namespace=namespace,owner='worker-b')
        second=queue.acquire_recovery_maintenance(namespace=namespace,audio_job_id='synthetic-audio',owner='repair-b',expected_revision=41)
        assert second==generation+1
        assert not queue.release_recovery_maintenance(namespace=namespace,owner='repair-a',generation=generation)
        ref.set({'revision':42},merge=True)
        assert not queue.renew_recovery_maintenance(namespace=namespace,owner='repair-b',generation=second)
        assert queue.release_recovery_maintenance(namespace=namespace,owner='repair-b',generation=second)
        assert queue.acquire_recovery_maintenance(namespace=namespace,audio_job_id='synthetic-audio',owner='repair-c',expected_revision=41)==0
    print('V16: EMULATOR GUARD TESTS PASSED — synthetic queue only')
    print('NO PRODUCTION FIRESTORE; NO AUTOPILOT STARTUP; NO GCS; NO DEPLOYMENT')

if __name__=='__main__':main()
