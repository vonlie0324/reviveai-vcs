"""Offline production write-set review. NO CLOUD CONNECTIONS OR COMMIT PATH."""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
TENANT='61cf44d3ae8277b1f9d2aa781d87e52d'
JOB='audio_821f2a568f804076b10fa4364793385c'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
PREFIX=f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}/audio_finishing/{JOB}/assets/'

def load(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def digest(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for buf in iter(lambda:f.read(1024*1024),b''):h.update(buf)
    return h.hexdigest()
def assess(manifest,plan,records,preview, v14=None, snapshot=None, *, now=None):
    now=now or datetime.now(timezone.utc)
    checks=[]
    def ck(name,good,detail=''):
        checks.append({'name':name,'passed':bool(good),'detail':detail})
    ck('V10B validation',manifest.get('status')=='RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED' and manifest.get('commit_enabled') is False)
    ck('V11 plan',plan.get('status')=='READY_FOR_ISOLATED_INTEGRATION_NOT_PRODUCTION' and plan.get('production_writes_enabled') is False and plan.get('commit_available') is False)
    ck('audio identity',manifest.get('audio_job_id')==JOB and plan.get('job_id')==JOB and plan.get('production_id')==PROD and plan.get('assembly_job_id')==ASSEMBLY)
    a=records.get('assembly_job') or {}; b=records.get('production_brief_job') or {}
    ar=a.get('result') or {}; br=b.get('result') or {}
    ck('approved authoritative records',a.get('job_id')==ASSEMBLY and b.get('job_id')==PROD and a.get('stage')=='DELIVERED' and b.get('stage')=='COMPLETED' and ar.get('review_status')=='APPROVED' and br.get('review_status')=='APPROVED')
    ck('original publishing & visual',ar.get('publishing')==br.get('publishing') and ar.get('final_video',{}).get('asset_id')==VISUAL)
    proposed=manifest.get('proposed_result') or {}
    ck('QC and caption review gated',proposed.get('review_status')=='NEEDS_REVIEW' and proposed.get('reviewed_at') is None and proposed.get('subtitles') is None)
    ops=plan.get('operations') or []
    ck('two immutable assets',len(ops)==2 and {o.get('category') for o in ops}=={'mix','delivery'})
    writes=[]
    for op in ops:
        name=op.get('local_name') or ''
        # Reject path traversal and absolute paths, including Windows path separators.
        safe=bool(name) and Path(name).name==name and '/' not in name and '\\' not in name and name not in ('.','..')
        target=Path(preview)/name if safe else None
        intact=bool(safe and target.is_file() and target.stat().st_size==op.get('bytes') and digest(target)==op.get('sha256'))
        destination=op.get('destination') or ''
        allowed=destination.startswith(PREFIX) and destination.count('..')==0 and destination.endswith(('.m4a','.mp4'))
        ck('asset:'+str(op.get('category')),intact and allowed and op.get('precondition')=='if_generation_match=0' and op.get('verify_remote_bytes') is True and op.get('capture_generation') is True)
        writes.append({'operation':'CREATE_ONLY_GCS','category':op.get('category'),'destination':destination,'sha256':op.get('sha256'),'size_bytes':op.get('bytes'),'if_generation_match':0,'executed':False})
    writes += [
        {'operation':'READ_CHECK_THEN_CLAIM_MAINTENANCE','document':f'reviveai_autopilot_supervisor/{TENANT}','database':'reviveai-prod','executed':False},
        {'operation':'CREATE_OR_RECONCILE_JOURNAL','document':'UNRESOLVED—must be uniquely allocated, journal verified generations; no path assumed','database':'reviveai-prod','executed':False},
        {'operation':'ATOMIC_CAS','document':f'reviveai_tenants/{TENANT}/audio_finishing_jobs/{JOB}','database':'reviveai-prod','executed':False},
        {'operation':'READ_ONLY_POST_COMMIT_VERIFICATION','document':f'reviveai_tenants/{TENANT}/audio_finishing_jobs/{JOB}','database':'reviveai-prod','executed':False},
    ]
    if v14:
        job=v14.get('audio') or v14.get('audio_job') or {}
        ck('V14 record available',bool(job),'Report format must match inspected output')
        if job:
            ck('V14 original storage',job.get('storage_mode')=='inline-json-v1' and job.get('stage')=='RENDERING' and job.get('has_result') is False and job.get('checkpoint_state') is None and job.get('source_visual_asset_id')==VISUAL)
    if snapshot:
        try:
            date=datetime.fromisoformat(snapshot['captured_at'].replace('Z','+00:00'))
            age=(now-date).total_seconds()
            ck('API snapshot freshness',0<=age<=300,f'{age:.1f}s; historic snapshots must be refreshed')
            j=snapshot.get('audio_job') or {}; s=(snapshot.get('autopilot') or {}).get('session') or {}
            ck('API state at capture',j.get('job_id')==JOB and j.get('stage')=='RENDERING' and j.get('result') is None and s.get('currentAudioJobId')==JOB and s.get('currentPublicationId') is None)
        except (KeyError,ValueError,TypeError) as exc:ck('API snapshot parse',False,str(exc))
    # Never mark production-ready, even when all static checks pass: cloud generation, lease and journal are unproved.
    blockers=[c['name'] for c in checks if not c['passed']]
    blockers += ['No atomic production maintenance/deployment quiescence verification',
                 'No real GCS generation and restart reconciliation acceptance',
                 'No durable production journal orchestration and proven path',
                 'No commit-time authoritative Firestore reread or approval for writes',
                 'No production deployment rollback/canary acceptance',
                 'Audio listening, music rights and delivery QC still required']
    return {'status':'READINESS_REVIEW_ONLY_PRODUCTION_BLOCKED','commit_enabled':False,'deployment_allowed':False,'publish_allowed':False,
            'job_id':JOB,'tenant':TENANT,'checks':checks,'blockers':blockers,'proposed_write_set':writes,
            'notes':['No external API calls','No cloud client imports','No external writes','No production commit implementation']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for v in ['manifest','plan','records','preview-dir']:p.add_argument('--'+v,required=True,type=Path)
    p.add_argument('--v14',type=Path);p.add_argument('--snapshot',type=Path);p.add_argument('--out',type=Path)
    p.add_argument('--commit',action='store_true');p.add_argument('--deploy',action='store_true')
    args=p.parse_args()
    if args.commit or args.deploy:raise SystemExit('REFUSED: no production commit/deploy functionality')
    result=assess(load(args.manifest),load(args.plan),load(args.records),args.preview_dir,load(args.v14) if args.v14 else None,load(args.snapshot) if args.snapshot else None)
    out=args.out or (args.preview_dir/'final-production-readiness-review.json')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    for c in result['checks']:print(('PASS' if c['passed'] else 'BLOCKED')+': '+c['name'])
    print('STATUS:',result['status']);print('PLANNED WRITE-SET:',len(result['proposed_write_set']),'operations; zero executed');print('REPORT:',out)
    print('NO NETWORK; NO CLOUD CLIENTS; NO FIRESTORE/GCS WRITES; NO DEPLOYMENT; NO PUBLISH')
if __name__=='__main__':main()
