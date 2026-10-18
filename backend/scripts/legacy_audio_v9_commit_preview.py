"""V9 offline commit design. No imports of ReviveAI services, cloud SDKs or network clients."""
import argparse, hashlib, json
from pathlib import Path
from datetime import datetime, timezone

JOB='audio_821f2a568f804076b10fa4364793385c'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
ARTIFACTS={'local-preview-mix.m4a':('AUDIO_MIX','audio/mp4','mix'), 'local-preview-delivery.mp4':('FINAL_VIDEO','video/mp4','delivery')}

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def verify_preview(preview):
    report=json.loads((preview/'recovery-report.json').read_text(encoding='utf-8'))
    errors=[]
    if report.get('job_id')!=JOB or report.get('source_visual_asset_id')!=VISUAL or report.get('mode')!='LOCAL_DRY_RUN_NO_CLOUD_WRITES': errors.append('report identity or mode mismatch')
    if report.get('music',{}).get('preset')!='CINEMATIC_AMBIENT':errors.append('wrong music preset')
    for filename,(kind,mime,prefix) in ARTIFACTS.items():
        item=report.get(filename) or {}
        file=preview/filename
        if not file.is_file() or digest(file)!=item.get('sha256') or file.stat().st_size!=item.get('size_bytes'):
            errors.append(f'hash/size mismatch {filename}')
        if abs(float(item.get('duration',0))-15)>0.35:errors.append(f'duration mismatch {filename}')
    return report,errors

def build(preview,snapshot=None):
    report,issues=verify_preview(preview)
    live=None
    if snapshot:
        source=json.loads(Path(snapshot).read_text(encoding='utf-8'))
        live=source.get('audio_job') or {}
        session=(source.get('autopilot') or {}).get('session') or {}
        if live.get('job_id')!=JOB or live.get('stage')!='RENDERING' or live.get('result') is not None:issues.append('live job is not stalled expected job')
        if (live.get('detail') or {}).get('render_checkpoint'):issues.append('live job already has checkpoint')
        if (live.get('detail') or {}).get('source_visual_asset_id')!=VISUAL:issues.append('visual lineage mismatch')
        if session.get('currentProductionJobId')!=PROD or session.get('currentAudioJobId')!=JOB or session.get('currentPublicationId'):issues.append('autopilot identity or publication mismatch')
        try:
            ts=datetime.fromisoformat(source['captured_at'].replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-ts).total_seconds()
            if age<0 or age>300:issues.append('snapshot expired or from future')
        except (KeyError,ValueError,TypeError):issues.append('snapshot timestamp invalid')
    else:issues.append('fresh live snapshot not provided')
    base=f'gs://reviveai/videos/runtime-artifacts/tenants/<TENANT>/audio_finishing/{JOB}/assets/'
    assets=[]
    for name,(kind,mime,prefix) in ARTIFACTS.items():
        sha=report.get(name,{}).get('sha256','')
        assets.append({'source_local_file':str(preview/name),'sha256':sha,'size_bytes':report.get(name,{}).get('size_bytes'),'asset_kind':kind,'mime_type':mime,'proposed_asset_id':f'{prefix}_recovered_{sha[:20]}','proposed_gcs_uri_template':base+f'{prefix}_recovered_{sha[:20]}'+('.m4a' if prefix=='mix' else '.mp4'),'gcs_precondition':'if_generation_match=0','upload_enabled':False})
    # Proposed fields are intentionally non-executable and incomplete until assembly publishing package is available.
    result={'review_status':'NEEDS_REVIEW','reviewed_at':None,'effective_music_source':'REVIVEAI','effective_music_preset':'CINEMATIC_AMBIENT','selected_youtube_audio_library_track':None,'selected_trending_track':None,'audio_mix':assets[0]['proposed_asset_id'],'delivery_video':assets[1]['proposed_asset_id'],'subtitles':None,'warnings':['Shot 2 and 3 word alignment UNVERIFIED; do not describe subtitles as speech verified','Replacement generated soundtrack approved for QC and potential publication; QC still required'],'required_unresolved':['assembly_result.publishing','assembly_result.working_title','production_brief.audio_direction','actual tenant scoped Firestore payload storage mode','caption delivery policy']}
    return {'version':'V9_PHASE_A','status':'BLOCKED_COMMIT_DESIGN_ONLY','cloud_writes_enabled':False,'job_id':JOB,'assembly_job_id':live.get('assembly_job_id') if live else None,'issues':issues,'assets':assets,'proposed_result_fields':result,'data_model':{'job_collection':'reviveai_tenants/{tenant}/audio_finishing_jobs/{job}','storage_modes':['inline-json-v1','gzip-chunks-v1'],'runtime_artifacts':'runtime-artifacts/tenants/{tenant}/audio_finishing/{job}/assets/','warning':'FirestoreJobRepository.save is a non-transactional overwrite and cannot be called for live commit','asset_registry':'separate productions/{id}/assets registry is not the audio job asset lookup; do not create entries there as a substitute'},'missing_implementation':['construct full AudioFinishingResult from assembly and production records','validated transaction/CAS for inline and chunked repository formats','GCS create-only upload and generation/sha verification','rollback or cleanup on partial stage failure','resume existing review and QC; never publish directly']}

def main():
    p=argparse.ArgumentParser();p.add_argument('--preview-dir',required=True);p.add_argument('--snapshot');p.add_argument('--commit',action='store_true');args=p.parse_args()
    if args.commit:raise SystemExit('BLOCKED: V9 Phase A has no production commit capability')
    preview=Path(args.preview_dir)
    result=build(preview,args.snapshot)
    dest=preview/'v9-commit-preview.json';dest.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('V9 PHASE A:',result['status']);print('Preview manifest:',dest)
    for issue in result['issues']:print('BLOCKER:',issue)
    print('NO CLOUD SDK IMPORTS; NO NETWORK; NO FIRESTORE OR GCS WRITES')
if __name__=='__main__':main()
