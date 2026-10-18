"""V10: OFFLINE, commit-disabled recovered audio-result adapter.

No GCP clients, imports or network. No production write code.
Requires independently exported approved assembly and production brief records.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
from legacy_audio_v9b_contracts import build_result, local_artifacts, validate_live, UnsafeRecovery

JOB='audio_821f2a568f804076b10fa4364793385c'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
PRODUCTION='production_bbbc7d506f044325a8f321dc59c16b8a'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
TENANT='61cf44d3ae8277b1f9d2aa781d87e52d'


def read_json(p):
    return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def sha_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def unwrap(record):
    if not isinstance(record,dict):raise UnsafeRecovery('source record must be JSON object')
    if isinstance(record.get('result'),dict):return record['result']
    return record


def build(preview, snapshot, assembly_record=None, brief_record=None, *, max_age=300, validate_schema=True):
    preview=Path(preview); snap=read_json(snapshot)
    when=datetime.fromisoformat(str(snap['captured_at']).replace('Z','+00:00'))
    if when.tzinfo is None:raise UnsafeRecovery('snapshot must carry a timezone')
    age=(datetime.now(timezone.utc)-when).total_seconds()
    if not (0<=age<=max_age):raise UnsafeRecovery('live-state snapshot expired or future-dated')
    report,outputs=local_artifacts(preview)
    job=validate_live(snap)
    if job.get('assembly_job_id')!=ASSEMBLY:raise UnsafeRecovery('wrong approved assembly ID')
    session=(snap.get('autopilot') or {}).get('session') or {}
    if session.get('currentProductionJobId')!=PRODUCTION or session.get('status')!='RUNNING':raise UnsafeRecovery('autopilot state changed')
    if job.get('detail',{}).get('source_visual_asset_id')!=VISUAL:raise UnsafeRecovery('visual lineage changed')
    proposed=[];assets={'assembly_job_id':ASSEMBLY,'production_brief_job_id':job.get('production_brief_job_id')}
    for category,name,ext,mime in [('mix','local-preview-mix.m4a','m4a','audio/mp4'),('delivery','local-preview-delivery.mp4','mp4','video/mp4')]:
        digest=sha_file(preview/name)
        if hashlib.sha256(outputs[name]).hexdigest()!=digest:raise UnsafeRecovery('artifact changed during verification')
        asset_id=f'{category}_recovered_{digest[:20]}'
        filename=f'{asset_id}.{ext}'
        uri=f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}/audio_finishing/{JOB}/assets/{filename}'
        assets[category]={'asset_id':asset_id,'filename':filename,'gcs_uri':uri}
        proposed.append({'category':category,'local_path':str(preview/name),'asset_id':asset_id,'gcs_uri':uri,'sha256':digest,'size_bytes':len(outputs[name]),'mime_type':mime,'upload_precondition':'if_generation_match=0','remote_byte_hash_verification_required':True})
    blockers=[];result=None
    if assembly_record is None or brief_record is None:
        blockers.append('Authoritative approved assembly and production brief records are required; never synthesize publishing metadata')
    else:
        assembly_raw=read_json(assembly_record);brief_raw=read_json(brief_record)
        if assembly_raw.get('job_id') not in (None,ASSEMBLY):raise UnsafeRecovery('assembly record identity mismatch')
        if brief_raw.get('job_id') not in (None,job.get('production_brief_job_id')):raise UnsafeRecovery('brief record identity mismatch')
        assembly=unwrap(assembly_raw);brief=unwrap(brief_raw)
        if assembly.get('review_status')!='APPROVED':raise UnsafeRecovery('assembly must be approved')
        audio_direction=((brief.get('publishing') or {}).get('audio_direction'))
        if not isinstance(audio_direction,str):raise UnsafeRecovery('production brief audio direction missing')
        result=build_result(job,assembly,audio_direction,assets)
        if validate_schema:
            # Import model only, never initialize backend, Firestore or cloud clients.
            from app.models.audio_finishing import AudioFinishingResult
            result=AudioFinishingResult.model_validate(result).model_dump(mode='json')
        if result.get('review_status')!='NEEDS_REVIEW':raise UnsafeRecovery('review status must remain NEEDS_REVIEW')
        if result.get('selected_youtube_audio_library_track') is not None:raise UnsafeRecovery('replacement music must not be attributed to YouTube catalog')
    manifest={'version':'V10_OFFLINE_COMMIT_DISABLED','status':'SCHEMA_PREVIEW_ONLY' if not blockers else 'BLOCKED_MISSING_AUTHORITATIVE_RECORDS','audio_job_id':JOB,'assembly_job_id':ASSEMBLY,'production_id':PRODUCTION,'snapshot_captured_at':snap['captured_at'],'snapshot_age_seconds':age,'recovery_report_sha256':sha_file(preview/'recovery-report.json'),'source_visual_asset_id':VISUAL,'proposed_artifacts':proposed,'proposed_result':result,'blocked_reasons':blockers,'manual_review_required':['Production write authorization','Authoritative lease/status CAS at commit time','Real GCS generation and digest checks','Durable recovery journal','Asset endpoint readability','QC of shots 2/3 captions','Soundtrack rights and publication review'],'commit_enabled':False,'production_writes':False}
    return manifest


def main():
    p=argparse.ArgumentParser(description='V10 offline recovery adapter; production commit deliberately unavailable')
    p.add_argument('--preview-dir',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--assembly-record',type=Path);p.add_argument('--brief-record',type=Path)
    p.add_argument('--commit',action='store_true');a=p.parse_args()
    if a.commit:raise SystemExit('REFUSED: V10 does not contain production commit functionality')
    try:manifest=build(a.preview_dir,a.snapshot,a.assembly_record,a.brief_record)
    except (UnsafeRecovery,FileNotFoundError,ValueError,KeyError) as exc:raise SystemExit('BLOCKED: '+str(exc)) from exc
    dest=a.preview_dir/'v10-recovery-adapter-preview.json'
    dest.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    print('V10:',manifest['status']);print('MANIFEST:',dest)
    for reason in manifest['blocked_reasons']:print('BLOCKED:',reason)
    print('NO CLOUD CLIENTS; NO NETWORK; NO FIRESTORE/GCS WRITES; NO PRODUCTION COMMIT')

if __name__=='__main__':main()
