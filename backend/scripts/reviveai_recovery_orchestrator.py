"""Injected recovery orchestration; no cloud-client construction or executable production entrypoint.

A lease-owning caller supplies pre-authorized Firestore refs, bucket and attested
manifest. Fail closed on interruptions; retry reconciles immutable staging.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from reviveai_recovery_gcs_adapter import stage_verified
from reviveai_recovery_commit_gate import finalize_inline_transaction, CommitRefused

class RecoveryBlocked(RuntimeError): pass

def require(condition, detail):
    if not condition: raise RecoveryBlocked(detail)

def verify_ownership(queue_ref, *, owner, generation, revision, job_id):
    queue=queue_ref.get().to_dict() or {}
    m=queue.get('recovery_maintenance') or {}
    now=datetime.now(timezone.utc)
    expiry=m.get('expires_at')
    if isinstance(expiry,datetime) and expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
    require(m.get('owner')==owner and int(m.get('generation') or 0)==generation
            and m.get('audio_job_id')==job_id and int(m.get('expected_revision') or -1)==revision
            and isinstance(expiry,datetime) and expiry>now,'maintenance owner invalid or expired')
    return queue

def ensure_journal(db, *, queue_ref, journal_ref, owner, generation, revision, job_id, fingerprint):
    """Persist intent atomically before the first cloud upload. Resumes matching intent only."""
    from google.cloud import firestore
    tx=db.transaction()
    @firestore.transactional
    def claim(t):
        q=queue_ref.get(transaction=t).to_dict() or {}
        old=journal_ref.get(transaction=t).to_dict() or {}
        m=q.get('recovery_maintenance') or {}
        now=datetime.now(timezone.utc); expiry=m.get('expires_at')
        if isinstance(expiry,datetime) and expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
        require(m.get('owner')==owner and int(m.get('generation') or 0)==generation
                and int(m.get('expected_revision') or -1)==revision and m.get('audio_job_id')==job_id
                and isinstance(expiry,datetime) and expiry>now,'claim changed before intent')
        require(q.get('status')=='RUNNING' and q.get('execution_owner')=='BACKEND'
                and int(q.get('revision') or -1)==revision,'supervisor queue changed')
        if old:
            require(old.get('job_id')==job_id and old.get('fingerprint')==fingerprint,
                    'journal identity/fingerprint changed: refuse takeover')
            state=old.get('state')
            require(state in ('INTENT','STAGED_VERIFIED','FINALIZED'), 'unexpected journal state')
            require(state!='FINALIZED', 'finalized recovery cannot be taken over')
            old_gen=int(old.get('generation') or 0)
            if old.get('owner')==owner and old_gen==generation:
                return state
            # The queue maintenance claim is the sole authority. It is validated
            # in this transaction, and its generation must advance monotonically.
            # Never carry forward old generation's staged evidence: re-verify the
            # remote objects before journal STAGED_VERIFIED at the new generation.
            require(old_gen>0 and generation>old_gen,
                    'journal takeover requires newer maintenance generation')
            t.update(journal_ref, {
                'owner':owner,'generation':generation,'state':'INTENT',
                'verified_assets':{},'takeover_at':now,
                'previous_owner':old.get('owner'), 'previous_generation':old_gen,
            })
            return 'INTENT'
        t.create(journal_ref, {'job_id':job_id,'owner':owner,'generation':generation,
                               'fingerprint':fingerprint,'state':'INTENT','created_at':now})
        return 'INTENT'
    return claim(tx)

def record_staged(db, *, queue_ref, journal_ref, owner, generation, revision, job_id, fingerprint, assets):
    """Journal all generation-verified objects atomically, while ownership remains valid."""
    from google.cloud import firestore
    require(set(assets)=={'mix','delivery'} and all(a.get('verified') for a in assets.values()),'unverified assets')
    tx=db.transaction()
    @firestore.transactional
    def mark(t):
        q=queue_ref.get(transaction=t).to_dict() or {}
        j=journal_ref.get(transaction=t).to_dict() or {}
        m=q.get('recovery_maintenance') or {}; now=datetime.now(timezone.utc)
        expiry=m.get('expires_at')
        if isinstance(expiry,datetime) and expiry.tzinfo is None: expiry=expiry.replace(tzinfo=timezone.utc)
        require(m.get('owner')==owner and int(m.get('generation') or 0)==generation
                and int(m.get('expected_revision') or -1)==revision and m.get('audio_job_id')==job_id
                and isinstance(expiry,datetime) and expiry>now,'maintenance lost during staging')
        require(j.get('owner')==owner and j.get('generation')==generation
                and j.get('fingerprint')==fingerprint and j.get('job_id')==job_id,'journal changed')
        require(j.get('state') in ('INTENT','STAGED_VERIFIED'),'journal no longer stageable')
        if j.get('state')=='STAGED_VERIFIED':
            require(j.get('verified_assets')==assets,'staged objects changed on retry')
            return
        t.update(journal_ref,{'state':'STAGED_VERIFIED','verified_assets':assets,'staged_at':now})
    mark(tx)

def stage_and_finalize(db, bucket, *, refs, identity, manifest, preview_dir:Path, original_updated_at,
                       candidate, expected_visual, fingerprint, checkpoint=None):
    """Resume create-only uploads and atomic job switch. Caller must own/renew maintenance.

    No automatic maintenance acquisition/release, backend startup, supervisor resume,
    or publishing; these demand explicit coordinated operational control.
    """
    checkpoint = checkpoint or (lambda: None)
    checkpoint()
    queue_ref,session_ref,job_ref,journal_ref=refs
    tenant,job_id,owner,generation,revision=(identity[k] for k in ('tenant','job_id','owner','generation','revision'))
    require(bucket.name=='reviveai','unexpected bucket')
    verify_ownership(queue_ref,owner=owner,generation=generation,revision=revision,job_id=job_id)
    state=ensure_journal(db,queue_ref=queue_ref,journal_ref=journal_ref,owner=owner,
                         generation=generation,revision=revision,job_id=job_id,fingerprint=fingerprint)
    require(state!='FINALIZED','job already finalized; verify separately')
    expected={a['category']:a for a in manifest.get('proposed_artifacts',[])}
    require(set(expected)=={'mix','delivery'},'missing or extra assets')
    assets={}
    for kind, filename, mime in [('mix','local-preview-mix.m4a','audio/mp4'),('delivery','local-preview-delivery.mp4','video/mp4')]:
        # Short lease? Renew outside this operation. We fail closed before and after uploads.
        checkpoint()
        verify_ownership(queue_ref,owner=owner,generation=generation,revision=revision,job_id=job_id)
        entry=expected[kind]
        require(entry.get('upload_precondition')=='if_generation_match=0','unsafe upload precondition')
        uri=entry['gcs_uri']
        require(uri.startswith('gs://reviveai/videos/runtime-artifacts/tenants/'+tenant+'/audio_finishing/'+job_id+'/assets/'),
                'non-job staging destination')
        attestation=stage_verified(bucket,uri=uri,path=preview_dir/filename,
              expected_sha256=entry['sha256'],expected_size=entry['size_bytes'],
              prefix=f'videos/runtime-artifacts/tenants/{tenant}/audio_finishing/{job_id}/assets/',content_type=mime)
        checkpoint() # detect lost maintenance after slow external upload
        attestation.pop('status',None) # upload disposition is not a durable identity
        assets[kind]=attestation
    checkpoint()
    record_staged(db,queue_ref=queue_ref,journal_ref=journal_ref,owner=owner,generation=generation,
                  revision=revision,job_id=job_id,fingerprint=fingerprint,assets=assets)
    checkpoint()
    return finalize_inline_transaction(db,queue_ref=queue_ref,session_ref=session_ref,job_ref=job_ref,
          journal_ref=journal_ref,tenant=tenant,job_id=job_id,visual_id=expected_visual,
          owner=owner,generation=generation,revision=revision,original_updated_at=original_updated_at,
          candidate=candidate,verified_assets=assets)
