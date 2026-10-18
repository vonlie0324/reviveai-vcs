"""V9E isolated recovery journal and resumability tests. No production access.

Requires FIRESTORE_EMULATOR_HOST=127.0.0.1:8085. Uses fake GCS.
Tests synthetic jobs only, never launches FastAPI nor imports app.
"""
from __future__ import annotations
import hashlib, uuid
from datetime import datetime, timedelta, timezone
from google.cloud import firestore
from test_legacy_audio_v9d_emulator import (
    ensure_isolated, PROJECT, DB, ROOT, JOB_ID, MODE_INLINE, MODE_CHUNKED,
    job_fixture, write_fixture, read_job, make_manifest, stage_candidate_chunks,
    guarded_finalize, Conflict, result_fixture,
)

class FakeGCS:
    def __init__(self): self.objects={}; self.uploads=0
    def stage(self, key, data, sha, *, fail=False):
        if hashlib.sha256(data).hexdigest()!=sha: raise Conflict('incorrect local SHA-256')
        if key in self.objects:
            if self.objects[key]!=data: raise Conflict('existing object hash mismatch')
            return 'REUSED_VERIFIED'
        if fail: raise IOError('synthetic upload interruption')
        self.objects[key]=bytes(data); self.uploads+=1
        return 'CREATED'
    def verify(self, key, sha):
        return key in self.objects and hashlib.sha256(self.objects[key]).hexdigest()==sha

def run_scenario(client, namespace, mode):
    ref=client.collection(ROOT).document(namespace).collection('audio_finishing_jobs').document(JOB_ID)
    lock=client.collection(ROOT).document(namespace).collection('recovery_locks').document(JOB_ID)
    journal=client.collection(ROOT).document(namespace).collection('recovery_journals').document(JOB_ID)
    initial=job_fixture(size=850_000 if mode==MODE_CHUNKED else 10)
    write_fixture(ref, initial, mode)
    old_parent=ref.get().to_dict()
    owner=uuid.uuid4().hex; generation=1
    lock.create({'job_id':JOB_ID,'owner':owner,'generation':generation,
                 'expires_at':datetime.now(timezone.utc)+timedelta(minutes=10),'state':'ACTIVE'})
    intent=uuid.uuid4().hex
    keys={label:f'synthetic/{namespace}/{intent}/{label}' for label in ('mix.m4a','delivery.mp4')}
    contents={'mix.m4a':b'synthetic-audio-mix','delivery.mp4':b'synthetic-video'}
    hashes={k:hashlib.sha256(v).hexdigest() for k,v in contents.items()}
    journal.create({'intent':intent,'job_id':JOB_ID,'owner':owner,'generation':generation,
                    'state':'STAGING','keys':keys,'hashes':hashes,'created_at':datetime.now(timezone.utc)})
    gcs=FakeGCS()
    gcs.stage(keys['mix.m4a'],contents['mix.m4a'],hashes['mix.m4a'])
    try: gcs.stage(keys['delivery.mp4'],contents['delivery.mp4'],hashes['delivery.mp4'],fail=True)
    except IOError: pass
    else: raise AssertionError('expected simulated failure')
    assert read_job(ref)==initial and journal.get().get('state')=='STAGING'
    print('PASS:',mode,'partial GCS failure leaves authoritative job unchanged')
    assert gcs.stage(keys['mix.m4a'],contents['mix.m4a'],hashes['mix.m4a'])=='REUSED_VERIFIED'
    gcs.stage(keys['delivery.mp4'],contents['delivery.mp4'],hashes['delivery.mp4'])
    assert gcs.uploads==2 and all(gcs.verify(keys[k],hashes[k]) for k in keys)
    journal.update({'state':'STAGED_VERIFIED','verified_at':datetime.now(timezone.utc)})
    assert read_job(ref)==initial
    print('PASS:',mode,'retry reuses verified object; staging does not finalize job')
    candidate={**initial,'stage':'COMPLETED','result':result_fixture(),
               'progress_current':initial['progress_total'],
               'detail':{**initial['detail'],'render_checkpoint':{'version':1,'state':'COMPLETED','recovery_intent':intent}}}
    # Actual repository serializer, compatible with repository chunk contract.
    manifest,chunks=make_manifest(candidate,mode)
    if chunks: stage_candidate_chunks(ref,manifest,chunks)
    assert read_job(ref)==initial
    # Loss of ownership prevents commit (even with fully staged objects).
    try: guarded_finalize(client,ref,lock,owner='other',initial_parent=old_parent,new_manifest=manifest,expected_generation=generation)
    except Conflict: pass
    else: raise AssertionError('lost-owner commit accepted')
    assert read_job(ref)==initial
    print('PASS:',mode,'wrong owner cannot commit staged objects')
    # Transaction guard rechecks BOTH parent and lease. Journal marks completion only
    # after visible job commits; crash in between is detected during reconciliation.
    guarded_finalize(client,ref,lock,owner=owner,initial_parent=old_parent,new_manifest=manifest,expected_generation=generation)
    assert read_job(ref)['result']['review_status']=='NEEDS_REVIEW'
    assert journal.get().get('state')=='STAGED_VERIFIED'
    print('PASS:',mode,'crash after Firestore switch leaves reconcilable journal')
    journal.update({'state':'FINALIZED','completed_at':datetime.now(timezone.utc)})
    try: guarded_finalize(client,ref,lock,owner=owner,initial_parent=old_parent,new_manifest=manifest,expected_generation=generation)
    except Conflict: pass
    else: raise AssertionError('duplicate commit accepted')
    assert gcs.uploads==2 and journal.get().get('state')=='FINALIZED'
    print('PASS:',mode,'reconciled journal; duplicate finalize rejected without reupload')
    return 5

def main():
    ensure_isolated()
    client=firestore.Client(project=PROJECT,database=DB)
    namespace='v9e-'+uuid.uuid4().hex
    print('ISOLATED EMULATOR NAMESPACE:',namespace)
    count=0
    for mode in (MODE_INLINE,MODE_CHUNKED):count+=run_scenario(client,namespace+'-'+mode,mode)
    print(f'ALL {count} V9E EMULATOR SCENARIO CHECKS PASSED')
    print('FAKE GCS ONLY; NO PRODUCTION CLIENT; NO BACKEND IMPORTS; NO PUBLISHING')
if __name__=='__main__':main()
