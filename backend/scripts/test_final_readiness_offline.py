from pathlib import Path
from tempfile import TemporaryDirectory
import importlib.util,hashlib
m=Path(__file__).with_name('reviveai_final_readiness.py')
spec=importlib.util.spec_from_file_location('readiness',m);x=importlib.util.module_from_spec(spec);spec.loader.exec_module(x)
with TemporaryDirectory() as temp:
 p=Path(temp);(p/'mix.m4a').write_bytes(b'mix');(p/'delivery.mp4').write_bytes(b'delivery')
 ops=[]
 for category,name in [('mix','mix.m4a'),('delivery','delivery.mp4')]:
  bs=(p/name).read_bytes();ops.append({'category':category,'local_name':name,'bytes':len(bs),'sha256':hashlib.sha256(bs).hexdigest(),'destination':x.PREFIX+name,'precondition':'if_generation_match=0','verify_remote_bytes':True,'capture_generation':True})
 manifest={'status':'RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','commit_enabled':False,'audio_job_id':x.JOB,'proposed_result':{'review_status':'NEEDS_REVIEW','reviewed_at':None,'subtitles':None}}
 plan={'status':'READY_FOR_ISOLATED_INTEGRATION_NOT_PRODUCTION','production_writes_enabled':False,'commit_available':False,'job_id':x.JOB,'production_id':x.PROD,'assembly_job_id':x.ASSEMBLY,'operations':ops}
 publishing={'youtube_title':'existing'}
 records={'assembly_job':{'job_id':x.ASSEMBLY,'stage':'DELIVERED','result':{'review_status':'APPROVED','final_video':{'asset_id':x.VISUAL},'publishing':publishing}},'production_brief_job':{'job_id':x.PROD,'stage':'COMPLETED','result':{'review_status':'APPROVED','publishing':publishing}}}
 r=x.assess(manifest,plan,records,p)
 assert all(c['passed'] for c in r['checks']),r['checks']
 assert r['commit_enabled'] is False and r['deployment_allowed'] is False
 assert len(r['proposed_write_set'])==6
 ops[0]['precondition']='none';r=x.assess(manifest,plan,records,p)
 assert any(not c['passed'] for c in r['checks'])
 ops[0]['precondition']='if_generation_match=0';(p/'mix.m4a').write_bytes(b'evil')
 r=x.assess(manifest,plan,records,p);assert any(not c['passed'] for c in r['checks'])
 ops[0]['local_name']='../elsewhere';r=x.assess(manifest,plan,records,p)
 assert any(not c['passed'] for c in r['checks'])
print('FINAL READINESS: 4 OFFLINE SCENARIOS PASSED; COMMIT DISABLED')
