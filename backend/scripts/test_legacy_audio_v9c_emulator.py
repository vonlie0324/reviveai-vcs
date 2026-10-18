"""V9C: ISOLATED Firestore emulator tests, never production. No application imports.

Run from backend root with FIRESTORE_EMULATOR_HOST=127.0.0.1:8085:
  python scripts/test_legacy_audio_v9c_emulator.py
"""
from __future__ import annotations
import gzip
import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone

PROJECT = 'reviveai-local-test'
DB = '(default)'
ROOT = 'v9c-isolated-tests'
JOB_ID = 'synthetic-audio-v9c'
MODE_INLINE = 'inline-json-v1'
MODE_CHUNKED = 'gzip-chunks-v1'


def ensure_isolated():
    host = os.environ.get('FIRESTORE_EMULATOR_HOST', '')
    if host not in {'127.0.0.1:8085', 'localhost:8085', '[::1]:8085'}:
        raise SystemExit('BLOCKED: set FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 (loopback-only emulator)')
    if os.environ.get('GOOGLE_CLOUD_PROJECT') not in (None, '', PROJECT):
        raise SystemExit('BLOCKED: GOOGLE_CLOUD_PROJECT must be unset or reviveai-local-test')


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Conflict(Exception):
    pass


def job_fixture(size=0):
    return {'job_id': JOB_ID, 'stage': 'RENDERING', 'result': None,
            'detail': {'source_visual_asset_id': 'visual-synthetic', 'narration_stems': [{'shot_number': n} for n in range(1, 5)]},
            'padding': 'x' * size, 'progress_total': 5, 'progress_current': 4,
            'assembly_job_id': 'assembly-synthetic', 'production_brief_job_id': 'brief-synthetic'}


def result_fixture():
    return {'review_status': 'NEEDS_REVIEW', 'delivery_video': {'asset_id': 'delivery-synthetic'},
            'audio_mix': {'asset_id': 'mix-synthetic'}, 'subtitles': None,
            'effective_music_source': 'REVIVEAI', 'effective_music_preset': 'CINEMATIC_AMBIENT'}


def make_manifest(job, mode, generation=None):
    raw = encode(job)
    base = {'schema_version': 2, 'storage_mode': mode, 'payload_size_bytes': len(raw),
            'payload_sha256': digest(raw), 'persisted_at': datetime.now(timezone.utc)}
    if mode == MODE_INLINE:
        return dict(base, payload_json=raw.decode()), []
    compressed = gzip.compress(raw, compresslevel=6)
    gen = generation or uuid.uuid4().hex
    chunks = [compressed[i:i+600*1024] for i in range(0, len(compressed), 600*1024)]
    return dict(base, compression='gzip', chunk_generation=gen, chunk_count=len(chunks),
                compressed_size_bytes=len(compressed), compressed_sha256=digest(compressed)), chunks


def write_fixture(ref, job, mode):
    manifest, chunks = make_manifest(job, mode)
    for i, chunk in enumerate(chunks):
        ref.collection('_payload_chunks').document(f"{manifest['chunk_generation']}_{i:06d}").set({
            'schema_version': 2, 'chunk_generation': manifest['chunk_generation'],
            'chunk_index': i, 'payload_bytes': chunk})
    ref.set(manifest)


def read_job(ref):
    snap = ref.get()
    if not snap.exists: raise Conflict('missing parent')
    return decode_manifest(ref, snap.to_dict())


def decode_manifest(ref, manifest):
    if manifest.get('storage_mode') == MODE_INLINE:
        raw = manifest['payload_json'].encode()
    elif manifest.get('storage_mode') == MODE_CHUNKED:
        gen = manifest['chunk_generation']
        chunks = []
        for i in range(manifest['chunk_count']):
            child = ref.collection('_payload_chunks').document(f'{gen}_{i:06d}').get()
            if not child.exists: raise Conflict('missing chunk')
            chunks.append(bytes(child.get('payload_bytes')))
        compressed = b''.join(chunks)
        if digest(compressed) != manifest['compressed_sha256']: raise Conflict('compressed hash mismatch')
        raw = gzip.decompress(compressed)
    else: raise Conflict('unknown storage mode')
    if digest(raw) != manifest['payload_sha256']: raise Conflict('payload hash mismatch')
    return json.loads(raw)


def stage_candidate_chunks(ref, manifest, chunks):
    """Immutable new chunk generation, staged before atomic parent switch."""
    for i, chunk in enumerate(chunks):
        ref.collection('_payload_chunks').document(f"{manifest['chunk_generation']}_{i:06d}").create({
            'schema_version': 2, 'chunk_generation': manifest['chunk_generation'],
            'chunk_index': i, 'payload_bytes': chunk})


def guarded_finalize(client, ref, lock_ref, *, owner, initial_parent, new_manifest, expected_generation):
    """Transaction uses only parent+lease reads; payload/chunks validated beforehand.

    This is an emulator-only implementation, NOT wired to production application.
    """
    from google.cloud import firestore
    from google.api_core.exceptions import Aborted
    initial_fingerprint = digest(encode({k: v for k, v in initial_parent.items() if k != 'persisted_at'}))
    tx = client.transaction()

    @firestore.transactional
    def atomic(transaction):
        parent_snap = ref.get(transaction=transaction)
        lock_snap = lock_ref.get(transaction=transaction)
        if not parent_snap.exists or not lock_snap.exists: raise Conflict('missing parent/lease')
        parent = parent_snap.to_dict()
        lease = lock_snap.to_dict()
        if digest(encode({k: v for k, v in parent.items() if k != 'persisted_at'})) != initial_fingerprint:
            raise Conflict('stale parent version')
        if lease.get('owner') != owner or lease.get('generation') != expected_generation:
            raise Conflict('lost ownership or generation')
        expires = lease.get('expires_at')
        if expires is None or expires <= datetime.now(timezone.utc):
            raise Conflict('lease expired')
        if lease.get('job_id') != JOB_ID: raise Conflict('incorrect job lease')
        # No reads occur after writes inside the transaction.
        transaction.set(ref, new_manifest)
        transaction.update(lock_ref, {'finalized_at': datetime.now(timezone.utc), 'state': 'COMPLETED'})
        return True
    try:
        return atomic(tx)
    except Aborted as exc:
        raise Conflict('transaction aborted') from exc


def prepare_candidate(ref, old_job, mode):
    assert old_job['job_id'] == JOB_ID and old_job['stage'] == 'RENDERING' and old_job['result'] is None
    candidate = dict(old_job)
    candidate['result'] = result_fixture()
    candidate['stage'] = 'COMPLETED'
    candidate['progress_current'] = candidate['progress_total']
    candidate['detail'] = {**candidate['detail'], 'render_checkpoint': {'version': 1, 'state': 'COMPLETED', 'source': 'SYNTHETIC_V9C'}}
    if mode == MODE_CHUNKED: candidate['padding'] = uuid.uuid4().hex + old_job['padding']
    manifest, chunks = make_manifest(candidate, mode)
    return manifest, chunks


def test_case(client, namespace, mode):
    ref = client.collection(ROOT).document(namespace).collection('audio_finishing_jobs').document(JOB_ID)
    lock = client.collection(ROOT).document(namespace).collection('recovery_locks').document(JOB_ID)
    job = job_fixture(size=850_000 if mode == MODE_CHUNKED else 10)
    write_fixture(ref, job, mode)
    original_manifest = ref.get().to_dict()
    assert read_job(ref) == job
    lease_owner = uuid.uuid4().hex
    lease_gen = 1
    lock.set({'job_id': JOB_ID, 'owner': lease_owner, 'generation': lease_gen,
              'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10), 'state': 'ACTIVE'})
    new_manifest, chunks = prepare_candidate(ref, job, mode)
    # Simulate interruption after staging only. Parent must remain unchanged/readable.
    if chunks: stage_candidate_chunks(ref, new_manifest, chunks)
    assert read_job(ref) == job
    print(f'PASS: {mode} staged candidate does not change visible job')
    for bad_owner, bad_gen in [('other-owner', lease_gen), (lease_owner, lease_gen + 1)]:
        try: guarded_finalize(client, ref, lock, owner=bad_owner, initial_parent=original_manifest, new_manifest=new_manifest, expected_generation=bad_gen)
        except Conflict: pass
        else: raise AssertionError('wrong-owner/generation accepted')
    assert read_job(ref) == job
    print(f'PASS: {mode} wrong owner / generation rejected')
    guarded_finalize(client, ref, lock, owner=lease_owner, initial_parent=original_manifest,
                     new_manifest=new_manifest, expected_generation=lease_gen)
    final = read_job(ref)
    assert final['stage'] == 'COMPLETED' and final['result']['review_status'] == 'NEEDS_REVIEW'
    assert final['detail']['source_visual_asset_id'] == 'visual-synthetic'
    print(f'PASS: {mode} transaction finalized with original lineage and NEEDS_REVIEW')
    try: guarded_finalize(client, ref, lock, owner=lease_owner, initial_parent=original_manifest, new_manifest=new_manifest, expected_generation=lease_gen)
    except Conflict: pass
    else: raise AssertionError('duplicate commit accepted')
    assert read_job(ref) == final
    print(f'PASS: {mode} duplicate commit rejected')
    if mode == MODE_CHUNKED:
        assert decode_manifest(ref, original_manifest) == job
        print('PASS: chunked previous generation still readable after switch')


def main():
    ensure_isolated()
    from google.cloud import firestore
    client = firestore.Client(project=PROJECT, database=DB)
    namespace = 'v9c-' + uuid.uuid4().hex
    print('ISOLATED EMULATOR NAMESPACE:', namespace)
    test_case(client, namespace + '-inline', MODE_INLINE)
    test_case(client, namespace + '-chunked', MODE_CHUNKED)
    print('ALL 9 V9C FIRESTORE EMULATOR CHECKS PASSED')
    print('NO PRODUCTION CLIENT; NO APPLICATION IMPORTS; NO GCS; NO PUBLISHING')

if __name__ == '__main__': main()
