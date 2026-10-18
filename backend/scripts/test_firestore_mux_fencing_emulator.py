"""Emulator-only integration verification; never imports app modules."""
import ast
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from google.cloud import firestore

assert os.environ.get('FIRESTORE_EMULATOR_HOST') in ('127.0.0.1:8085', 'localhost:8085'), 'REFUSING live Firestore'
db = firestore.Client(project='reviveai-local-test', database='(default)')
assert db.project == 'reviveai-local-test', 'REFUSING unexpected project'

root = Path(__file__).resolve().parents[1]
src = root / 'app/services/audio_finishing_job_service.py'
module = ast.parse(src.read_text(encoding='utf-8'))
selected = {'_mux_recovery_lock_ref', '_acquire_mux_recovery_claim', '_owns_mux_recovery_claim',
            '_release_mux_recovery_claim', '_mux_recovery_claim_generation', '_commit_mux_recovery_fenced'}
funcs = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in selected]
assert {node.name for node in funcs} == selected

tenant = 'fencing-test-' + uuid4().hex
job_id = 'audio_test_' + uuid4().hex
class Repo:
    SCHEMA_VERSION = 2
    STORAGE_INLINE = 'inline-json-v1'
    INLINE_JSON_LIMIT_BYTES = 700*1024
    _encode = staticmethod(lambda payload: json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
    _sha256 = staticmethod(lambda data: hashlib.sha256(data).hexdigest())
class Stage:
    RENDERING = type('S', (), {'value':'RENDERING'})()
    COMPLETED = type('S', (), {'value':'COMPLETED'})()
ns = dict(get_runtime_firestore_client=lambda: db, tenant_namespace=lambda: tenant,
          datetime=datetime, timedelta=timedelta, timezone=timezone, json=json,
          AudioFinishingJobStage=Stage, FirestoreJobRepository=Repo)
exec(compile(ast.Module(body=funcs, type_ignores=[]), str(src), 'exec'), ns)
acquire = ns['_acquire_mux_recovery_claim']
owns = ns['_owns_mux_recovery_claim']
release = ns['_release_mux_recovery_claim']
generation = ns['_mux_recovery_claim_generation']
commit = ns['_commit_mux_recovery_fenced']
lock_ref = ns['_mux_recovery_lock_ref'](job_id)
job_ref = db.collection('reviveai_tenants').document(tenant).collection('audio_finishing_jobs').document(job_id)
base = {'job_id': job_id, 'stage':'RENDERING', 'version_number': 1, 'progress_total':5,
        'progress_current':4, 'detail':{'render_checkpoint':{'version':1,'state':'MUX_READY','delivery_asset_id':'delivery-test'}},
        'result':{'delivery_video':{'asset_id':'delivery-test','filename':'base.mp4'}}}
job_ref.set({'schema_version':2,'storage_mode':Repo.STORAGE_INLINE,'payload_json':Repo._encode(base)})
try:
    assert acquire(job_id, 'A')
    g1 = generation(job_id, 'A')
    assert g1 == 1
    assert not acquire(job_id, 'B')
    assert not commit(job_id,'B',g1,'bad.mp4','gs://dummy/bad.mp4')
    print('PASS: competitor cannot commit')
    release(job_id,'A')
    assert acquire(job_id,'B')
    g2 = generation(job_id,'B')
    assert g2 == g1 + 1, (g1,g2)
    assert not commit(job_id,'A',g1,'stale.mp4','gs://dummy/stale.mp4')
    print('PASS: released worker rejected after takeover')
    assert not commit(job_id,'B',g1,'wrong-generation.mp4','gs://dummy/wrong.mp4')
    print('PASS: generation mismatch rejected')
    assert commit(job_id,'B',g2,'good.mp4','gs://dummy/good.mp4')
    payload = json.loads(job_ref.get().to_dict()['payload_json'])
    assert payload['stage'] == 'COMPLETED'
    assert payload['result']['delivery_video']['filename'] == 'good.mp4'
    assert payload['detail']['render_checkpoint']['recovery_generation'] == g2
    assert not commit(job_id,'B',g2,'replayed.mp4','gs://dummy/replayed.mp4')
    print('PASS: one atomic commit; replay rejected')
    release(job_id,'B')
    assert acquire(job_id,'C')
    assert generation(job_id,'C') == g2 + 1
    assert not commit(job_id,'C',g2+1,'third.mp4','gs://dummy/third.mp4')
    print('PASS: generation monotonic; completed job immutable to recovery')
    print('ALL 5 FIRESTORE FENCING CHECKS PASSED')
finally:
    job_ref.delete()
    lock_ref.delete()
