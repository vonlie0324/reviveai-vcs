import importlib.util, json, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('v9',Path(__file__).with_name('legacy_audio_v9_commit_preview.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp)
    report={'job_id':m.JOB,'source_visual_asset_id':m.VISUAL,'mode':'LOCAL_DRY_RUN_NO_CLOUD_WRITES','music':{'preset':'CINEMATIC_AMBIENT'}}
    for name in m.ARTIFACTS:
        b=b'fake-'+name.encode();(p/name).write_bytes(b)
        report[name]={'sha256':m.digest(p/name),'size_bytes':len(b),'duration':15.0}
    (p/'recovery-report.json').write_text(json.dumps(report))
    out=m.build(p)
    assert out['status']=='BLOCKED_COMMIT_DESIGN_ONLY' and len(out['assets'])==2
    assert all(x['upload_enabled'] is False for x in out['assets'])
    print('PASS: manifest remains non-executable and writes disabled')
    (p/'local-preview-mix.m4a').write_bytes(b'changed')
    _,errors=m.verify_preview(p)
    assert any('hash/size mismatch' in x for x in errors)
    print('PASS: tampered mix hash rejected')
    assert all(x['gcs_precondition']=='if_generation_match=0' for x in out['assets'])
    print('PASS: create-only GCS design')
    assert 'gzip-chunks-v1' in out['data_model']['storage_modes']
    print('PASS: chunked Firestore incompatibility documented')
    assert out['proposed_result_fields']['review_status']=='NEEDS_REVIEW'
    print('PASS: human/QC review not bypassed')
print('ALL 5 V9 OFFLINE DESIGN CHECKS PASSED')
