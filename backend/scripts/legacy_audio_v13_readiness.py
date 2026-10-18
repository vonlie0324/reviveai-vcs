"""V13 read-only snapshot + write-set review. Never opens cloud clients or commits."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path

JOB='audio_821f2a568f804076b10fa4364793385c'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
TENANT='61cf44d3ae8277b1f9d2aa781d87e52d'
class Blocked(Exception): pass

def need(cond, message):
    if not cond: raise Blocked(message)

def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def analyze(manifest,plan,records,snapshot,preview,*,now=None):
    now=now or datetime.now(timezone.utc)
    need(manifest.get('status')=='RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','V10B status invalid')
    need(manifest.get('commit_enabled') is False,'V10B commit enabled')
    need(plan.get('status')=='READY_FOR_ISOLATED_INTEGRATION_NOT_PRODUCTION','V11 plan invalid')
    need(plan.get('production_writes_enabled') is False and plan.get('commit_available') is False,'V11 unsafe flags')
    need(manifest.get('audio_job_id')==JOB and plan.get('job_id')==JOB,'job mismatch')
    need(plan.get('assembly_job_id')==ASSEMBLY and plan.get('production_id')==PROD,'lineage mismatch')
    a=records.get('assembly_job') or {}; b=records.get('production_brief_job') or {}
    need(a.get('job_id')==ASSEMBLY and a.get('stage')=='DELIVERED','assembly changed')
    need(b.get('job_id')==PROD and b.get('stage')=='COMPLETED','brief changed')
    need((a.get('result') or {}).get('review_status')=='APPROVED','assembly not approved')
    need((b.get('result') or {}).get('review_status')=='APPROVED','brief not approved')
    need((a.get('result') or {}).get('final_video',{}).get('asset_id')==VISUAL,'visual mismatch')
    need((a.get('result') or {}).get('publishing')==(b.get('result') or {}).get('publishing'),'publishing mismatch')
    ts=datetime.fromisoformat(snapshot['captured_at'].replace('Z','+00:00'))
    need(ts.tzinfo is not None,'snapshot has no timezone')
    age=(now-ts).total_seconds()
    need(0<=age<=300,f'snapshot is not fresh ({age:.0f}s)')
    j=snapshot.get('audio_job') or {}; ap=snapshot.get('autopilot') or {}; session=ap.get('session') or {}
    need(j.get('job_id')==JOB and j.get('assembly_job_id')==ASSEMBLY and j.get('production_brief_job_id')==PROD,'live audio lineage differs')
    need(j.get('stage')=='RENDERING' and j.get('result') is None,'job already progressed; STOP')
    need(not (j.get('detail') or {}).get('render_checkpoint'),'job has checkpoint; STOP')
    need((j.get('detail') or {}).get('source_visual_asset_id')==VISUAL,'live visual changed')
    need(session.get('currentProductionJobId')==PROD and session.get('currentAudioJobId')==JOB,'Autopilot work moved')
    need(session.get('currentPublicationId') is None,'publication exists; STOP')
    need(manifest.get('proposed_result',{}).get('review_status')=='NEEDS_REVIEW','review must remain pending')
    need(manifest['proposed_result'].get('subtitles') is None,'unverified subtitles attached')
    operations=plan.get('operations') or []
    need({o.get('category') for o in operations}=={'mix','delivery'} and len(operations)==2,'unexpected object count')
    for o in operations:
        local=Path(preview)/o['local_name']
        need(local.is_file(),'missing local file '+str(local))
        need(local.stat().st_size==o['bytes'] and sha_file(local)==o['sha256'],'artifact hash mismatch '+str(local))
        need(o['precondition']=='if_generation_match=0' and o.get('verify_remote_bytes') and o.get('capture_generation'),'unsafe staging operation')
        need(o['destination'].startswith(f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}/audio_finishing/{JOB}/assets/'),'unexpected GCS target')
    # Paths below are PLANNED ONLY. Actual authoritative Firestore collection, database, doc storage mode
    # and lease/journal paths must be confirmed from a production read-only inspection before any commit.
    write_set=[{'type':'GCS_CREATE_ONLY','destination':o['destination'],'sha256':o['sha256'],'size_bytes':o['bytes'],'precondition':o['precondition']} for o in operations]
    write_set.append({'type':'FIRESTORE_CAS_UNRESOLVED','logical_target':f'audio finishing job {JOB}','note':'Resolve actual Firestore database, tenant collection, inline/chunked mode, version and supervisor lease before any write'})
    write_set.append({'type':'FIRESTORE_JOURNAL_UNRESOLVED','logical_target':f'recovery journal/lease for {JOB}','note':'Resolve actual collection and fencing generation under explicit production plan'})
    return {'version':'V13_READ_ONLY','status':'LIVE_SNAPSHOT_VALIDATED_PRODUCTION_COMMIT_BLOCKED',
            'production_writes_enabled':False,'commit_available':False,'snapshot_age_seconds':round(age,2),
            'snapshot_captured_at':snapshot['captured_at'],'job_id':JOB,'autopilot_revision':ap.get('revision'),
            'job_updated_at':j.get('updated_at'),'source_records_sha256':None,
            'planned_write_set':write_set,
            'blocking_requirements':['Production authoritative Firestore read: correct database and tenant/document path, storage mode, parent version/update_time, chunk layout',
              'Production supervisor coordination: verify current lease/generation and acquire exclusive recovery fencing without competing worker',
              'Commit-time revalidation of job, approved assembly, brief and linked publication against authoritative stores, not browser snapshot',
              'Real Cloud Storage generation-aware adapter and transactionally journaled reconciliation for interrupted staging',
              'Confirm asset URLs resolve through current audio asset route and preserve downstream review, caption, music rights and Delivery QC',
              'Separately obtain explicit authorization for exact production writes and deployment'],
            'deployment_allowed':False,'youtube_publish_allowed':False}

def main():
    p=argparse.ArgumentParser(description='V13 read-only readiness report; no cloud clients or writes')
    for x in ['manifest','plan','records','snapshot','preview-dir']: p.add_argument('--'+x,type=Path,required=True)
    p.add_argument('--commit',action='store_true')
    args=p.parse_args()
    if args.commit:raise SystemExit('REFUSED: V13 has no commit capability')
    try: report=analyze(load(args.manifest),load(args.plan),load(args.records),load(args.snapshot),args.preview_dir)
    except (Blocked,KeyError,ValueError,TypeError,OSError) as e:raise SystemExit('BLOCKED: '+str(e))
    path=args.preview_dir/'v13-readiness-report.json';path.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('V13:',report['status']);print('SNAPSHOT AGE SECONDS:',report['snapshot_age_seconds']);print('WRITE SET:',len(report['planned_write_set']),'planned entries, zero executed');print('REPORT:',path)
    print('NO CLOUD CLIENTS; NO NETWORK; NO PRODUCTION WRITES; NO DEPLOYMENT; NO YOUTUBE')
if __name__=='__main__':main()
