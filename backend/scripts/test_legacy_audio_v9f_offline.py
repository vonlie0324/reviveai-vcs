"""V9F against ACTUAL CloudStorageService with injected fake GCS client.
No application startup, no ADC, no Firestore or production GCS.
"""
from __future__ import annotations
import ast, hashlib, tempfile
from pathlib import Path
from types import ModuleType
from legacy_audio_v9f_gcs_adapter import stage_create_only, StagingConflict

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'app/services/cloud_storage_service.py'

# Load the genuine class AST, stripping application imports to prevent ADC.
def load_storage_class():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'CloudStorageService')
    mod = ast.Module(body=[cls], type_ignores=[])
    ns = {'Path': Path, 'timedelta': __import__('datetime').timedelta, 'parse_gcs_uri':lambda s:{'bucket':'fake-bucket','prefix':'isolation'}}
    exec(compile(ast.fix_missing_locations(mod), str(SOURCE), 'exec'), ns)
    return ns['CloudStorageService']

class PreconditionFailed(Exception):
    code = 412
class BadNetwork(Exception):
    pass
class FakeBlob:
    def __init__(self, backing, key): self.backing, self.key = backing,key
    def upload_from_filename(self, path, *, content_type=None, if_generation_match=None):
        self.backing.calls.append((self.key,if_generation_match))
        if if_generation_match != 0: raise AssertionError('non-create-only upload')
        if self.backing.fail_network: raise BadNetwork('synthetic connection drop')
        if self.key in self.backing.objects: raise PreconditionFailed('existing')
        self.backing.objects[self.key] = Path(path).read_bytes()
    def download_as_bytes(self): return self.backing.objects[self.key]
class FakeBucket:
    def __init__(self, backing):self.backing=backing
    def blob(self, name):return FakeBlob(self.backing,name)
class FakeClient:
    def __init__(self): self.objects={}; self.calls=[]; self.fail_network=False
    def bucket(self, name):
        assert name=='fake-bucket'
        return FakeBucket(self)

def rejects(fn):
    try: fn()
    except (StagingConflict, BadNetwork): return
    raise AssertionError('expected failure')

def main():
    storage_cls=load_storage_class()
    cloud=FakeClient()
    store=storage_cls('gs://fake-bucket/isolation', client=cloud)
    with tempfile.TemporaryDirectory(prefix='revive_v9f_') as d:
        audio=Path(d)/'mix.m4a'; audio.write_bytes(b'mock verified mix')
        video=Path(d)/'video.mp4';video.write_bytes(b'mock verified delivery')
        sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        key='isolated-intent/mix.m4a'
        assert stage_create_only(store,audio,key,sha(audio),content_type='audio/mp4')=='CREATED'
        assert cloud.calls[-1][1] == 0
        print('PASS: actual CloudStorageService-compatible blob API uses if_generation_match=0')
        assert stage_create_only(store,audio,key,sha(audio),content_type='audio/mp4')=='REUSED_VERIFIED'
        assert len(cloud.objects)==1
        print('PASS: 412 collision reused only after byte-level SHA-256 verification')
        cloud.objects[key]=b'altered remotely'
        rejects(lambda:stage_create_only(store,audio,key,sha(audio),content_type='audio/mp4'))
        print('PASS: remote collision with wrong bytes rejects finalization')
        cloud.objects[key]=audio.read_bytes()
        rejects(lambda:stage_create_only(store,audio,key,'0'*64,content_type='audio/mp4'))
        rejects(lambda:stage_create_only(store,audio,'../unsafe',sha(audio),content_type='audio/mp4'))
        print('PASS: local tampering and unsafe paths rejected')
        cloud.fail_network=True
        rejects(lambda:stage_create_only(store,video,'isolated-intent/delivery.mp4',sha(video),content_type='video/mp4'))
        assert 'isolated-intent/delivery.mp4' not in cloud.objects
        cloud.fail_network=False
        assert stage_create_only(store,video,'isolated-intent/delivery.mp4',sha(video),content_type='video/mp4')=='CREATED'
        assert len(cloud.objects)==2
        print('PASS: upload interruption does not create unverified artifact; retry succeeds')
    print('ALL 5 V9F OFFLINE STORAGE CONTRACT CHECKS PASSED')
    print('FAKE CLOUD ONLY; NO ADC; NO FIRESTORE; NO GCS WRITES; NO COMMIT')
if __name__=='__main__':main()
