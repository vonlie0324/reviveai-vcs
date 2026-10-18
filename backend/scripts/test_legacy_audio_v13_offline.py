from __future__ import annotations
import sys, json, tempfile, hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
from copy import deepcopy
from legacy_audio_v13_readiness import analyze,Blocked,JOB,ASSEMBLY,PROD,VISUAL,TENANT

def main():
    with tempfile.TemporaryDirectory() as d:
        base=Path(d);content=b'v13-safe-test'; (base/'mix.m4a').write_bytes(content);(base/'del.mp4').write_bytes(content)
        digest=hashlib.sha256(content).hexdigest();prefix=f'gs://reviveai/videos/runtime-artifacts/tenants/{TENANT}/audio_finishing/{JOB}/assets/'
        ops=[{'category':c,'local_name':n,'bytes':len(content),'sha256':digest,'precondition':'if_generation_match=0','verify_remote_bytes':True,'capture_generation':True,'destination':prefix+c+'.'+ext} for c,n,ext in [('mix','mix.m4a','m4a'),('delivery','del.mp4','mp4')]]
        m={'status':'RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','commit_enabled':False,'audio_job_id':JOB,'proposed_result':{'review_status':'NEEDS_REVIEW','subtitles':None}}
        p={'status':'READY_FOR_ISOLATED_INTEGRATION_NOT_PRODUCTION','production_writes_enabled':False,'commit_available':False,'job_id':JOB,'assembly_job_id':ASSEMBLY,'production_id':PROD,'operations':ops}
        publishing={'youtube_title':'test'}
        r={'assembly_job':{'job_id':ASSEMBLY,'stage':'DELIVERED','result':{'review_status':'APPROVED','final_video':{'asset_id':VISUAL},'publishing':publishing}},'production_brief_job':{'job_id':PROD,'stage':'COMPLETED','result':{'review_status':'APPROVED','publishing':publishing}}}
        now=datetime.now(timezone.utc)
        s={'captured_at':now.isoformat(),'audio_job':{'job_id':JOB,'assembly_job_id':ASSEMBLY,'production_brief_job_id':PROD,'stage':'RENDERING','result':None,'detail':{'source_visual_asset_id':VISUAL}},'autopilot':{'revision':1,'session':{'currentProductionJobId':PROD,'currentAudioJobId':JOB,'currentPublicationId':None}}}
        def test(label,mutator,expected_block):
            mm,pp,rr,ss=map(deepcopy,(m,p,r,s));mutator(mm,pp,rr,ss)
            try:res=analyze(mm,pp,rr,ss,base,now=now)
            except Blocked:
                assert expected_block,label
            else:
                assert not expected_block,label
                assert res['commit_available'] is False and len(res['planned_write_set'])==4
            print('PASS:',label)
        test('normal read-only plan',lambda *x:None,False)
        test('expired snapshot',lambda m,p,r,s:s.update(captured_at=(now-timedelta(minutes=6)).isoformat()),True)
        test('existing publication',lambda m,p,r,s:s['autopilot']['session'].update(currentPublicationId='ytpub_test'),True)
        test('job progressed',lambda m,p,r,s:s['audio_job'].update(stage='COMPLETED'),True)
        test('wrong visual',lambda m,p,r,s:s['audio_job']['detail'].update(source_visual_asset_id='wrong'),True)
        test('changed asset',lambda m,p,r,s:p['operations'][0].update(sha256='bad'),True)
        test('missing create-only precondition',lambda m,p,r,s:p['operations'][0].update(precondition=''),True)
        test('bad destination',lambda m,p,r,s:p['operations'][0].update(destination='gs://other/mix.m4a'),True)
        test('unapproved brief',lambda m,p,r,s:r['production_brief_job']['result'].update(review_status='PENDING'),True)
        test('review already approved',lambda m,p,r,s:m['proposed_result'].update(review_status='APPROVED'),True)
        test('commit flag changed',lambda m,p,r,s:p.update(commit_available=True),True)
    print('V13: 11/11 OFFLINE CHECKS PASSED; ZERO NETWORK/PRODUCTION WRITES')
if __name__=='__main__':main()
