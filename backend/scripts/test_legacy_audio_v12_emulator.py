"""V12 isolated V10B-result integration proof, never production execution.
Requires V9D/V9F/V9G test scripts already installed in backend/scripts.
Only connects to FIRESTORE_EMULATOR_HOST 127.0.0.1:8085, synthetic project,
synthetic job doc, fake GCS. No production application startup or credentials.
"""
from __future__ import annotations
import argparse, json, hashlib, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.cloud import firestore
from test_legacy_audio_v9d_emulator import (
    ensure_isolated, PROJECT, DB, ROOT, JOB_ID, MODE_INLINE, MODE_CHUNKED,
    job_fixture, write_fixture, read_job, make_manifest, stage_candidate_chunks,
    guarded_finalize, Conflict,
)
from test_legacy_audio_v9f_offline import load_storage_class, FakeClient
from legacy_audio_v9f_gcs_adapter import stage_create_only, StagingConflict
from legacy_audio_v11_guarded_plan import validate as validate_v11


def require(flag, why):
    if not flag: raise AssertionError(why)


def run_one(client, namespace, mode, plan, source_result, preview):
    job_ref=client.collection(ROOT).document(namespace).collection('audio_finishing_jobs').document(JOB_ID)
    lock=client.collection(ROOT).document(namespace).collection('recovery_locks').document(JOB_ID)
    journal=client.collection(ROOT).document(namespace).collection('recovery_journals').document(JOB_ID)
    base=job_fixture(size=850000 if mode==MODE_CHUNKED else 20)
    base['assembly_job_id']=plan['assembly_job_id']
    base['production_brief_job_id']=plan['production_id']
    base['detail']['source_visual_asset_id']='final_f9c1a20be9ca4526a42f4d112c9efb46'
    write_fixture(job_ref, base, mode)
    initial=job_ref.get().to_dict()
    owner=uuid.uuid4().hex; generation=1; intent=uuid.uuid4().hex
    lock.create({'job_id':JOB_ID,'owner':owner,'generation':generation,'state':'ACTIVE',
                 'expires_at':datetime.now(timezone.utc)+timedelta(minutes=10)})
    journal.create({'intent':intent,'owner':owner,'generation':generation,
                    'state':'STAGING','job_id':JOB_ID,
                    'hashes':{op['category']:op['sha256'] for op in plan['operations']}})
    fake=FakeClient()
    storage=load_storage_class()('gs://fake-bucket/isolation',client=fake)
    paths={op['category']:preview/op['local_name'] for op in plan['operations']}
    keys={op['category']:f'isolation/v12/{namespace}/{intent}/{op["category"]}' for op in plan['operations']}
    specs={op['category']:op for op in plan['operations']}
    require(stage_create_only(storage,paths['mix'],keys['mix'],specs['mix']['sha256'],content_type='audio/mp4')=='CREATED','first staging failed')
    fake.fail_network=True
    try:stage_create_only(storage,paths['delivery'],keys['delivery'],specs['delivery']['sha256'],content_type='video/mp4')
    except Exception as exc:
        require(exc.__class__.__name__=='BadNetwork','unexpected upload error')
    else:raise AssertionError('network outage accepted')
    fake.fail_network=False
    require(read_job(job_ref)==base,'partial upload changed job')
    require(stage_create_only(storage,paths['mix'],keys['mix'],specs['mix']['sha256'],content_type='audio/mp4')=='REUSED_VERIFIED','retry did not verify mix')
    require(stage_create_only(storage,paths['delivery'],keys['delivery'],specs['delivery']['sha256'],content_type='video/mp4')=='CREATED','retry did not stage video')
    journal.update({'state':'STAGED_VERIFIED','verified_at':datetime.now(timezone.utc)})
    result=json.loads(json.dumps(source_result))
    require(result['review_status']=='NEEDS_REVIEW' and result.get('subtitles') is None,'QC bypass')
    candidate={**base,'stage':'COMPLETED','result':result,'progress_current':5,
               'detail':{**base['detail'],'render_checkpoint':{'version':1,'state':'COMPLETED',
                           'source':'V12_ISOLATED_EMULATOR_ONLY','recovery_intent':intent}}}
    serialized,chunks=make_manifest(candidate,mode)
    if chunks:stage_candidate_chunks(job_ref,serialized,chunks)
    require(read_job(job_ref)==base,'staged candidate became visible early')
    for bad_owner in ('wrong-owner',):
        try:guarded_finalize(client,job_ref,lock,owner=bad_owner,initial_parent=initial,
                             new_manifest=serialized,expected_generation=generation)
        except Conflict:pass
        else:raise AssertionError('stale worker finalized job')
    require(read_job(job_ref)==base,'stale owner mutated job')
    # Verify bytes again before CAS, including no bypass of precondition paths.
    for key in ('mix','delivery'):
        op=specs[key]
        stage_create_only(storage,paths[key],keys[key],op['sha256'],content_type='audio/mp4' if key=='mix' else 'video/mp4')
    guarded_finalize(client,job_ref,lock,owner=owner,initial_parent=initial,
                     new_manifest=serialized,expected_generation=generation)
    actual=read_job(job_ref)
    require(actual==candidate,'Firestore serializer roundtrip changed result')
    require(actual['detail']['source_visual_asset_id']==base['detail']['source_visual_asset_id'],'lost visual lineage')
    require(actual['result']['review_status']=='NEEDS_REVIEW','premature approval')
    require(journal.get().get('state')=='STAGED_VERIFIED','crash-reconcile scenario not preserved')
    journal.update({'state':'FINALIZED','completed_at':datetime.now(timezone.utc)})
    try:guarded_finalize(client,job_ref,lock,owner=owner,initial_parent=initial,
                         new_manifest=serialized,expected_generation=generation)
    except Conflict:pass
    else:raise AssertionError('duplicate commit not rejected')
    require(len(fake.objects)==2,'wrong fake object count')
    print(f'PASS: {mode} validated result, staged bytes, interruption, lease CAS, restart and retry rejection')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--preview-dir',type=Path,required=True)
    parser.add_argument('--commit',action='store_true')
    a=parser.parse_args()
    if a.commit:raise SystemExit('REFUSED: V12 is emulator-only; no production commit')
    ensure_isolated()  # BEFORE creating any cloud client
    manifest=json.loads(a.manifest.read_text(encoding='utf-8-sig'))
    plan=validate_v11(manifest,a.preview_dir)
    require(plan['production_writes_enabled'] is False and plan['commit_available'] is False,'production guard absent')
    result=manifest['proposed_result']
    # Schema validates the *actual* proposed result using app models only; no service startups.
    from app.models.audio_finishing import AudioFinishingResult
    AudioFinishingResult.model_validate(result)
    client=firestore.Client(project=PROJECT,database=DB)
    ns='v12-'+uuid.uuid4().hex
    print('EMULATOR PROJECT:',PROJECT,'DATABASE:',DB,'NAMESPACE:',ns)
    run_one(client,ns+'-inline',MODE_INLINE,plan,result,a.preview_dir)
    run_one(client,ns+'-chunked',MODE_CHUNKED,plan,result,a.preview_dir)
    print('V12: ISOLATED_RESULT_INTEGRATION_PASSED_COMMIT_DISABLED')
    print('NO PRODUCTION FIRESTORE/GCS; NO AUTOPILOT; NO YOUTUBE; NO DEPLOYMENT')

if __name__=='__main__':main()
