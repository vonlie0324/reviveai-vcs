"""V19: synthetic transaction gate. Strictly Firestore EMULATOR only.

Tests cross-document queue maintenance + live Autopilot session revision + inline
job CAS + staged journal. No provider, production GCS, app server, or publish calls.
"""
from __future__ import annotations
import json, os, uuid
from datetime import datetime, timedelta, timezone

PROJECT='reviveai-local-test'
HOSTS={'127.0.0.1:8085','localhost:8085'}

class Refused(RuntimeError): pass

def isolation():
    if os.environ.get('FIRESTORE_EMULATOR_HOST') not in HOSTS or os.environ.get('GOOGLE_CLOUD_PROJECT')!=PROJECT:
        raise SystemExit('REFUSED: emulator 127.0.0.1:8085 and reviveai-local-test required')

def commit_gate(db, *, queue, session, job, journal, owner, generation, revision, candidate):
    """Synthetic inline only: transaction reads all four authoritative documents."""
    from google.cloud import firestore
    tx=db.transaction()
    @firestore.transactional
    def atomic(t):
        q=queue.get(transaction=t).to_dict() or {}
        s=session.get(transaction=t).to_dict() or {}
        j=job.get(transaction=t).to_dict() or {}
        h=journal.get(transaction=t).to_dict() or {}
        now=datetime.now(timezone.utc)
        m=q.get('recovery_maintenance') or {}
        expiry=m.get('expires_at')
        if not (m.get('owner')==owner and m.get('generation')==generation and
                m.get('expected_revision')==revision and m.get('audio_job_id')=='synthetic-audio' and
                isinstance(expiry,datetime) and expiry>now):
            raise Refused('maintenance owner / generation / expiry')
        if (q.get('lease_owner') and isinstance(q.get('lease_expires_at'),datetime)
                and q['lease_expires_at']>now): raise Refused('supervisor active')
        if q.get('revision')!=revision or q.get('status')!='RUNNING':
            raise Refused('queue revision/status changed')
        if s.get('storage_mode')!='inline-json-v1': raise Refused('session serialization')
        state=json.loads(s['payload_json'])
        payload=state.get('session') or {}
        if (state.get('revision')!=revision or payload.get('status')!='RUNNING' or
            payload.get('executionOwner')!='BACKEND' or payload.get('currentAudioJobId')!='synthetic-audio' or
            payload.get('currentPublicationId') is not None):
            raise Refused('Autopilot session changed or publication exists')
        if j.get('storage_mode')!='inline-json-v1':raise Refused('audio storage mode')
        before=json.loads(j['payload_json'])
        if (before.get('job_id')!='synthetic-audio' or before.get('stage')!='RENDERING' or
            before.get('result') is not None or (before.get('detail') or {}).get('render_checkpoint')):
            raise Refused('audio job changed')
        if (h.get('owner')!=owner or h.get('generation')!=generation or
            h.get('state')!='STAGED_VERIFIED' or h.get('job_id')!='synthetic-audio' or
            h.get('verified_artifacts')!=['mix','delivery']):
            raise Refused('journal not verified')
        if (candidate.get('result') or {}).get('review_status')!='NEEDS_REVIEW' or candidate.get('stage')!='COMPLETED':
            raise Refused('review bypass')
        if (candidate.get('detail') or {}).get('source_visual_asset_id')!='visual-synthetic':
            raise Refused('visual lineage')
        if (candidate.get('result') or {}).get('effective_music_source')!='REVIVEAI':
            raise Refused('music provenance')
        replacement={**j, 'payload_json':json.dumps(candidate,sort_keys=True,separators=(',',':'))}
        t.set(job,replacement)
        t.update(journal,{'state':'FINALIZED','finalized_at':now})
        return True
    return atomic(tx)

def main():
    isolation()
    from google.cloud import firestore
    from app.services import autopilot_supervisor_queue as mod
    from unittest.mock import patch
    from types import SimpleNamespace
    db=firestore.Client(project=PROJECT,database='(default)')
    ns='v19-'+uuid.uuid4().hex
    queue=db.collection('reviveai_autopilot_supervisor').document(ns)
    session=db.collection('reviveai_tenants').document(ns).collection('autopilot_state').document('active_session')
    job=db.collection('reviveai_tenants').document(ns).collection('audio_finishing_jobs').document('synthetic-audio')
    journal=db.collection('reviveai_tenants').document(ns).collection('synthetic_v19_journal').document('synthetic-audio')
    now=datetime.now(timezone.utc)
    q={'namespace':ns,'status':'RUNNING','revision':20,'execution_owner':'BACKEND','lease_owner':'',
       'lease_expires_at':now-timedelta(seconds=5)}
    queue.set(q)
    state={'revision':20,'session':{'status':'RUNNING','executionOwner':'BACKEND','currentAudioJobId':'synthetic-audio','currentPublicationId':None}}
    session.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(state)})
    original={'job_id':'synthetic-audio','stage':'RENDERING','result':None,'detail':{'source_visual_asset_id':'visual-synthetic'},'progress_total':5}
    job.set({'storage_mode':'inline-json-v1','payload_json':json.dumps(original)})
    settings=SimpleNamespace(autopilot_auto_replenish_enabled=False,autopilot_event_driven_enabled=False,autopilot_autonomous_final_approval_enabled=False,autopilot_continuous_campaign_enabled=False)
    with patch.object(mod,'get_runtime_firestore_client',return_value=db),patch.object(mod,'get_settings',return_value=settings):
        api=mod.AutopilotSupervisorQueue()
        gen=api.acquire_recovery_maintenance(namespace=ns,audio_job_id='synthetic-audio',owner='repair',expected_revision=20)
        assert gen>0
        assert not api.acquire_lease(namespace=ns,owner='supervisor',lease_seconds=60)
        journal.set({'owner':'repair','generation':gen,'state':'STAGED_VERIFIED','job_id':'synthetic-audio','verified_artifacts':['mix','delivery']})
        candidate={**original,'stage':'COMPLETED','result':{'review_status':'NEEDS_REVIEW','effective_music_source':'REVIVEAI'},'detail':{'source_visual_asset_id':'visual-synthetic','render_checkpoint':{'state':'COMPLETED'}}}
        args=dict(queue=queue,session=session,job=job,journal=journal,owner='repair',generation=gen,revision=20,candidate=candidate)
        def expect_refusal(why,mutate,restore):
            mutate()
            try:commit_gate(db,**args)
            except Refused:pass
            else:raise AssertionError('unsafe commit allowed: '+why)
            restore()
            assert json.loads(job.get().get('payload_json'))==original
        expect_refusal('changed session',lambda:session.update({'payload_json':json.dumps({**state,'revision':21})}),lambda:session.update({'payload_json':json.dumps(state)}))
        expect_refusal('publication',lambda:session.update({'payload_json':json.dumps({'revision':20,'session':{**state['session'],'currentPublicationId':'publication-x'}})}),lambda:session.update({'payload_json':json.dumps(state)}))
        expect_refusal('unverified journal',lambda:journal.update({'state':'STAGING'}),lambda:journal.update({'state':'STAGED_VERIFIED'}))
        expect_refusal('queue revision',lambda:queue.update({'revision':21}),lambda:queue.update({'revision':20}))
        expect_refusal('active competing lease',lambda:queue.update({'lease_owner':'worker','lease_expires_at':now+timedelta(minutes=2)}),lambda:queue.update({'lease_owner':'','lease_expires_at':now-timedelta(seconds=5)}))
        expect_refusal('stale owner',lambda:args.update(owner='stale'),lambda:args.update(owner='repair'))
        expect_refusal('stale generation',lambda:args.update(generation=gen+1),lambda:args.update(generation=gen))
        commit_gate(db,**args)
        assert json.loads(job.get().get('payload_json'))==candidate
        assert journal.get().get('state')=='FINALIZED'
        try:commit_gate(db,**args)
        except Refused: pass
        else:raise AssertionError('duplicate commit permitted')
        assert api.release_recovery_maintenance(namespace=ns,owner='repair',generation=gen)
    print('PASS: queue+session+audio+journal transactional CAS; seven conflict scenarios; duplicate rejected')
    print('V19: SYNTHETIC_CROSS_DOCUMENT_EMULATOR_PASSED_COMMIT_DISABLED')
    print('NO PRODUCTION CLIENTS; NO GCS; NO PROVIDER; NO PUBLISH; NO DEPLOY')
if __name__=='__main__':main()
