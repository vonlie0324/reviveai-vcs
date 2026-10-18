"""V9G combined isolated flow: actual repository serializer + Firestore emulator + CloudStorageService-shaped fake.
STRICT: no ADC, real GCS, production application imports, or recovery commits.
"""
from __future__ import annotations
import hashlib, tempfile, uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from google.cloud import firestore
from test_legacy_audio_v9d_emulator import (ensure_isolated, PROJECT, DB, ROOT, JOB_ID, MODE_INLINE, MODE_CHUNKED, job_fixture, write_fixture, read_job, make_manifest, stage_candidate_chunks, guarded_finalize, Conflict, result_fixture)
from test_legacy_audio_v9f_offline import load_storage_class, FakeClient, BadNetwork
from legacy_audio_v9f_gcs_adapter import stage_create_only, StagingConflict


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def scenario(client, ns, mode):
    root=client.collection(ROOT).document(ns)
    jobref=root.collection('audio_finishing_jobs').document(JOB_ID)
    lock=root.collection('recovery_locks').document(JOB_ID)
    journal=root.collection('recovery_journals').document(JOB_ID)
    original=job_fixture(size=850000 if mode==MODE_CHUNKED else 12)
    write_fixture(jobref, original, mode)
    original_parent=jobref.get().to_dict()
    owner=uuid.uuid4().hex; gen=1; intent=uuid.uuid4().hex
    lock.create({'job_id':JOB_ID,'owner':owner,'generation':gen,'state':'ACTIVE','expires_at':datetime.now(timezone.utc)+timedelta(minutes=10)})
    with tempfile.TemporaryDirectory(prefix='v9g_') as td:
        d=Path(td); paths={'mix':d/'mix.m4a','delivery':d/'delivery.mp4'}
        paths['mix'].write_bytes(b'synthetic-mix-v9g');paths['delivery'].write_bytes(b'synthetic-delivery-v9g')
        hashes={k:digest(p) for k,p in paths.items()}
        keys={k:f'isolation/v9g/{ns}/{intent}/{k}' for k in paths}
        journal.create({'intent':intent,'owner':owner,'generation':gen,'state':'STAGING','hashes':hashes,'paths':keys,'job_id':JOB_ID})
        cloud=FakeClient(); storage=load_storage_class()('gs://fake-bucket/isolation',client=cloud)
        # Boundary A: after first successful upload, before journal update.
        assert stage_create_only(storage,paths['mix'],keys['mix'],hashes['mix'],content_type='audio/mp4')=='CREATED'
        assert journal.get().get('state')=='STAGING' and read_job(jobref)==original
        # Boundary B: network drop on second upload. No parent switch.
        cloud.fail_network=True
        try:stage_create_only(storage,paths['delivery'],keys['delivery'],hashes['delivery'],content_type='video/mp4')
        except BadNetwork:pass
        else:raise AssertionError('interrupted upload should fail')
        cloud.fail_network=False
        assert read_job(jobref)==original
        print(f'PASS: {mode} interruption before journal update and partial upload keep job unchanged')
        # Retry reuses first object by checking the actual bytes.
        assert stage_create_only(storage,paths['mix'],keys['mix'],hashes['mix'],content_type='audio/mp4')=='REUSED_VERIFIED'
        assert stage_create_only(storage,paths['delivery'],keys['delivery'],hashes['delivery'],content_type='video/mp4')=='CREATED'
        assert len(cloud.objects)==2
        journal.update({'state':'STAGED_VERIFIED','verified_at':datetime.now(timezone.utc)})
        print(f'PASS: {mode} retry reuses verified object and completes staging')
        candidate={**original,'stage':'COMPLETED','result':result_fixture(),'progress_current':5,'detail':{**original['detail'],'render_checkpoint':{'version':1,'state':'COMPLETED','recovery_intent':intent}}}
        manifest,chunks=make_manifest(candidate,mode)
        if chunks:stage_candidate_chunks(jobref,manifest,chunks)
        assert read_job(jobref)==original
        # No commit after remote object corruption.
        cloud.objects[keys['mix']]=b'corrupted'
        try:stage_create_only(storage,paths['mix'],keys['mix'],hashes['mix'],content_type='audio/mp4')
        except StagingConflict:pass
        else:raise AssertionError('remote tampering accepted')
        assert read_job(jobref)==original
        cloud.objects[keys['mix']]=paths['mix'].read_bytes()
        print(f'PASS: {mode} remote corruption blocks staging verification')
        # Lost lease aborts finalization.
        try:guarded_finalize(client,jobref,lock,owner='wrong',initial_parent=original_parent,new_manifest=manifest,expected_generation=gen)
        except Conflict:pass
        else:raise AssertionError('wrong-owner commit accepted')
        assert read_job(jobref)==original
        print(f'PASS: {mode} lost owner blocks job mutation')
        # Simulated crash after parent switch before journal reconciliation.
        guarded_finalize(client,jobref,lock,owner=owner,initial_parent=original_parent,new_manifest=manifest,expected_generation=gen)
        assert read_job(jobref)==candidate
        assert journal.get().get('state')=='STAGED_VERIFIED'
        print(f'PASS: {mode} committed parent and stale journal can be reconciled')
        # Retry verifies committed job and journal rather than switching again.
        assert read_job(jobref)['detail']['render_checkpoint']['recovery_intent']==intent
        journal.update({'state':'FINALIZED','completed_at':datetime.now(timezone.utc)})
        try:guarded_finalize(client,jobref,lock,owner=owner,initial_parent=original_parent,new_manifest=manifest,expected_generation=gen)
        except Conflict:pass
        else:raise AssertionError('duplicate accepted')
        assert len(cloud.objects)==2 and journal.get().get('state')=='FINALIZED'
        print(f'PASS: {mode} final journal reconciliation and duplicate rejection')
    return 6

def main():
    ensure_isolated()
    client=firestore.Client(project=PROJECT,database=DB)
    ns='v9g-'+uuid.uuid4().hex
    print('ISOLATED EMULATOR NAMESPACE:',ns)
    count=sum(scenario(client,ns+'-'+mode,mode) for mode in (MODE_INLINE,MODE_CHUNKED))
    print(f'ALL {count} V9G COMBINED EMULATOR CHECKS PASSED')
    print('FAKE GCS; LOOPBACK FIRESTORE EMULATOR; NO PRODUCTION COMMIT OR APPLICATION STARTUP')
if __name__=='__main__':main()
