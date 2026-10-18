"""Actual injected staging + journal + extracted CAS; synthetic tenant, emulator + fake GCS only."""
from __future__ import annotations
import argparse, hashlib,json,os,uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path
from test_recovery_extracted_transaction_emulator import isolated,validate_manifest,EXPECTED_TENANT
from test_recovery_gcs_adapter_offline import Bucket
from reviveai_recovery_orchestrator import stage_and_finalize, RecoveryBlocked,ensure_journal

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--preview-dir',type=Path,required=True)
    args=p.parse_args()
    isolated() # before all cloud imports
    manifest=json.loads(args.manifest.read_text('utf-8-sig'))
    result, objects=validate_manifest(manifest,args.preview_dir)
    from google.cloud import firestore
    from app.models.audio_finishing import AudioFinishingJob
    db=firestore.Client(project='reviveai-local-test',database='(default)')
    ns='orchestrator-'+uuid.uuid4().hex; job_id='synthetic-'+uuid.uuid4().hex
    original_id=manifest['audio_job_id']
    # A synthetic job id means its GCS URI must be synthetic too. The injected
    # orchestrator refuses a manifest pointing to the real audio job.
    from copy import deepcopy
    synthetic=deepcopy(manifest)
    synthetic['proposed_artifacts']=deepcopy(manifest['proposed_artifacts'])
    candidate_result=result.model_dump(mode='json')
    for e in synthetic['proposed_artifacts']:
        old=e['gcs_uri']; e['gcs_uri']=old.replace('/audio_finishing/'+original_id+'/','/audio_finishing/'+job_id+'/')
        assert e['gcs_uri']!=old,'manifest identity not found'
        field='audio_mix' if e['category']=='mix' else 'delivery_video'
        candidate_result[field]['gcs_uri']=e['gcs_uri']
    from app.models.audio_finishing import AudioFinishingResult
    AudioFinishingResult.model_validate(candidate_result)
    queue=db.collection('reviveai_autopilot_supervisor').document(ns)
    root=db.collection('reviveai_tenants').document(ns)
    session=root.collection('autopilot_state').document('active_session')
    job=root.collection('audio_finishing_jobs').document(job_id)
    journal=root.collection('synthetic_recovery_journals').document(job_id)
    now=datetime.now(timezone.utc); rev=8; gen=2; owner='isolated-orchestrator'
    visual='final_f9c1a20be9ca4526a42f4d112c9efb46'
    base={'job_id':job_id,'assembly_job_id':manifest['assembly_job_id'],'production_brief_job_id':manifest['production_job_id'],
          'media_job_id':result.media_job_id,'channel_id':'synthetic-channel','version_number':1,
          'stage':'RENDERING','message':'Synthetic pending','progress_current':4,'progress_total':5,
          'created_at':now.isoformat(),'updated_at':now.isoformat(),'detail':{'source_visual_asset_id':visual},
          'options':result.options.model_dump(mode='json'),'result':None,'error':None}
    AudioFinishingJob.model_validate(base)
    queue.set({'namespace':ns,'status':'RUNNING','execution_owner':'BACKEND','revision':rev,'lease_owner':'',
               'lease_expires_at':now-timedelta(seconds=1),
               'recovery_maintenance':{'owner':owner,'generation':gen,'audio_job_id':job_id,
                                        'expected_revision':rev,'expires_at':now+timedelta(minutes=10)}})
    session.set({'storage_mode':'inline-json-v1','payload_json':json.dumps({'revision':rev,'session':{
              'status':'RUNNING','executionOwner':'BACKEND','currentAudioJobId':job_id,'currentPublicationId':None}})})
    job.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(base)})
    candidate={**base,'stage':'COMPLETED','result':candidate_result,'progress_current':5,
               'message':'Synthetic recovered; audio review pending',
               'detail':{**base['detail'],'render_checkpoint':{'version':1,'state':'COMPLETED','recovery_generation':gen}}}
    identity={'tenant':EXPECTED_TENANT,'job_id':job_id,'owner':owner,'generation':gen,'revision':rev}
    fp=hashlib.sha256(json.dumps(synthetic,sort_keys=True).encode()).hexdigest()
    bucket=Bucket()
    kwargs=dict(refs=(queue,session,job,journal),identity=identity,manifest=synthetic,
                preview_dir=args.preview_dir,original_updated_at=base['updated_at'],
                candidate=candidate,expected_visual=visual,fingerprint=fp)
    # Simulate crash after journal intent and first upload, before journal staged.
    ensure_journal(db,queue_ref=queue,journal_ref=journal,owner=owner,
                   generation=gen,revision=rev,job_id=job_id,fingerprint=fp)
    from reviveai_recovery_gcs_adapter import stage_verified
    first=synthetic['proposed_artifacts'][0]
    filename='local-preview-mix.m4a' if first['category']=='mix' else 'local-preview-delivery.mp4'
    stage_verified(bucket,uri=first['gcs_uri'],path=args.preview_dir/filename,
                   expected_sha256=first['sha256'],expected_size=first['size_bytes'],
                   prefix=f'videos/runtime-artifacts/tenants/{EXPECTED_TENANT}/audio_finishing/{job_id}/assets/',
                   content_type='audio/mp4' if first['category']=='mix' else 'video/mp4')
    assert journal.get().get('state')=='INTENT'
    assert stage_and_finalize(db,bucket,**kwargs)
    assert journal.get().get('state')=='FINALIZED'
    finalized=json.loads(job.get().get('payload_json'))
    assert finalized['result']==candidate_result
    AudioFinishingJob.model_validate(finalized)
    try:stage_and_finalize(db,bucket,**kwargs)
    except RecoveryBlocked:pass
    else:raise AssertionError('replay accepted finalized journal')
    # Stale lease after expiry must fail before cloud stage.
    queue.update({'recovery_maintenance':{**queue.get().get('recovery_maintenance'), 'owner':'new-worker'}})
    try:stage_and_finalize(db,bucket,**kwargs)
    except RecoveryBlocked:pass
    else:raise AssertionError('stale owner accepted')
    print('PASS: real result + create-only GCS reconcile after interrupted upload')
    print('PASS: durable INTENT -> STAGED_VERIFIED -> FINALIZED, replay and stale owner rejected')
    print('FINAL: ISOLATED_ORCHESTRATOR_EMULATOR_PASSED_COMMIT_DISABLED')
    print('NO PRODUCTION CLIENTS; NO PROVIDERS; NO YOUTUBE; NO DEPLOYMENT')
if __name__=='__main__':main()
