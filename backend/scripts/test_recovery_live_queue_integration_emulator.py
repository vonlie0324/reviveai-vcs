"""Synthetic queue + lifecycle + real-result orchestrator acceptance. Emulator only.
No direct production entry point. Requires previously validated V10B manifest.
"""
import argparse, hashlib, json, os, uuid
from pathlib import Path
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from unittest.mock import patch
from types import SimpleNamespace

def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',required=True,type=Path);p.add_argument('--preview-dir',required=True,type=Path);args=p.parse_args()
    if (os.environ.get('FIRESTORE_EMULATOR_HOST') not in ('127.0.0.1:8085','localhost:8085')
        or os.environ.get('GOOGLE_CLOUD_PROJECT') != 'reviveai-local-test'
        or os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')):
        raise SystemExit('REFUSED: local emulator only; unset GOOGLE_APPLICATION_CREDENTIALS')
    from test_recovery_extracted_transaction_emulator import validate_manifest,EXPECTED_TENANT
    from test_recovery_gcs_adapter_offline import Bucket
    from reviveai_recovery_maintenance_lifecycle import run_staged_recovery, MaintenanceLost
    from app.services import autopilot_supervisor_queue as qmod
    from app.models.audio_finishing import AudioFinishingJob,AudioFinishingResult
    from google.cloud import firestore
    db=firestore.Client(project='reviveai-local-test',database='(default)')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8-sig'))
    result, _=validate_manifest(manifest,args.preview_dir)
    ns='integrated-'+uuid.uuid4().hex; jid='synthetic-'+uuid.uuid4().hex
    original=manifest['audio_job_id']; work=deepcopy(manifest)
    new_result=result.model_dump(mode='json')
    for a in work['proposed_artifacts']:
        uri=a['gcs_uri']; a['gcs_uri']=uri.replace('/audio_finishing/'+original+'/', '/audio_finishing/'+jid+'/')
        assert a['gcs_uri']!=uri
        key='audio_mix' if a['category']=='mix' else 'delivery_video'
        new_result[key]['gcs_uri']=a['gcs_uri']
    AudioFinishingResult.model_validate(new_result)
    root=db.collection('reviveai_tenants').document(ns)
    qref=db.collection('reviveai_autopilot_supervisor').document(ns)
    sref=root.collection('autopilot_state').document('active_session')
    jref=root.collection('audio_finishing_jobs').document(jid)
    journal=root.collection('synthetic_recovery_journals').document(jid)
    now=datetime.now(timezone.utc); rev=91; owner='recovery-isolated'
    visual='final_f9c1a20be9ca4526a42f4d112c9efb46'
    base={'job_id':jid,'assembly_job_id':manifest['assembly_job_id'],'production_brief_job_id':manifest['production_job_id'],
      'media_job_id':result.media_job_id,'channel_id':'synthetic-channel','version_number':1,'stage':'RENDERING',
      'message':'synthetic pending','progress_current':4,'progress_total':5,
      'created_at':now.isoformat(),'updated_at':now.isoformat(),'detail':{'source_visual_asset_id':visual},
      'options':result.options.model_dump(mode='json'),'result':None,'error':None}
    AudioFinishingJob.model_validate(base)
    candidate={**base,'stage':'COMPLETED','result':new_result,'progress_current':5,
      'message':'synthetic recovered; review required','detail':{'source_visual_asset_id':visual,
      'render_checkpoint':{'version':1,'state':'COMPLETED','recovery_generation':1}}}
    qref.set({'namespace':ns,'status':'RUNNING','execution_owner':'BACKEND','revision':rev,'lease_owner':'',
      'lease_expires_at':now-timedelta(seconds=30),'next_run_at':now-timedelta(seconds=1)})
    sref.set({'storage_mode':'inline-json-v1','payload_json':json.dumps({'revision':rev,'session':{
      'status':'RUNNING','executionOwner':'BACKEND','currentAudioJobId':jid,'currentPublicationId':None}})})
    jref.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(base)})
    settings=SimpleNamespace(autopilot_auto_replenish_enabled=False,autopilot_event_driven_enabled=False,
      autopilot_autonomous_final_approval_enabled=False,autopilot_continuous_campaign_enabled=False)
    fp=hashlib.sha256(json.dumps(work,sort_keys=True).encode()).hexdigest()
    kwargs={'refs':(qref,sref,jref,journal),'identity':{'tenant':EXPECTED_TENANT,'job_id':jid,
      'owner':owner,'revision':rev},'manifest':work,'preview_dir':args.preview_dir,
      'original_updated_at':base['updated_at'],'candidate':candidate,
      'expected_visual':visual,'fingerprint':fp}
    with patch.object(qmod,'get_runtime_firestore_client',return_value=db),patch.object(qmod,'get_settings',return_value=settings):
        queue=qmod.AutopilotSupervisorQueue()
        assert queue.acquire_lease(namespace=ns,owner='worker-1',lease_seconds=30)
        assert queue.acquire_recovery_maintenance(namespace=ns,audio_job_id=jid,owner=owner,expected_revision=rev)==0
        queue.release_lease(namespace=ns,owner='worker-1')
        def competing(claim, checkpoint):
            assert not queue.acquire_lease(namespace=ns,owner='worker-1',lease_seconds=30)
            assert not queue.acquire_lease(namespace=ns,owner='worker-2',lease_seconds=30)
            assert not queue.renew_lease(namespace=ns,owner='worker-1',lease_seconds=30)
            assert queue.acquire_recovery_maintenance(namespace=ns,audio_job_id=jid,owner='other-recovery',expected_revision=rev)==0
            checkpoint()
            from reviveai_recovery_orchestrator import stage_and_finalize
            identity=dict(kwargs['identity']);identity['generation']=claim.generation
            updated=dict(candidate);updated['detail']={**candidate['detail'],'render_checkpoint':{
               **candidate['detail']['render_checkpoint'],'recovery_generation':claim.generation}}
            return stage_and_finalize(db,Bucket(),**{**kwargs,'identity':identity,'candidate':updated,'checkpoint':checkpoint})
        from reviveai_recovery_maintenance_lifecycle import run_with_maintenance
        assert run_with_maintenance(queue,namespace=ns,audio_job_id=jid,owner=owner,expected_revision=rev,
             operation=competing,heartbeat_seconds=1,lease_seconds=60)
        final=json.loads(jref.get().get('payload_json'))
        AudioFinishingJob.model_validate(final)
        assert final['stage']=='COMPLETED' and final['result']==new_result
        assert journal.get().get('state')=='FINALIZED'
        assert (
            (qref.get().to_dict() or {})
            .get("recovery_maintenance", {})
            .get("owner")
            is None
        )
        print('PASS: real queue guards two workers while lease-owned real-result recovery finalizes')
        print('PASS: atomic journal + session + queue + job, then generation-fenced maintenance release')
    print('INTEGRATED: SYNTHETIC_LIVE_QUEUE_EMULATOR_PASSED_COMMIT_DISABLED')
    print('NO PRODUCTION FIRESTORE/GCS; NO PROVIDERS; NO YOUTUBE; NO DEPLOYMENT')
if __name__=='__main__':main()
