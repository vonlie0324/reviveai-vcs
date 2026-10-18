"""Isolated V11 gate tests. Uses only temporary files and synthetic data."""
from __future__ import annotations
import copy, hashlib, tempfile
from pathlib import Path
from legacy_audio_v11_guarded_plan import validate,Blocked,JOB,PROD,ASSEMBLY,PREFIX

def test():
    with tempfile.TemporaryDirectory() as t:
        d=Path(t); arts=[]; result_assets={}
        for category,name,ext in (('mix','local-preview-mix.m4a','.m4a'),('delivery','local-preview-delivery.mp4','.mp4')):
            p=d/name;p.write_bytes(('SYNTHETIC_V11_'+category).encode())
            sha=hashlib.sha256(p.read_bytes()).hexdigest();asset_id=f'{category}_recovered_{sha[:20]}';uri=PREFIX+asset_id+ext
            arts.append({'category':category,'sha256':sha,'size_bytes':p.stat().st_size,'asset_id':asset_id,'gcs_uri':uri,'upload_precondition':'if_generation_match=0','remote_byte_hash_verification_required':True})
            result_assets['audio_mix' if category=='mix' else 'delivery_video']={'asset_id':asset_id,'gcs_uri':uri}
        m={'status':'RESULT_SCHEMA_VALIDATED_COMMIT_DISABLED','commit_enabled':False,'audio_job_id':JOB,'assembly_job_id':ASSEMBLY,'production_job_id':PROD,'review_approved':True,'narration_word_alignment_shots_2_3':'UNVERIFIED','snapshot_age_seconds':10,'proposed_artifacts':arts,'proposed_result':{'review_status':'NEEDS_REVIEW','reviewed_at':None,'assembly_job_id':ASSEMBLY,'production_brief_job_id':PROD,'effective_music_source':'REVIVEAI','effective_music_preset':'CINEMATIC_AMBIENT','selected_youtube_audio_library_track':None,'total_duration_seconds':15,'publishing':{'title':'synthetic'},'subtitles':None,'warnings':['UNVERIFIED shots 2/3'],**result_assets}}
        assert len(validate(m,d)['operations'])==2;print('PASS: valid synthetic recovery plan')
        cases=[('unapproved',lambda x:x.update(review_approved=False)),('music provenance',lambda x:x['proposed_result'].update(effective_music_source='YOUTUBE_AUDIO_LIBRARY')),('missing warning',lambda x:x['proposed_result'].update(warnings=[])),('wrong job',lambda x:x.update(audio_job_id='other')),('wrong artifact destination',lambda x:x['proposed_artifacts'][0].update(gcs_uri='gs://other/unsafe')),('missing create-only',lambda x:x['proposed_artifacts'][0].update(upload_precondition='none')),('fake approval',lambda x:x['proposed_result'].update(review_status='APPROVED')),('stale origin snapshot',lambda x:x.update(snapshot_age_seconds=900))]
        for name,mutate in cases:
            bad=copy.deepcopy(m);mutate(bad)
            try:validate(bad,d)
            except Blocked:print('PASS: blocked '+name)
            else:raise AssertionError('gate accepted '+name)
        (d/'local-preview-mix.m4a').write_bytes(b'changed')
        try:validate(m,d)
        except Blocked:print('PASS: blocked modified local artifact')
        else:raise AssertionError('modified artifact accepted')
        print('ALL 10 V11 OFFLINE CHECKS PASSED')
if __name__=='__main__':test()
