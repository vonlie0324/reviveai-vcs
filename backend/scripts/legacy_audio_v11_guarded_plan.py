"""V11 commit-disabled recovery gate and deterministic operation plan.
No cloud SDK, no production mutation, no subprocess/network. This is NOT a deployable commit adapter.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

JOB='audio_821f2a568f804076b10fa4364793385c'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
PREFIX=f'gs://reviveai/videos/runtime-artifacts/tenants/61cf44d3ae8277b1f9d2aa781d87e52d/audio_finishing/{JOB}/assets/'
EXPECTED={'mix':'local-preview-mix.m4a','delivery':'local-preview-delivery.mp4'}
class Blocked(ValueError):pass

def require(ok, why):
    if not ok:raise Blocked(why)

def file_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def validate(manifest, preview, *, now=None, max_age_seconds=300):
    require(manifest.get('status')=='RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','V10B manifest not validated')
    require(manifest.get('commit_enabled') is False,'manifest unexpectedly enables commit')
    require(manifest.get('audio_job_id')==JOB and manifest.get('assembly_job_id')==ASSEMBLY and manifest.get('production_job_id')==PROD,'recovery identity mismatch')
    require(manifest.get('review_approved') is True,'unapproved authoritative records')
    require(manifest.get('narration_word_alignment_shots_2_3')=='UNVERIFIED','narration warning missing')
    result=manifest.get('proposed_result') or {}
    require(result.get('review_status')=='NEEDS_REVIEW' and result.get('reviewed_at') is None,'review must remain pending')
    require(result.get('selected_youtube_audio_library_track') is None and result.get('effective_music_source')=='REVIVEAI' and result.get('effective_music_preset')=='CINEMATIC_AMBIENT','soundtrack provenance mismatch')
    require(result.get('assembly_job_id')==ASSEMBLY and result.get('production_brief_job_id')==PROD,'result lineage mismatch')
    require(abs(float(result.get('total_duration_seconds',-1))-15)<0.01,'duration mismatch')
    require(bool(result.get('publishing')),'publishing metadata absent')
    require(result.get('subtitles') is None,'unverified subtitle artifact attached')
    require(any('UNVERIFIED' in str(x) for x in result.get('warnings',[])),'speech alignment warning absent')
    captured=manifest.get('snapshot_age_seconds')
    # V10B reports age at PREVIEW CREATION, not current time; rely on captured timestamp where available.
    require(isinstance(captured,(int,float)) and 0<=captured<=max_age_seconds,'original V10B snapshot was stale')
    artifacts=manifest.get('proposed_artifacts') or []
    require(len(artifacts)==2 and set(a.get('category') for a in artifacts)==set(EXPECTED),'exactly two expected artifacts required')
    operations=[]
    for category in ('mix','delivery'):
        a=next(x for x in artifacts if x.get('category')==category)
        local=preview/EXPECTED[category]
        require(local.is_file(),'missing local approved artifact: '+str(local))
        digest=file_sha(local)
        require(a.get('sha256')==digest and a.get('size_bytes')==local.stat().st_size,'local artifact changed: '+category)
        require(a.get('gcs_uri','').startswith(PREFIX) and a.get('gcs_uri','').endswith('/'+a.get('asset_id','')+('.m4a' if category=='mix' else '.mp4')),'destination path mismatch')
        require(a.get('upload_precondition')=='if_generation_match=0' and a.get('remote_byte_hash_verification_required') is True,'unsafe upload configuration')
        ref=result.get('audio_mix' if category=='mix' else 'delivery_video') or {}
        require(ref.get('asset_id')==a.get('asset_id') and ref.get('gcs_uri')==a.get('gcs_uri'),'result asset URI mismatch')
        operations.append({'category':category,'local_name':EXPECTED[category],'bytes':local.stat().st_size,'sha256':digest,'destination':a['gcs_uri'],'precondition':'if_generation_match=0','verify_remote_bytes':True,'capture_generation':True})
    return {'version':'V11_COMMIT_DISABLED','status':'READY_FOR_ISOLATED_INTEGRATION_NOT_PRODUCTION','production_writes_enabled':False,'commit_available':False,'job_id':JOB,'assembly_job_id':ASSEMBLY,'production_id':PROD,'operations':operations,'required_guards':['Re-read authoritative Firestore job+assembly+brief+Autopilot immediately before commit','Verify no active publication and supervisor lease ownership','Create durable intent journal with monotonically fenced generation','Stage both GCS assets create-only, verify full remote byte digest and generations','Stage serialized inline/chunked candidate without switching the parent','Atomic parent compare-and-set checks job state, snapshot version, lease generation, journal verified','Journal reconciliation after crash must be idempotent','Confirm asset route accessibility, NEEDS_REVIEW and follow-on listening/caption/rights QC'],'unresolved':['No real Firestore read/CAS and GCS writes wired in V11','No authoritative assembly and Autopilot commit-time transaction spanning stores','No production authorization'],'snapshot_freshness_note':'V10B creation-time snapshot is NOT sufficient to authorize a future commit'}

def main():
    p=argparse.ArgumentParser(description='Offline V11 integration planning; no commit ability')
    p.add_argument('--manifest',required=True,type=Path);p.add_argument('--preview-dir',required=True,type=Path)
    p.add_argument('--commit',action='store_true')
    args=p.parse_args()
    if args.commit:raise SystemExit('REFUSED: V11 cannot write to production')
    try:plan=validate(json.loads(args.manifest.read_text(encoding='utf-8-sig')),args.preview_dir)
    except (Blocked,ValueError,KeyError,OSError) as e:raise SystemExit('BLOCKED: '+str(e)) from e
    dest=args.preview_dir/'v11-integration-plan.json';dest.write_text(json.dumps(plan,indent=2),encoding='utf-8')
    print('V11:',plan['status']);print('PLAN:',dest)
    print('NO CLOUD CLIENTS; NO NETWORK; NO FIRESTORE/GCS WRITES; NO PRODUCTION COMMIT')
if __name__=='__main__':main()
