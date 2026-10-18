"""Reusable Firestore atomic CAS for a pre-staged, verified legacy audio result.

This is a *transaction primitive*, NOT an executable production repair tool.
The caller must ensure artifacts are independently generation-verified and
its durable journal binds those generations to the expected job and owner.
There is deliberately no Firestore client constructor and no command-line main.
"""
from __future__ import annotations
import hashlib,json
from datetime import datetime,timezone

class CommitRefused(RuntimeError):pass

def require(ok,message):
    if not ok:raise CommitRefused(message)

def _dt_future(value,now):
    if not isinstance(value,datetime):return False
    if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
    return value>now

def _sha(raw):return hashlib.sha256(raw).hexdigest()

def finalize_inline_transaction(db, *, queue_ref, session_ref, job_ref, journal_ref,
                                tenant: str, job_id: str, visual_id: str,
                                owner: str, generation: int, revision: int,
                                original_updated_at: str, candidate: dict,
                                verified_assets: dict) -> bool:
    """Atomic four-document CAS, inline-json-v1 only; fails closed.

    verified_assets must be {'mix':{sha256,generation,gcs_uri,size_bytes},
                             'delivery':{...}} already recorded in journal.
    Caller must hold and renew the recovery maintenance lease.
    """
    from google.cloud import firestore
    from app.models.audio_finishing import AudioFinishingJob
    require(tenant and job_id and visual_id and owner and generation>0,'missing identity')
    require(set(verified_assets)=={'mix','delivery'},'required assets missing')
    for kind, a in verified_assets.items():
        require(a.get('verified') is True and int(a.get('generation') or 0)>0 and
                isinstance(a.get('sha256'),str) and len(a['sha256'])==64 and
                str(a.get('gcs_uri','')).startswith('gs://reviveai/videos/runtime-artifacts/tenants/'+tenant+'/') and
                int(a.get('size_bytes') or 0)>0,'unverified '+kind)
    AudioFinishingJob.model_validate(candidate)
    require(candidate.get('job_id')==job_id and candidate.get('stage')=='COMPLETED','candidate state mismatch')
    result=candidate.get('result') or {}
    require(result.get('review_status')=='NEEDS_REVIEW' and result.get('reviewed_at') is None,'review must be pending')
    require((candidate.get('detail') or {}).get('source_visual_asset_id')==visual_id,'visual identity mismatch')
    cp=(candidate.get('detail') or {}).get('render_checkpoint') or {}
    require(cp.get('state')=='COMPLETED','checkpoint not finalized')
    for kind,field in [('mix','audio_mix'),('delivery','delivery_video')]:
        asset=result.get(field) or {}
        require(asset.get('gcs_uri')==verified_assets[kind]['gcs_uri'],'result asset URI mismatch '+kind)

    tx=db.transaction()
    @firestore.transactional
    def _commit(t):
        # All reads precede writes. Firestore retries a conflicting transaction.
        q=queue_ref.get(transaction=t).to_dict() or {}
        s=session_ref.get(transaction=t).to_dict() or {}
        j=job_ref.get(transaction=t).to_dict() or {}
        h=journal_ref.get(transaction=t).to_dict() or {}
        now=datetime.now(timezone.utc)
        maint=q.get('recovery_maintenance') or {}
        require(maint.get('owner')==owner and int(maint.get('generation') or 0)==generation and
                int(maint.get('expected_revision') or -1)==revision and
                maint.get('audio_job_id')==job_id and _dt_future(maint.get('expires_at'),now),'maintenance claim invalid')
        require(not _dt_future(q.get('lease_expires_at'),now),'supervisor worker lease active')
        require(q.get('status')=='RUNNING' and q.get('execution_owner')=='BACKEND' and
                int(q.get('revision') or -1)==revision,'supervisor queue changed')
        require(s.get('storage_mode')=='inline-json-v1' and j.get('storage_mode')=='inline-json-v1','unsupported record encoding')
        session=json.loads(s.get('payload_json') or '{}'); active=session.get('session') or {}
        require(int(session.get('revision') or -1)==revision and active.get('status')=='RUNNING' and
                active.get('executionOwner')=='BACKEND' and active.get('currentAudioJobId')==job_id and
                active.get('currentPublicationId') is None,'active Autopilot state changed')
        old=json.loads(j.get('payload_json') or '{}')
        require(old.get('job_id')==job_id and old.get('stage')=='RENDERING' and old.get('result') is None and
                old.get('updated_at')==original_updated_at and
                (old.get('detail') or {}).get('source_visual_asset_id')==visual_id and
                not (old.get('detail') or {}).get('render_checkpoint'),'legacy audio job changed')
        require(h.get('job_id')==job_id and h.get('owner')==owner and
                int(h.get('generation') or 0)==generation and h.get('state')=='STAGED_VERIFIED' and
                h.get('verified_assets')==verified_assets,'journal generation or assets changed')
        raw=json.dumps(candidate,ensure_ascii=False,separators=(',',':')).encode('utf-8')
        require(len(raw)<=700*1024,'candidate exceeds inline JSON boundary')
        # Preserve existing Firestore metadata, but record new size and hash.
        t.update(job_ref,{'payload_json':raw.decode('utf-8'), 'payload_size_bytes':len(raw),
                          'payload_sha256':_sha(raw),'persisted_at':now})
        t.update(journal_ref,{'state':'FINALIZED','finalized_at':now})
        return True
    return bool(_commit(tx))
