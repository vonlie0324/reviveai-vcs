"""Consolidated REAL-RESULT emulator acceptance. NO production capability.

Uses V10B actual AudioFinishingResult and local media, stages fake GCS
with verified hashes, and atomically switches a synthetic job across four
Firestore documents. No application startup, network except loopback emulator.
"""
from __future__ import annotations
import argparse, hashlib, json, os, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ALLOWED_PROJECT='reviveai-local-test'
ALLOWED_HOSTS={'127.0.0.1:8085','localhost:8085'}
TYPES={'mix':('local-preview-mix.m4a','audio_mix'), 'delivery':('local-preview-delivery.mp4','delivery_video')}

class Rejected(RuntimeError): pass

def check(ok, message):
    if not ok: raise Rejected(message)

def sha256(data): return hashlib.sha256(data).hexdigest()

def isolated():
    check(os.getenv('FIRESTORE_EMULATOR_HOST') in ALLOWED_HOSTS, 'loopback emulator required')
    check(os.getenv('GOOGLE_CLOUD_PROJECT')==ALLOWED_PROJECT, 'test project required')
    check(not os.getenv('GOOGLE_APPLICATION_CREDENTIALS'), 'unset GOOGLE_APPLICATION_CREDENTIALS for isolated tests')

def validate_manifest(manifest, preview_dir):
    from app.models.audio_finishing import AudioFinishingResult
    check(manifest.get('status')=='RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','invalid V10B status')
    check(manifest.get('commit_enabled') is False,'commit flag must be false')
    result=AudioFinishingResult.model_validate(manifest['proposed_result'])
    check(result.review_status.value=='NEEDS_REVIEW' and result.reviewed_at is None,'review gate changed')
    check(result.effective_music_source.value=='REVIVEAI','music provider changed')
    check(result.effective_music_preset.value=='CINEMATIC_AMBIENT','music preset changed')
    check(result.subtitles is None,'unverified subtitle artifact attached')
    check(any('UNVERIFIED' in w for w in result.warnings),'caption warning missing')
    check(abs(result.total_duration_seconds-15)<0.01,'duration changed')
    check(result.assembly_job_id==manifest['assembly_job_id'] and result.production_brief_job_id==manifest['production_job_id'],'lineage changed')
    assets=manifest.get('proposed_artifacts') or []
    check(len(assets)==2,'two artifacts required')
    objects={}
    for kind,(filename,field) in TYPES.items():
        entry=next((a for a in assets if a.get('category')==kind), None)
        check(entry is not None,'missing artifact: '+kind)
        p=preview_dir/filename
        check(p.is_file(),'local artifact missing: '+str(p))
        contents=p.read_bytes(); digest=sha256(contents)
        check(digest==entry.get('sha256') and len(contents)==entry.get('size_bytes'),'artifact hash/size mismatch: '+kind)
        check(entry.get('upload_precondition')=='if_generation_match=0','create-only precondition missing')
        check(entry.get('remote_byte_hash_verification_required') is True,'remote verification absent')
        asset=getattr(result,field)
        check(asset is not None and asset.asset_id==entry.get('asset_id') and asset.gcs_uri==entry.get('gcs_uri'),'result asset reference mismatch')
        check(str(asset.gcs_uri).startswith('gs://reviveai/videos/runtime-artifacts/tenants/'),'unrecognized target uri')
        objects[kind]=(entry,contents)
    return result,objects

def guarded_switch(db,refs,*,owner,gen,revision,expected_job,expected_visual,candidate,hashes):
    from google.cloud import firestore
    queue,session,job,journal=refs
    tx=db.transaction()
    @firestore.transactional
    def do(t):
        q=queue.get(transaction=t).to_dict() or {}
        s=session.get(transaction=t).to_dict() or {}
        j=job.get(transaction=t).to_dict() or {}
        h=journal.get(transaction=t).to_dict() or {}
        now=datetime.now(timezone.utc)
        m=q.get('recovery_maintenance') or {}
        exp=m.get('expires_at')
        check(m.get('owner')==owner and m.get('generation')==gen and m.get('expected_revision')==revision and m.get('audio_job_id')==expected_job and isinstance(exp,datetime) and exp>now,'maintenance generation/expiry')
        lease=q.get('lease_expires_at')
        check(not (isinstance(lease,datetime) and lease>now),'supervisor lease not quiesced')
        check(q.get('revision')==revision and q.get('status')=='RUNNING' and q.get('execution_owner')=='BACKEND','queue state changed')
        check(s.get('storage_mode')=='inline-json-v1' and j.get('storage_mode')=='inline-json-v1','wrong storage mode')
        state=json.loads(s['payload_json']); active=state.get('session') or {}
        check(state.get('revision')==revision and active.get('status')=='RUNNING' and active.get('executionOwner')=='BACKEND' and active.get('currentAudioJobId')==expected_job and active.get('currentPublicationId') is None,'session changed')
        old=json.loads(j['payload_json'])
        check(old.get('job_id')==expected_job and old.get('stage')=='RENDERING' and old.get('result') is None,'audio job changed')
        check(not (old.get('detail') or {}).get('render_checkpoint') and (old.get('detail') or {}).get('source_visual_asset_id')==expected_visual,'checkpoint or visual changed')
        check(h.get('owner')==owner and h.get('generation')==gen and h.get('state')=='STAGED_VERIFIED' and h.get('job_id')==expected_job and h.get('verified_sha256')==hashes,'staging journal changed')
        check(candidate.get('job_id')==expected_job and candidate.get('stage')=='COMPLETED','candidate identity/stage')
        check((candidate.get('result') or {}).get('review_status')=='NEEDS_REVIEW' and (candidate.get('result') or {}).get('reviewed_at') is None,'review bypass')
        check((candidate.get('detail') or {}).get('source_visual_asset_id')==expected_visual,'candidate visual changed')
        check((candidate.get('detail') or {}).get('render_checkpoint',{}).get('state')=='COMPLETED','checkpoint not finalized')
        from app.models.audio_finishing import AudioFinishingJob
        AudioFinishingJob.model_validate(candidate)
        t.update(job,{'payload_json':json.dumps(candidate,ensure_ascii=False,separators=(',',':'))})
        t.update(journal,{'state':'FINALIZED','finalized_at':now})
        return True
    return do(tx)

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--preview-dir',type=Path,required=True)
    a=p.parse_args()
    isolated()   # MUST precede cloud imports
    manifest=json.loads(a.manifest.read_text(encoding='utf-8-sig'))
    result,objects=validate_manifest(manifest,a.preview_dir)
    from google.cloud import firestore
    from app.models.audio_finishing import AudioFinishingJob
    db=firestore.Client(project=ALLOWED_PROJECT,database='(default)')
    ns='final-'+uuid.uuid4().hex
    job_id='synthetic-'+uuid.uuid4().hex
    root=db.collection('reviveai_tenants').document(ns)
    queue=db.collection('reviveai_autopilot_supervisor').document(ns)
    session=root.collection('autopilot_state').document('active_session')
    job=root.collection('audio_finishing_jobs').document(job_id)
    journal=root.collection('synthetic_recovery_journals').document(job_id)
    refs=(queue,session,job,journal)
    now=datetime.now(timezone.utc); gen=3; revision=14; owner='isolated-recovery'
    visual='final_f9c1a20be9ca4526a42f4d112c9efb46'
    base={'job_id':job_id,'assembly_job_id':manifest['assembly_job_id'],'production_brief_job_id':manifest['production_job_id'],'media_job_id':result.media_job_id,'channel_id':'synthetic-channel','version_number':1,'stage':'RENDERING','message':'Synthetic mux pending','progress_current':4,'progress_total':5,'created_at':now.isoformat(),'updated_at':now.isoformat(),'detail':{'source_visual_asset_id':visual},'options':result.options.model_dump(mode='json'),'result':None,'error':None}
    AudioFinishingJob.model_validate(base)
    # Independent fake cloud: create-once immutable objects with post-stage digest verification.
    fake_gcs={}; hashes={}
    for kind,(entry,contents) in objects.items():
        key=entry['gcs_uri']; check(key not in fake_gcs,'duplicate fake key')
        fake_gcs[key]=contents
        check(sha256(fake_gcs[key])==entry['sha256'],'fake remote integrity')
        hashes[kind]=entry['sha256']
    q={'namespace':ns,'status':'RUNNING','revision':revision,'execution_owner':'BACKEND','lease_owner':'','lease_expires_at':now-timedelta(seconds=5),'recovery_maintenance':{'owner':owner,'audio_job_id':job_id,'generation':gen,'expected_revision':revision,'expires_at':now+timedelta(minutes=3)}}
    queue.set(q)
    state={'revision':revision,'session':{'status':'RUNNING','executionOwner':'BACKEND','currentAudioJobId':job_id,'currentPublicationId':None}}
    session.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(state)})
    job.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(base)})
    journal.set({'owner':owner,'generation':gen,'state':'STAGED_VERIFIED','job_id':job_id,'verified_sha256':hashes})
    candidate={**base,'stage':'COMPLETED','progress_current':5,'message':'Synthetic recovered mix; review pending','updated_at':now.isoformat(),'result':result.model_dump(mode='json'),'detail':{**base['detail'],'render_checkpoint':{'version':1,'state':'COMPLETED','recovery_generation':gen}}}
    kwargs=dict(owner=owner,gen=gen,revision=revision,expected_job=job_id,expected_visual=visual,candidate=candidate,hashes=hashes)
    def refusal(reason,action,undo):
        action()
        try:guarded_switch(db,refs,**kwargs)
        except Rejected:pass
        else:raise AssertionError('unsafe commit accepted: '+reason)
        undo()
        assert json.loads(job.get().get('payload_json'))==base,reason
    refusal('publication',lambda:session.update({'payload_json':json.dumps({'revision':revision,'session':{**state['session'],'currentPublicationId':'pub'}})}),lambda:session.update({'payload_json':json.dumps(state)}))
    refusal('revision',lambda:queue.update({'revision':revision+1}),lambda:queue.update({'revision':revision}))
    refusal('lease',lambda:queue.update({'lease_expires_at':now+timedelta(minutes=2)}),lambda:queue.update({'lease_expires_at':now-timedelta(seconds=5)}))
    refusal('staging',lambda:journal.update({'state':'STAGING'}),lambda:journal.update({'state':'STAGED_VERIFIED'}))
    refusal('owner',lambda:queue.update({'recovery_maintenance':{**q['recovery_maintenance'],'owner':'someone-else'}}),lambda:queue.update({'recovery_maintenance':q['recovery_maintenance']}))
    refusal('visual',lambda:job.update({'payload_json':json.dumps({**base,'detail':{'source_visual_asset_id':'tampered'}})}),lambda:job.update({'payload_json':json.dumps(base)}))
    guarded_switch(db,refs,**kwargs)
    readback=json.loads(job.get().get('payload_json'))
    AudioFinishingJob.model_validate(readback)
    assert readback['result']==result.model_dump(mode='json')
    assert journal.get().get('state')=='FINALIZED'
    try:guarded_switch(db,refs,**kwargs)
    except Rejected:pass
    else:raise AssertionError('duplicate completion was allowed')
    print('PASS: actual V10B Pydantic audio result validated and committed to synthetic emulator job')
    print('PASS: local media hashes, fake create-only GCS staging, verified journal')
    print('PASS: six conflict scenarios, atomic queue+session+job+journal, duplicate rejection')
    print('FINAL: ISOLATED_REAL_RESULT_EMULATOR_PASSED_COMMIT_DISABLED')
    print('NO PRODUCTION FIRESTORE/GCS; NO PROVIDERS; NO YOUTUBE; NO DEPLOYMENT')
if __name__=='__main__':
    main()
