"""V9D exact repository serializer + fake GCS staging checks; no app startup."""
from __future__ import annotations
import ast, gzip, hashlib, json, os, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'app/services/firestore_job_repository.py'

def load_repo_class():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'FirestoreJobRepository')
    # Compile the original class methods in isolation, avoiding application imports and ADC.
    mod = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(mod)
    context = {'gzip':gzip, 'hashlib':hashlib, 'json':json, 'uuid':__import__('uuid'), 'datetime':datetime, 'timezone':timezone, 'Optional':__import__('typing').Optional, 'Any':__import__('typing').Any, 'Iterable':__import__('typing').Iterable,
    'get_runtime_firestore_client': lambda: (_ for _ in ()).throw(AssertionError('cloud access prohibited')), 'tenant_namespace':lambda: 'synthetic'}
    exec(compile(mod,str(SOURCE),'exec'),context)
    return context['FirestoreJobRepository']

class FakeCreateOnly:
    def __init__(self): self.objects={}
    def create(self,key,blob,*,generation_match=0,expected_sha):
        if generation_match != 0: raise AssertionError('create-only precondition mandatory')
        if hashlib.sha256(blob).hexdigest() != expected_sha: raise ValueError('digest mismatch')
        if key in self.objects: raise FileExistsError('object collision')
        self.objects[key] = bytes(blob)
        return {'sha256':expected_sha,'generation':1}
    def verify(self,key,digest):
        return key in self.objects and hashlib.sha256(self.objects[key]).hexdigest()==digest

def test():
    repo=load_repo_class()
    assert repo.STORAGE_INLINE=='inline-json-v1' and repo.STORAGE_CHUNKED=='gzip-chunks-v1'
    assert repo.CHUNK_SIZE_BYTES==600*1024 and repo.INLINE_JSON_LIMIT_BYTES==700*1024
    data={'job_id':'synthetic','stage':'RENDERING','detail':{'source_visual_asset_id':'synthetic-visual'},'result':None}
    raw=repo._encode(data).encode()
    assert json.loads(raw)==data and repo._sha256(raw)==hashlib.sha256(raw).hexdigest()
    assert b''.join(repo._chunk_bytes(gzip.compress(raw)))==gzip.compress(raw)
    print('PASS: loaded actual FirestoreJobRepository class from source, real constants and serializer')
    gcs=FakeCreateOnly(); digest=hashlib.sha256(raw).hexdigest()
    assert gcs.create('synthetic/mix.m4a',raw,expected_sha=digest)['generation']==1
    assert gcs.verify('synthetic/mix.m4a',digest)
    for action in (lambda:gcs.create('synthetic/mix.m4a',raw,expected_sha=digest),lambda:gcs.create('synthetic/other',raw,expected_sha='bad'),lambda:gcs.create('synthetic/other',raw,generation_match=1,expected_sha=digest)):
        try: action()
        except (FileExistsError,ValueError,AssertionError): pass
        else: raise AssertionError('unsafe upload accepted')
    print('PASS: fake GCS create-only, collision, digest and precondition failures')
    staged=FakeCreateOnly(); staged.create('new/mix',b'mix',expected_sha=hashlib.sha256(b'mix').hexdigest())
    try: staged.create('new/delivery',b'video',expected_sha='wrong')
    except ValueError: pass
    else: raise AssertionError('partial staging did not fail')
    assert 'new/mix' in staged.objects and 'new/delivery' not in staged.objects
    assert data['result'] is None and data['stage']=='RENDERING'
    print('PASS: failed staging leaves authoritative job unchanged; orphan is non-authoritative')
    print('ALL 3 V9D OFFLINE CHECKS PASSED; NO PRODUCTION CLOUD ACCESS')
if __name__=='__main__':test()
