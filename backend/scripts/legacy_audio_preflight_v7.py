#!/usr/bin/env python3
"""Read-only V7 preflight for one legacy audio job. Does not import the app."""
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

JOB='audio_821f2a568f804076b10fa4364793385c'
PRODUCTION='production_bbbc7d506f044325a8f321dc59c16b8a'
ASSEMBLY='assembly_46ec7d635b884406b41761be3261c22b'
VISUAL='final_f9c1a20be9ca4526a42f4d112c9efb46'
SOURCE_HASHES={
 f'{VISUAL}.mp4':'ade74515a1b2908bad2bf017cdd0cb90be01763b36ededdbe502443d64cdfddd',
 'narration-shot-01.wav':'69a33a0b538ca31a903f6bd993e0c8690ba1a630126f1351a11e150aaa0bf72b',
 'narration-shot-02.wav':'829f4ce67b3fdb85abcdd7c3f27b22ebc79b9c0367de4eeb455fb51f0bb0f140',
 'narration-shot-03.wav':'c7fbd2a54bf49fcc236da0f4a8be71bb341b7c55a06bd5a704663b44f81a80bc',
 'narration-shot-04.wav':'bcb9bb166e17e8ce3eb3f987d6bead4e86704de53ee61bfd0fb6d32da86766ec',
}
OUTPUT_HASHES={
 'local-preview-mix.m4a':'7f3d4461f0d5aa41ec39c9fcd5c73104319df75c83253fd1063c01eace14c67f',
 'local-preview-delivery.mp4':'0f17a31b1cb45ded9e106a2faac4d6203cf42644e12a90cc19e4a438a91b1f65',
}
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
 return h.hexdigest()
def add(checks,key,passed,info): checks.append({'check':key,'pass':bool(passed),'detail':info})
def preflight(directory,snapshot=None):
 d=Path(directory); report=json.loads((d/'recovery-report.json').read_text(encoding='utf-8'))
 checks=[]
 add(checks,'report_identity', report.get('job_id')==JOB and report.get('source_visual_asset_id')==VISUAL and report.get('mode')=='LOCAL_DRY_RUN_NO_CLOUD_WRITES','Exact legacy job, visual and dry-run mode')
 for name,want in SOURCE_HASHES.items():
  p=d/'downloaded'/name; documented=report.get('sources',{}).get(name,{})
  ok=p.is_file() and sha(p)==want and documented.get('sha256')==want and p.stat().st_size==documented.get('size_bytes')
  add(checks,'source:'+name,ok,'Expected SHA-256, report entry and bytes match')
 for name,want in OUTPUT_HASHES.items():
  p=d/name; documented=report.get(name,{})
  ok=p.is_file() and sha(p)==want and documented.get('sha256')==want and p.stat().st_size==documented.get('size_bytes') and abs(float(documented.get('duration',0))-15)<0.8
  add(checks,'output:'+name,ok,'Expected SHA-256, report entry, bytes and duration match')
 music=report.get('music',{})
 add(checks,'soundtrack_approval',music.get('type')=='explicitly_approved_generated_substitute' and music.get('preset')=='CINEMATIC_AMBIENT','User approved this substituted music for production QC and potential publication; still subject to QC and rights review')
 add(checks,'caption_limitations',any('shots 2 and 3' in str(x) and 'UNVERIFIED' in str(x) for x in report.get('warnings',[])),'Shot 2/3 word alignment remains unverified; no speech-verified caption claim')
 live_status='NOT_PROVIDED'
 if snapshot is not None:
  live_status='REJECTED'
  data=json.loads(Path(snapshot).read_text(encoding='utf-8'))
  job=data.get('audio_job') or {}; ap=data.get('autopilot') or {}; session=ap.get('session') or {}
  add(checks,'snapshot_identity',job.get('job_id')==JOB and job.get('assembly_job_id')==ASSEMBLY and (job.get('detail') or {}).get('source_visual_asset_id')==VISUAL,'Live job identity and original visual lineage')
  add(checks,'snapshot_stage',job.get('stage')=='RENDERING' and not job.get('result') and not (job.get('detail') or {}).get('render_checkpoint'),'Still stalled at RENDERING with no completed result/checkpoint')
  add(checks,'snapshot_autopilot',session.get('currentProductionJobId')==PRODUCTION and session.get('currentAudioJobId')==JOB and session.get('currentPublicationId') is None,'Expected active production/audio and no linked publication')
  captured=data.get('captured_at')
  try:
   dt=datetime.fromisoformat(captured.replace('Z','+00:00'))
   age=(datetime.now(timezone.utc)-dt.astimezone(timezone.utc)).total_seconds()
   fresh=0<=age<=300
  except (AttributeError,ValueError,TypeError): fresh=False; age=None
  add(checks,'snapshot_freshness',fresh,f'Captured {captured}; age {age} seconds; max 300')
  live_status='PASS' if all(c['pass'] for c in checks if c['check'].startswith('snapshot_')) else 'REJECTED'
 else:
  add(checks,'live_snapshot_required',False,'Supply a live snapshot no older than five minutes via --snapshot; default is NOT READY')
 overall=all(c['pass'] for c in checks)
 return {'schema_version':1,'operation':'READ_ONLY_PREFLIGHT_NO_PRODUCTION_WRITES','created_at':datetime.now(timezone.utc).isoformat(),'job_id':JOB,'source_visual_asset_id':VISUAL,'music_approval':'CINEMATIC_AMBIENT approved for production QC/potential publication; not final publishing approval','live_snapshot_status':live_status,'preflight_status':'PASS_FOR_COMMIT_DESIGN_ONLY' if overall else 'BLOCKED','checks':checks,'artifacts':{'mix':OUTPUT_HASHES['local-preview-mix.m4a'],'delivery':OUTPUT_HASHES['local-preview-delivery.mp4']},'commit_performed':False,'commit_implemented':False,'remaining_gates':['Production asset registry and persistence schema review','Live exclusive claim and generation fencing','SRT fallback and captions policy review','Music rights and delivery QC','Explicit separate approval before production writes']}
def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--preview-dir',type=Path,required=True)
 p.add_argument('--snapshot',type=Path,help='JSON containing captured_at, audio_job, autopilot from authenticated read-only browser fetch')
 p.add_argument('--output',type=Path,help='Output manifest path (defaults to preview-dir/v7-preflight-manifest.json)')
 a=p.parse_args(argv)
 try: result=preflight(a.preview_dir,a.snapshot)
 except (OSError,ValueError,KeyError,TypeError) as exc: p.exit(2,f'PREFLIGHT ERROR: {exc}\n')
 target=a.output or a.preview_dir/'v7-preflight-manifest.json'
 target.parent.mkdir(parents=True,exist_ok=True)
 target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
 for c in result['checks']:print(('PASS' if c['pass'] else 'BLOCK')+': '+c['check']+' — '+c['detail'])
 print('PREFLIGHT:',result['preflight_status'])
 print('MANIFEST:',target)
 print('NO CLOUD WRITES; NO COMMIT CAPABILITY')
 return 0 if result['preflight_status']=='PASS_FOR_COMMIT_DESIGN_ONLY' else 1
if __name__=='__main__':sys.exit(main())
