#!/usr/bin/env python3
"""Offline safety tests; uses no ADC, Firestore, GCS, or backend imports."""
import importlib.util, os, subprocess, sys
from pathlib import Path
path=Path(__file__).with_name('legacy_audio_recovery_v8.py')
spec=importlib.util.spec_from_file_location('v8',path);v8=importlib.util.module_from_spec(spec);spec.loader.exec_module(v8)
j={'job_id':v8.JOB,'assembly_job_id':v8.ASSEMBLY,'stage':'RENDERING','result':None,'detail':{'source_visual_asset_id':v8.VISUAL}}
a={'session':{'currentProductionJobId':v8.PRODUCTION,'currentAudioJobId':v8.JOB,'currentPublicationId':None}}
assert v8.check_payload(j,a)
print('PASS: intended job and autopilot state accepted')
for key,value in [('stage','COMPLETED'),('result',{'unexpected':'result'}),('job_id','other')]:
 x={**j,key:value};assert not v8.check_payload(x,a)
print('PASS: completed/replaced/wrong job rejected')
assert not v8.check_payload(j,{'session':{**a['session'],'currentPublicationId':'ytpub_existing'}})
print('PASS: existing publication rejected')
assert not v8.check_payload({**j,'detail':{**j['detail'],'render_checkpoint':{'state':'MUX_READY'}}},a)
print('PASS: existing checkpoint rejected')
result=subprocess.run([sys.executable,str(path),'--production-commit','--preview-dir','unused','--snapshot','unused'],capture_output=True,text=True)
assert result.returncode!=0 and 'PRODUCTION COMMIT DISABLED' in result.stderr
print('PASS: production commit explicitly refused')
old=os.environ.get('FIRESTORE_EMULATOR_HOST')
os.environ.pop('FIRESTORE_EMULATOR_HOST',None)
try:
 try:v8.emulator_db();raise AssertionError('Missing emulator host allowed')
 except ValueError:pass
finally:
 if old is not None:os.environ['FIRESTORE_EMULATOR_HOST']=old
print('PASS: emulator requires explicit loopback host')
print('ALL 6 V8 OFFLINE SAFETY CHECKS PASSED')
