"""No app server, ADC, Firestore client, or network invoked."""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from legacy_audio_v9b_contracts import *


def fixture():
    options={'voiceover_enabled':True,'music_enabled':True,'ambience_sfx_enabled':True,'music_volume':.55,'voice_volume':1,'ambience_volume':.7,'duck_music_during_voiceover':True,'music_source':'YOUTUBE_AUDIO_LIBRARY','music_preset':'AUTO'}
    job={'job_id':JOB,'stage':'RENDERING','assembly_job_id':'assembly_test','production_brief_job_id':'brief_test','media_job_id':'media_test','options':options,'detail':{'source_visual_asset_id':VISUAL,'narration_stems':[{'shot_number':i,'duration_seconds':dur,'text':f'Voice shot {i}'} for i,dur in enumerate([3,3,4,5],1)]},'progress_total':5}
    assembly={'review_status':'APPROVED','final_video':{'asset_id':VISUAL},'working_title':'Synthetic title','total_duration_seconds':15,'publishing':{'youtube_title':'Synthetic title','description':'Test','social_caption':'Test','thumbnail_concept':'Test','audio_direction':'Soft room music','accessibility_alt_text':'Test'},'timeline':[{'shot_number':i,'output_duration_seconds':dur} for i,dur in enumerate([3,3,4,5],1)]}
    base='gs://fake-bucket/runtime-artifacts/tenants/emulator/audio_finishing/'+JOB+'/assets/'
    assets={'assembly_job_id':'assembly_test','production_brief_job_id':'brief_test'}
    for name,ext in [('mix','m4a'),('delivery','mp4')]:assets[name]={'asset_id':name+'_fixture','filename':name+'_fixture.'+ext,'gcs_uri':base+name+'_fixture.'+ext}
    return job,assembly,assets

def ok(label):print('PASS:',label)

def rejects(action):
    try:action()
    except UnsafeRecovery:return
    raise AssertionError('expected fail closed')

def main():
    job,assembly,assets=fixture()
    result=build_result(job,assembly,'Soft room music',assets)
    assert result['review_status']=='NEEDS_REVIEW' and result['effective_music_source']=='REVIVEAI'
    assert result['publishing']==assembly['publishing'] and result['subtitles'] is None
    assert [c['start_seconds'] for c in result['voiceover_cues']]==[0,3,6,10]
    ok('original publishing and narration timeline preserved')
    try:
        from app.models.audio_finishing import AudioFinishingResult
    except ImportError as exc:raise SystemExit('Install project dependencies for Pydantic schema validation: '+str(exc))
    validated=AudioFinishingResult.model_validate(result)
    assert validated.review_status.value=='NEEDS_REVIEW' and validated.effective_music_source.value=='REVIVEAI'
    ok('actual ReviveAI AudioFinishingResult Pydantic schema accepted')
    changed=dict(assembly,review_status='NEEDS_REVIEW')
    rejects(lambda:build_result(job,changed,'',assets))
    changed=dict(assembly,final_video={'asset_id':'other'})
    rejects(lambda:build_result(job,changed,'',assets))
    changed=dict(assembly,timeline=[*assembly['timeline'][:3],{'shot_number':4,'output_duration_seconds':10}])
    rejects(lambda:build_result(job,changed,'',assets))
    ok('unapproved visual, altered lineage and timeline rejected')
    store=FakeCreateOnlyObjects();data=b'test-file'
    store.upload('fake/object',data,if_generation_match=0,expected_sha=sha(data))
    rejects(lambda:store.upload('fake/object',data,if_generation_match=0,expected_sha=sha(data)))
    rejects(lambda:store.upload('fake/other',data,if_generation_match=1,expected_sha=sha(data)))
    rejects(lambda:store.upload('fake/other',b'wrong',if_generation_match=0,expected_sha=sha(data)))
    ok('fake GCS create-only, collision and digest safeguards')
    for chunked in (False,True):
        storage=FakeChunkedJobCAS(job,chunked=chunked)
        ver,_=storage.snapshot()
        storage.update(ver,JOB,result)
        rejects(lambda:storage.update(ver,JOB,result))
        rejects(lambda:storage.update(storage.version,JOB,result))
        assert storage.payload['result']['review_status']=='NEEDS_REVIEW'
        if chunked:assert len(storage.chunks)==1
    ok('inline and chunked simulation reject stale and duplicate CAS')
    rejects(lambda:FakeChunkedJobCAS(job).update(1,JOB,result,owner_valid=False))
    ok('lost owner cannot commit')
    print('ALL 6 V9B OFFLINE CONTRACT CHECKS PASSED')
    print('NO FIRESTORE OR GCS CLIENT; NO CLOUD WRITES; NO PRODUCTION COMMIT')
if __name__=='__main__':main()
