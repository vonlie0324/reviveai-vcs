"""Offline smoke checks; no application or cloud imports."""
import importlib.util, pathlib, tempfile, json, hashlib
root=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('audit',root/'legacy_audio_v9h_write_audit.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d)
 (p/'downloaded').mkdir()
 names=mod.SOURCES+tuple(x[0] for x in mod.OUTPUTS)
 for name in names:
  (p/('downloaded' if name in mod.SOURCES else '')/name).write_bytes(name.encode())
 def meta(name):
  b=name.encode();return {'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'duration':15}
 report={'job_id':mod.JOB,'source_visual_asset_id':mod.VISUAL,'mode':'LOCAL_DRY_RUN_NO_CLOUD_WRITES','music':{'type':'explicitly_approved_generated_substitute','preset':'CINEMATIC_AMBIENT'},'sources':{n:meta(n) for n in mod.SOURCES}}
 report.update({n:meta(n) for n,*_ in mod.OUTPUTS})
 (p/'recovery-report.json').write_text(json.dumps(report))
 source=pathlib.Path(__file__).resolve().parents[1]
 r=mod.build(p,None,source)
 assert r['commit_available'] is False and r['cloud_writes_enabled'] is False
 print('PASS: commit disabled and no production operations')
 assert all(x['passed'] for x in r['checks'] if x['name'].startswith('local_sha256:'))
 print('PASS: checks actual local bytes')
 assert len(r['proposed_assets'])==2 and all(x['upload_condition']=='if_generation_match=0' for x in r['proposed_assets'])
 print('PASS: only two create-only recovery asset proposals')
 assert all(x['passed'] for x in r['checks'] if x['name'].startswith('source_contract:'))
 print('PASS: backend source contracts match expected interfaces')
 (p/'local-preview-mix.m4a').write_bytes(b'tampered')
 r2=mod.build(p,None,source)
 assert any('local_sha256:local-preview-mix.m4a' in x for x in r2['blockers'])
 print('PASS: tampering blocks audit')
print('ALL 5 V9H OFFLINE CHECKS PASSED')
