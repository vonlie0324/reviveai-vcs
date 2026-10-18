from datetime import datetime, timedelta, timezone
from legacy_audio_v14_inspect import summarize
now=datetime.now(timezone.utc)
a={'storage_mode':'inline-json-v1','payload_json':'{"job_id":"audio_test","stage":"RENDERING","result":null,"detail":{"source_visual_asset_id":"asset"}}'}
r=summarize(a,{'owner':'worker','generation':2,'expires_at':now+timedelta(minutes=2)},{'status':'RUNNING','lease_owner':'worker','lease_expires_at':now+timedelta(minutes=1)},{'payload_json':'{"session":{"currentAudioJobId":"audio_test"}}'},now)
assert r['mux_lock']['expiry_state']=='ACTIVE'
assert r['supervisor_queue']['lease_state']=='ACTIVE'
assert r['audio_job']['stage']=='RENDERING'
assert r['production_commit_enabled'] is False and r['write_operations_performed']==0
r=summarize({'storage_mode':'gzip-chunks-v1'},{},{},{},now)
assert r['audio_job']['payload_parse_warning']=='CHUNKED_PAYLOAD_NOT_DECODED'
assert r['mux_lock']['expiry_state']=='UNKNOWN'
print('V14 OFFLINE: PASS; no cloud imports, reads, or writes')
