"""Commit-disabled V10B authoritative export validation and V10 adapter bridge."""
from __future__ import annotations
import argparse, json, hashlib
from pathlib import Path
from legacy_audio_v9b_contracts import UnsafeRecovery
from legacy_audio_v10_adapter import build as build_v10

JOB='audio_821f2a568f804076b10fa4364793385c'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'

def validate_export(p: Path):
    payload=json.loads(p.read_text(encoding='utf-8-sig'))
    a=payload.get('assembly_job') or {}; b=payload.get('production_brief_job') or {}
    ar=a.get('result') or {};br=b.get('result') or {}
    def need(ok,msg):
        if not ok:raise UnsafeRecovery(msg)
    need(payload.get('audio_job_id')==JOB,'wrong audio job identity')
    need(a.get('job_id')==ASSEMBLY and b.get('job_id')==PROD,'wrong authoritative record ids')
    need(a.get('production_brief_job_id')==PROD,'assembly to production relation mismatch')
    need(a.get('media_job_id')==ar.get('media_job_id'),'assembly media relation mismatch')
    need(a.get('channel_id')==b.get('channel_id'),'channel relation mismatch')
    need(ar.get('review_status')=='APPROVED' and br.get('review_status')=='APPROVED','records not approved')
    need((ar.get('final_video') or {}).get('asset_id')==VISUAL,'visual master lineage mismatch')
    need(len(ar.get('timeline') or [])==4,'expected four shots')
    need([s.get('shot_number') for s in ar['timeline']]==[1,2,3,4],'shot sequence mismatch')
    need([s.get('output_duration_seconds') for s in ar['timeline']]==[3,3,4,5],'timing mismatch')
    need(float(ar.get('total_duration_seconds',0))==15,'duration mismatch')
    need(isinstance(ar.get('publishing'),dict) and ar['publishing']==br.get('publishing'),'publishing records have diverged')
    need(isinstance((br.get('publishing') or {}).get('audio_direction'),str),'audio direction missing')
    need(ar.get('captions_burned_in') is True,'approved visual captions not burned in')
    from app.models.final_assembly import FinalAssemblyJob
    from app.models.production_brief import ProductionBriefJob
    FinalAssemblyJob.model_validate(a)
    ProductionBriefJob.model_validate(b)
    return payload

def main():
    p=argparse.ArgumentParser(description='Offline V10B authoritative export audit; production commit unavailable')
    p.add_argument('--records',type=Path,required=True)
    p.add_argument('--preview-dir',type=Path)
    p.add_argument('--snapshot',type=Path)
    p.add_argument('--commit',action='store_true')
    args=p.parse_args()
    if args.commit:raise SystemExit('REFUSED: V10B has no production commit')
    try:
        data=validate_export(args.records)
        report={'version':'V10B_OFFLINE','status':'RECORDS_VALIDATED_COMMIT_DISABLED','records_sha256':hashlib.sha256(args.records.read_bytes()).hexdigest(),'audio_job_id':JOB,'assembly_job_id':ASSEMBLY,'production_job_id':PROD,'review_approved':True,'duration_seconds':15,'shot_durations':[3,3,4,5],'captions_burned_in':True,'narration_word_alignment_shots_2_3':'UNVERIFIED','soundtrack':'REVIVEAI_CINEMATIC_AMBIENT_APPROVED_FOR_QC','commit_enabled':False}
        if args.preview_dir or args.snapshot:
            if not (args.preview_dir and args.snapshot):raise UnsafeRecovery('--preview-dir and --snapshot must both be provided')
            # V10 accepts paths to the two exported job records, not a combined file.
            # Persist split records only locally in the specified preview directory.
            args.preview_dir.mkdir(parents=True,exist_ok=True)
            ap=args.preview_dir/'v10b-assembly-record.json';bp=args.preview_dir/'v10b-brief-record.json'
            ap.write_text(json.dumps(data['assembly_job'],indent=2,ensure_ascii=False),encoding='utf-8')
            bp.write_text(json.dumps(data['production_brief_job'],indent=2,ensure_ascii=False),encoding='utf-8')
            result=build_v10(args.preview_dir,args.snapshot,ap,bp)
            if result['status']!='SCHEMA_PREVIEW_ONLY' or result['proposed_result'] is None:raise UnsafeRecovery('V10 result construction blocked')
            from app.models.audio_finishing import AudioFinishingResult
            AudioFinishingResult.model_validate(result['proposed_result'])
            report['status']='RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED'
            report['proposed_result']=result['proposed_result']
            report['proposed_artifacts']=result['proposed_artifacts']
            report['snapshot_age_seconds']=result['snapshot_age_seconds']
        dest=(args.preview_dir if args.preview_dir else args.records.parent)/'v10b-result-audit.json'
        dest.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print('PASS: authoritative assembly, brief, publishing package and timeline validated')
        print('V10B:',report['status']);print('MANIFEST:',dest)
        print('NO CLOUD CLIENTS; NO CLOUD WRITES; NO PRODUCTION COMMIT')
    except Exception as exc:
        raise SystemExit(f'BLOCKED: {type(exc).__name__}: {exc}') from exc
if __name__=='__main__':main()
