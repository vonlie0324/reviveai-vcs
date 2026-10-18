#!/usr/bin/env python3
"""V8 guarded legacy recovery design and isolated Firestore emulator transaction exercise.

NO PRODUCTION COMMIT: this command does not import ReviveAI application or call GCS.
Emulator mode writes exclusively to project reviveai-local-test, default database,
and only if FIRESTORE_EMULATOR_HOST is set to loopback.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

JOB = 'audio_821f2a568f804076b10fa4364793385c'
PRODUCTION = 'production_bbbc7d506f044325a8f321dc59c16b8a'
ASSEMBLY = 'assembly_46ec7d635b884406b41761be3261c22b'
VISUAL = 'final_f9c1a20be9ca4526a42f4d112c9efb46'
TENANT = '61cf44d3ae8277b1f9d2aa781d87e52d'
HASHES = {
 'local-preview-mix.m4a':'7f3d4461f0d5aa41ec39c9fcd5c73104319df75c83253fd1063c01eace14c67f',
 'local-preview-delivery.mp4':'0f17a31b1cb45ded9e106a2faac4d6203cf42644e12a90cc19e4a438a91b1f65',
}
SOURCES = {
 f'{VISUAL}.mp4':'ade74515a1b2908bad2bf017cdd0cb90be01763b36ededdbe502443d64cdfddd',
 'narration-shot-01.wav':'69a33a0b538ca31a903f6bd993e0c8690ba1a630126f1351a11e150aaa0bf72b',
 'narration-shot-02.wav':'829f4ce67b3fdb85abcdd7c3f27b22ebc79b9c0367de4eeb455fb51f0bb0f140',
 'narration-shot-03.wav':'c7fbd2a54bf49fcc236da0f4a8be71bb341b7c55a06bd5a704663b44f81a80bc',
 'narration-shot-04.wav':'bcb9bb166e17e8ce3eb3f987d6bead4e86704de53ee61bfd0fb6d32da86766ec',
}

def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as stream:
  for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
 return h.hexdigest()

def check_payload(job,ap):
 s=ap.get('session') or {}
 return (job.get('job_id')==JOB and job.get('assembly_job_id')==ASSEMBLY
  and job.get('stage')=='RENDERING' and job.get('result') is None
  and not (job.get('detail') or {}).get('render_checkpoint')
  and (job.get('detail') or {}).get('source_visual_asset_id')==VISUAL
  and s.get('currentProductionJobId')==PRODUCTION and s.get('currentAudioJobId')==JOB
  and s.get('currentPublicationId') is None)

def prepare(directory,snapshot):
 d=Path(directory); report=json.loads((d/'recovery-report.json').read_text(encoding='utf-8'))
 live=json.loads(Path(snapshot).read_text(encoding='utf-8'))
 captured=datetime.fromisoformat(live['captured_at'].replace('Z','+00:00'))
 age=(datetime.now(timezone.utc)-captured.astimezone(timezone.utc)).total_seconds()
 if not 0<=age<=300: raise ValueError('Live snapshot expired; capture a new one (<5 min)')
 if not check_payload(live['audio_job'],live['autopilot']): raise ValueError('Live job or Autopilot state differs; abort')
 if report.get('job_id')!=JOB or report.get('mode')!='LOCAL_DRY_RUN_NO_CLOUD_WRITES' or report.get('source_visual_asset_id')!=VISUAL:
  raise ValueError('Unexpected V6 report identity')
 if report.get('music',{}).get('preset')!='CINEMATIC_AMBIENT' or report.get('music',{}).get('type')!='explicitly_approved_generated_substitute':
  raise ValueError('Music does not match operator approval')
 for name,digest in {**HASHES,**SOURCES}.items():
  path=d/(name if name in HASHES else 'downloaded/'+name)
  entry=report.get(name,{}) if name in HASHES else report.get('sources',{}).get(name,{})
  if not path.is_file() or sha(path)!=digest or entry.get('sha256')!=digest or path.stat().st_size!=entry.get('size_bytes'):
   raise ValueError(f'Artifact hash/size mismatch: {name}')
 if not any('shots 2 and 3' in str(w) and 'UNVERIFIED' in str(w) for w in report.get('warnings',[])):
  raise ValueError('Missing speech alignment warning')
 return {'schema':'V8_COMMIT_DESIGN_1','created_at':datetime.now(timezone.utc).isoformat(),
  'job_id':JOB,'production_id':PRODUCTION,'assembly_job_id':ASSEMBLY,'tenant':TENANT,
  'source_visual_asset_id':VISUAL,'snapshot_captured_at':live['captured_at'],
  'snapshot_job_updated_at':live['audio_job'].get('updated_at'),
  'snapshot_autopilot_revision':live['autopilot'].get('revision'),
  'input_hashes':SOURCES,'output_hashes':HASHES,
  'music':{'source':'REVIVEAI','preset':'CINEMATIC_AMBIENT','track_id':None,'operator_approved_for_qc':True},
  'speech_alignment':'UNVERIFIED_SHOTS_2_3','review_status':'NEEDS_REVIEW',
  'asset_lineage_must_equal':VISUAL,'publication_allowed':False,
  'production_commit_enabled':False,
  'planned_steps':['Re-read job and autopilot state transactionally','Acquire generation-fenced lease',
   'Upload unique-generation objects with create-only preconditions and checksum verification',
   'Build validated AudioFinishingResult with correct publishing metadata and no unverified subtitle claims',
   'Atomic inline-job update under lease; chunked documents must fail closed',
   'Preserve NEEDS_REVIEW; allow standard AI listening, delivery QC and publishing checks']}

def emulator_db():
 host=os.environ.get('FIRESTORE_EMULATOR_HOST','')
 if host not in ('127.0.0.1:8085','localhost:8085','[::1]:8085'):
  raise ValueError('Emulator mode requires FIRESTORE_EMULATOR_HOST=127.0.0.1:8085; no production fallback')
 from google.cloud import firestore
 return firestore.Client(project='reviveai-local-test',database='(default)')

def claim(db,namespace,owner):
 from google.cloud import firestore
 ref=db.collection('reviveai_tenants').document(namespace).collection('audio_mux_recovery_locks').document(JOB)
 tx=db.transaction()
 @firestore.transactional
 def action(t):
  data=ref.get(transaction=t).to_dict() or {}; now=datetime.now(timezone.utc)
  expiry=data.get('expires_at')
  if expiry and expiry>now: return 0
  generation=int(data.get('generation') or 0)+1
  t.set(ref,{'owner':owner,'generation':generation,'claimed_at':now,'expires_at':now+timedelta(minutes=45)})
  return generation
 return action(tx)

def emulator_commit(db,namespace,owner,generation,manifest):
 """Exercise actual Firestore transaction fencing; test fixture only, not production data."""
 from google.cloud import firestore
 root=db.collection('reviveai_tenants').document(namespace)
 lock=root.collection('audio_mux_recovery_locks').document(JOB)
 jobref=root.collection('audio_finishing_jobs').document(JOB)
 tx=db.transaction()
 @firestore.transactional
 def action(t):
  lk=lock.get(transaction=t).to_dict() or {}
  raw=jobref.get(transaction=t).to_dict() or {}
  expiry=lk.get('expires_at'); now=datetime.now(timezone.utc)
  if lk.get('owner')!=owner or int(lk.get('generation') or 0)!=generation or not expiry or expiry<=now:return False
  if raw.get('storage_mode')!='inline-json-v1' or not isinstance(raw.get('payload_json'),str):return False
  payload=json.loads(raw['payload_json'])
  if (payload.get('job_id')!=JOB or payload.get('stage')!='RENDERING' or payload.get('result') is not None
      or (payload.get('detail') or {}).get('render_checkpoint') or payload.get('updated_at')!=manifest['snapshot_job_updated_at']):return False
  # A test-only result represents the proposed metadata. Never falsely label this fixture as production-ready.
  payload['stage']='COMPLETED';payload['updated_at']=now.isoformat();payload['message']='EMULATOR TEST ONLY: reconstructed output';payload['error']=None
  payload['detail']={**(payload.get('detail') or {}),'v8_emulator_test':{'generation':generation,'source_visual_asset_id':VISUAL,'outputs':HASHES}}
  serialized=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
  b=serialized.encode('utf-8')
  if len(b)>700*1024:return False
  t.set(jobref,{'schema_version':2,'storage_mode':'inline-json-v1','payload_json':serialized,
                'payload_size_bytes':len(b),'payload_sha256':hashlib.sha256(b).hexdigest(),'persisted_at':now})
  t.update(lock,{'committed_generation':generation})
  return True
 return action(tx)

def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--preview-dir',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True)
 p.add_argument('--emulator-test',action='store_true',help='Create isolated synthetic fixture and exercise fenced commit against local emulator only')
 p.add_argument('--production-commit',action='store_true',help='Always refused in V8: production is deliberately disabled')
 args=p.parse_args(argv)
 if args.production_commit: p.error('PRODUCTION COMMIT DISABLED: separate operator approval and implementation review required')
 try:
  manifest=prepare(args.preview_dir,args.snapshot)
  target=args.preview_dir/'v8-commit-design.json'
  target.write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
  print('PASS: V8 local hashes and fresh live-state snapshot; production writes disabled')
  print('DESIGN:',target)
  if args.emulator_test:
   db=emulator_db(); ns='v8-isolated-'+uuid.uuid4().hex; owner='owner-'+uuid.uuid4().hex
   root=db.collection('reviveai_tenants').document(ns)
   # Synthetic job fixture. Never import or load real tenant production document.
   job={'job_id':JOB,'assembly_job_id':ASSEMBLY,'stage':'RENDERING','updated_at':manifest['snapshot_job_updated_at'],
        'detail':{'source_visual_asset_id':VISUAL},'result':None}
   enc=json.dumps(job,separators=(',',':'))
   root.collection('audio_finishing_jobs').document(JOB).set({'storage_mode':'inline-json-v1','payload_json':enc})
   gen=claim(db,ns,owner)
   assert gen>0 and claim(db,ns,'competitor')==0,'duplicate ownership was not blocked'
   assert emulator_commit(db,ns,owner,gen,manifest),'first fenced commit failed'
   assert not emulator_commit(db,ns,owner,gen,manifest),'duplicate commit was not rejected'
   assert not emulator_commit(db,ns,'competitor',gen,manifest),'wrong owner was not rejected'
   print('PASS: isolated Firestore emulator claim, duplicate block, fenced commit and duplicate/wrong-owner rejection')
   print('EMULATOR NAMESPACE:',ns)
  print('NO PRODUCTION CLOUD WRITES; NO GCS UPLOADS; NO PUBLISHING')
  return 0
 except (ValueError, OSError, AssertionError, KeyError, TypeError, json.JSONDecodeError) as exc:
  print('BLOCKED:',exc,file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
