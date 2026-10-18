"""Pure offline V10 safeguards, no GCP clients."""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from legacy_audio_v10_adapter import build, UnsafeRecovery
from legacy_audio_v9b_contracts import JOB,VISUAL
from datetime import datetime, timezone

def main():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d); (p/'downloaded').mkdir()
        sources={}
        from hashlib import sha256
        for n in [VISUAL+'.mp4', *[f'narration-shot-{i:02}.wav' for i in range(1,5)]]:
            data=n.encode(); (p/'downloaded'/n).write_bytes(data)
            sources[n]={'sha256':sha256(data).hexdigest(),'size_bytes':len(data)}
        report={'job_id':JOB,'source_visual_asset_id':VISUAL,'music':{'preset':'CINEMATIC_AMBIENT'},'sources':sources}
        for n in ['local-preview-mix.m4a','local-preview-delivery.mp4']:
            data=n.encode();(p/n).write_bytes(data)
            report[n]={'sha256':sha256(data).hexdigest(),'size_bytes':len(data),'duration':15}
        (p/'recovery-report.json').write_text(json.dumps(report))
        job={'job_id':JOB,'stage':'RENDERING','result':None,'assembly_job_id':'assembly_46ec7d635b884406b41761be3261c22b','production_brief_job_id':'brief','detail':{'source_visual_asset_id':VISUAL},'options':{}}
        snapshot={'captured_at':datetime.now(timezone.utc).isoformat(),'audio_job':job,'autopilot':{'session':{'status':'RUNNING','currentAudioJobId':JOB,'currentProductionJobId':'production_bbbc7d506f044325a8f321dc59c16b8a','currentPublicationId':None}}}
        sp=p/'snapshot.json';sp.write_text(json.dumps(snapshot))
        result=build(p,sp,validate_schema=False)
        assert result['status']=='BLOCKED_MISSING_AUTHORITATIVE_RECORDS' and not result['commit_enabled'] and len(result['proposed_artifacts'])==2
        print('PASS: no authoritative assembly/brief produces blocked artifact-only preview')
        assert all(x['upload_precondition']=='if_generation_match=0' for x in result['proposed_artifacts'])
        print('PASS: proposed upload object names are create-only')
        snapshot['audio_job']['stage']='COMPLETED';sp.write_text(json.dumps(snapshot))
        try:build(p,sp,validate_schema=False)
        except UnsafeRecovery:pass
        else:raise AssertionError('already completed job accepted')
        print('PASS: completed job rejected')
        snapshot['audio_job']['stage']='RENDERING';snapshot['autopilot']['session']['currentPublicationId']='ytpub_fake';sp.write_text(json.dumps(snapshot))
        try:build(p,sp,validate_schema=False)
        except UnsafeRecovery:pass
        else:raise AssertionError('publication accepted')
        print('PASS: linked publication rejected')
        snapshot['autopilot']['session']['currentPublicationId']=None;sp.write_text(json.dumps(snapshot));(p/'local-preview-mix.m4a').write_bytes(b'tampered')
        try:build(p,sp,validate_schema=False)
        except UnsafeRecovery:pass
        else:raise AssertionError('tampered mix accepted')
        print('PASS: tampered mix rejected')
    print('ALL 5 V10 OFFLINE CHECKS PASSED')
    print('NO APPLICATION STARTUP; NO CLOUD CLIENTS; NO PRODUCTION COMMIT')
if __name__=='__main__':main()
