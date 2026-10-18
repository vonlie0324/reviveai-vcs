"""Emulator-only queue side effect boundary tests for two workers + maintenance."""
import os, uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from types import SimpleNamespace

def main():
    if os.getenv('FIRESTORE_EMULATOR_HOST') not in ('127.0.0.1:8085','localhost:8085') or os.getenv('GOOGLE_CLOUD_PROJECT')!='reviveai-local-test':
        raise SystemExit('REFUSED: emulator-only project and host required')
    from google.cloud import firestore
    from app.services import autopilot_supervisor_queue as module
    db=firestore.Client(project='reviveai-local-test',database='(default)')
    ns='v17-'+uuid.uuid4().hex
    ref=db.collection('reviveai_autopilot_supervisor').document(ns)
    settings=SimpleNamespace(autopilot_auto_replenish_enabled=False,autopilot_event_driven_enabled=False,autopilot_autonomous_final_approval_enabled=False,autopilot_continuous_campaign_enabled=False)
    with patch.object(module,'get_runtime_firestore_client',return_value=db),patch.object(module,'get_settings',return_value=settings):
        q=module.AutopilotSupervisorQueue(); now=datetime.now(timezone.utc)
        ref.set({'namespace':ns,'status':'RUNNING','revision':9,'execution_owner':'BACKEND','lease_owner':'','lease_expires_at':now-timedelta(seconds=10),'next_run_at':now})
        assert not q.assert_supervisor_lease(namespace=ns,owner='worker-a')
        assert q.acquire_lease(namespace=ns,owner='worker-a',lease_seconds=30)
        assert q.assert_supervisor_lease(namespace=ns,owner='worker-a')
        assert not q.assert_supervisor_lease(namespace=ns,owner='worker-b')
        assert not q.acquire_lease(namespace=ns,owner='worker-b',lease_seconds=30)
        assert not q.acquire_recovery_maintenance(namespace=ns,audio_job_id='synthetic',owner='recovery',expected_revision=9)
        q.release_lease(namespace=ns,owner='worker-a')
        gen=q.acquire_recovery_maintenance(namespace=ns,audio_job_id='synthetic',owner='recovery',expected_revision=9)
        assert gen>0
        assert not q.assert_supervisor_lease(namespace=ns,owner='worker-a')
        assert not q.assert_supervisor_lease(namespace=ns,owner='worker-b')
        assert not q.acquire_lease(namespace=ns,owner='worker-b',lease_seconds=30)
        assert q.release_recovery_maintenance(namespace=ns,owner='recovery',generation=gen)
        assert q.acquire_lease(namespace=ns,owner='worker-b',lease_seconds=30)
        assert q.assert_supervisor_lease(namespace=ns,owner='worker-b')
        ref.set({'lease_expires_at':datetime.now(timezone.utc)-timedelta(seconds=1)},merge=True)
        assert not q.assert_supervisor_lease(namespace=ns,owner='worker-b')
    print('V17: EMULATOR SIDE-EFFECT BOUNDARY CHECKS PASSED (two workers + recovery)')
    print('NO PRODUCTION FIRESTORE; NO CLOUD RUN; NO PROVIDERS; NO GCS; NO DEPLOYMENT')
if __name__=='__main__':main()
