"""V9H offline write-contract audit. Stdlib only; no production commit implementation."""
from __future__ import annotations
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path

JOB='audio_821f2a568f804076b10fa4364793385c'
PROD='production_bbbc7d506f044325a8f321dc59c16b8a'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
TENANT='61cf44d3ae8277b1f9d2aa781d87e52d'
OUTPUTS=(('local-preview-mix.m4a','mix','audio/mp4'),('local-preview-delivery.mp4','delivery','video/mp4'))
SOURCES=(f'{VISUAL}.mp4',*(f'narration-shot-{i:02}.wav' for i in range(1,5)))

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def build(preview:Path, snapshot:Path|None, source_root:Path):
    blockers=[]; checks=[]
    def check(name,passed,detail):
        checks.append({'name':name,'passed':bool(passed),'detail':str(detail)})
        if not passed:blockers.append(f'{name}: {detail}')
    report_path=preview/'recovery-report.json'
    try: report=json.loads(report_path.read_text('utf-8'))
    except (ValueError,OSError) as exc: raise RuntimeError(f'Cannot load V6 report: {exc}') from exc
    check('recovery_identity',report.get('job_id')==JOB and report.get('source_visual_asset_id')==VISUAL and report.get('mode')=='LOCAL_DRY_RUN_NO_CLOUD_WRITES','V6 report must identify expected dry-run job and visual master')
    check('soundtrack_selection',report.get('music',{}).get('type')=='explicitly_approved_generated_substitute' and report.get('music',{}).get('preset')=='CINEMATIC_AMBIENT','Generated music is a substitution; operator approval for QC/potential publication is recorded separately')
    objects=[]
    for name in SOURCES+tuple(x[0] for x in OUTPUTS):
        p=preview/('downloaded' if name in SOURCES else '')/name
        meta=(report.get('sources') or {}).get(name) if name in SOURCES else report.get(name)
        valid=bool(p.is_file() and isinstance(meta,dict) and sha(p)==meta.get('sha256') and p.stat().st_size==meta.get('size_bytes'))
        check('local_sha256:'+name,valid,'Recorded SHA-256 and size must match actual bytes')
    for name,prefix,mime in OUTPUTS:
        meta=report.get(name) or {}
        digest=meta.get('sha256') or ''
        if not re.fullmatch('[0-9a-f]{64}',digest): digest='0'*64
        asset_id=f'{prefix}_recovered_{digest[:20]}'
        filename=asset_id+('.m4a' if prefix=='mix' else '.mp4')
        uri=f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}/audio_finishing/{JOB}/assets/{filename}'
        objects.append({'local_file':str(preview/name),'asset_id':asset_id,'filename':filename,'mime_type':mime,'size_bytes':meta.get('size_bytes'),'sha256':meta.get('sha256'),'proposed_gcs_uri':uri,'upload_condition':'if_generation_match=0','must_verify_remote_sha256':True,'write_enabled':False})
    source_contracts={
      'app/services/firestore_job_repository.py':('class FirestoreJobRepository','STORAGE_INLINE','STORAGE_CHUNKED','def _decode_document','def save('),
      'app/services/runtime_artifact_store.py':('class RuntimeArtifactStore','def _object_name','def upload_file('),
      'app/services/audio_finishing_job_service.py':('class AudioFinishingJobStore','def _sync_artifacts','def _persist_cloud','def _persist('),
      'app/models/audio_finishing.py':('class AudioFinishingResult','class AudioFinishingJob','NEEDS_REVIEW')}
    signatures={}
    for rel,markers in source_contracts.items():
        f=source_root/rel
        content=f.read_text('utf-8') if f.is_file() else ''
        missing=[x for x in markers if x not in content]
        check('source_contract:'+rel,not missing,'Missing signatures: '+','.join(missing) if missing else 'Observed expected source symbols')
        signatures[rel]={'sha256':sha(f) if f.is_file() else None,'missing_markers':missing}
    live=None;age=None
    if snapshot:
        try:
            payload=json.loads(snapshot.read_text('utf-8'))
            job=payload.get('audio_job') or {}
            autopilot=(payload.get('autopilot') or {}).get('session') or {}
            ts=datetime.fromisoformat(str(payload['captured_at']).replace('Z','+00:00'))
            age=(datetime.now(timezone.utc)-ts).total_seconds()
            check('snapshot_freshness',0<=age<=300,'Snapshot must be between 0 and 300 seconds old')
            ok=job.get('job_id')==JOB and job.get('assembly_job_id')==ASSEMBLY and job.get('stage')=='RENDERING' and job.get('result') is None and not (job.get('detail') or {}).get('render_checkpoint') and (job.get('detail') or {}).get('source_visual_asset_id')==VISUAL
            check('job_state',ok,'Stalled audio job, visual lineage, absent result/checkpoint must match')
            ok=autopilot.get('currentProductionJobId')==PROD and autopilot.get('currentAudioJobId')==JOB and autopilot.get('currentPublicationId') is None
            check('autopilot_state',ok,'Expected active production, audio and no linked publication')
            live={'captured_at':payload['captured_at'],'job_updated_at':job.get('updated_at'),'autopilot_revision':(payload.get('autopilot') or {}).get('revision'),'audio_options':job.get('options'),'job_storage_mode':'UNKNOWN_REQUIRES_DIRECT_FIRESTORE_READ'}
        except (ValueError,KeyError,TypeError,OSError) as exc:
            check('snapshot_parse',False,str(exc))
    else:check('snapshot_present',False,'No fresh authenticated snapshot provided')
    unresolved=[
      'Obtain approved assembly result: working_title, PublishingPackage, timeline/subtitle references, duration and immutable visual lineage',
      'Obtain production brief audio_direction and validate original approved production/assembly identities',
      'Read current authoritative Firestore job and storage mode in a lease-fenced transaction; browser snapshot alone is insufficient',
      'Stage objects with GCS create-only generation preconditions and verify remote digest plus generation',
      'Use durable generation-fenced journal; support recovery after upload/journal/switch interruptions',
      'Do not call AudioFinishingJobStore.save or FirestoreJobRepository.save for recovery CAS',
      'Ensure exact AudioFinishingResult model, NEEDS_REVIEW, preserved word-offset warnings (shots 2/3), review/publishing gate compatibility',
      'Document approved procedural music rights, provenance and attribution; it is not a YouTube Audio Library track',
      'Define caption fallback policy and QC path before enabling supervisor progression',
      'Re-read active Autopilot publication state before and after finalization and avoid direct publishing',
      'Obtain separate explicit production commit authorization'
    ]
    return {'version':'V9H_READ_ONLY_AUDIT','status':'AUDIT_PASSED_COMMIT_DISABLED' if not blockers else 'AUDIT_BLOCKED_COMMIT_DISABLED','cloud_writes_enabled':False,'commit_available':False,'audio_job_id':JOB,'production_id':PROD,'tenant_id':TENANT,'source_visual_asset_id':VISUAL,'snapshot_age_seconds':age,'checks':checks,'blockers':blockers,'proposed_assets':objects,'source_contract_hashes':signatures,'snapshot_summary':live,'required_production_write_sequence':['Verify current authoritative job, assembly, brief, publication and recovery lease','Journal staging intent with generation and expected hashes','Create-only GCS staging, verify bytes and generation','Stage compatible inline or gzip chunks without switching parent','Transactional lease/generation/status compare-and-set parent switch, job status COMPLETED only after all verified assets','Reconcile journal; verify audio job asset URLs and result; preserve NEEDS_REVIEW','Allow existing Autopilot review/QC flow; do not publish directly'],'unresolved_before_commit':unresolved}

def main():
    p=argparse.ArgumentParser(description='Read-only V9H write contract audit; cannot commit')
    p.add_argument('--preview-dir',type=Path,required=True)
    p.add_argument('--snapshot',type=Path)
    p.add_argument('--source-root',type=Path,default=Path.cwd())
    p.add_argument('--commit',action='store_true')
    a=p.parse_args()
    if a.commit:raise SystemExit('REFUSED: V9H never writes production data')
    manifest=build(a.preview_dir,a.snapshot,a.source_root)
    target=a.preview_dir/'v9h-write-audit.json'
    target.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
    for c in manifest['checks']:print(('PASS' if c['passed'] else 'BLOCKED')+': '+c['name'])
    print('V9H:',manifest['status']);print('MANIFEST:',target)
    print('NO CLOUD CLIENTS; NO NETWORK; NO PRODUCTION WRITES; NO COMMIT')
if __name__=='__main__': main()
