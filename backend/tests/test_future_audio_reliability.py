"""Safe local regression checks; no application startup, network, or credentials."""
import ast
import hashlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / 'app/services/audio_finishing_job_service.py'
SUPERVISOR = ROOT / 'app/services/autopilot_supervisor_service.py'
STORE = ROOT / 'app/services/runtime_artifact_store.py'

class FakePreconditionFailed(Exception): pass
class Blob:
    def __init__(self, objects, name):
        self.objects, self.name = objects, name
        self.metadata = None
        self.size = None
        self.generation = None
    def upload_from_filename(self, path, *, content_type=None, if_generation_match=None):
        assert if_generation_match == 0
        if self.name in self.objects: raise FakePreconditionFailed()
        content = Path(path).read_bytes()
        self.objects[self.name] = (content, dict(self.metadata), 1)
    def reload(self):
        content, self.metadata, self.generation = self.objects[self.name]
        self.size = len(content)
    def download_to_file(self, file, *, if_generation_match=None):
        content, _, gen = self.objects[self.name]
        assert gen == if_generation_match
        file.write(content)
class Bucket:
    def __init__(self, objects):self.objects = objects
    def blob(self, name): return Blob(self.objects, name)
class Client:
    def __init__(self, objects): self.objects=objects
    def bucket(self, name):return Bucket(self.objects)

class Checks(unittest.TestCase):
    def test_no_uncheckpointed_rendering_save(self):
        src=AUDIO.read_text()
        fn=src.split('def render_audio_finishing(', 1)[1].split('def _mux_recovery_lock_ref',1)[0]
        self.assertNotIn('job.message = "Muxing the approved visual master with the unified audio mix"\n        store.save(job)',fn)
        self.assertIn('"state": "MUX_READY"', fn)
        self.assertIn('store.save(job)\n        _mux_delivery',fn)
    def test_no_historical_watchdog_activation(self):
        src=SUPERVISOR.read_text()
        self.assertIn('REVIVEAI_FUTURE_AUDIO_RECOVERY_FROM',src)
        self.assertIn('future_eligible = cutoff is not None and created >= cutoff',src)
        self.assertIn('watchdog_enabled and future_eligible',src)
    def test_create_only_remote_integrity_and_conflict(self):
        # Load the actual method AST without importing live backend app modules.
        tree=ast.parse(STORE.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='RuntimeArtifactStore')
        node=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='upload_file_create_only')
        code=compile(ast.Module(body=[node],type_ignores=[]),str(STORE),'exec')
        import sys
        fake_api=types.ModuleType('google.api_core.exceptions')
        fake_api.PreconditionFailed=FakePreconditionFailed
        fake_core=types.ModuleType('google.api_core');fake_core.exceptions=fake_api
        fake_google=types.ModuleType('google');fake_google.api_core=fake_core
        records={}
        ns={'Path':Path,'Optional':__import__('typing').Optional,'hashlib':hashlib,
            'get_storage_client':lambda:Client(records)}
        with patch.dict(sys.modules,{'google':fake_google,'google.api_core':fake_core,'google.api_core.exceptions':fake_api}):
            exec(code,ns)
            inst=types.SimpleNamespace(enabled=True,bucket_name='fake',category='audio_finishing',
                 _object_name=lambda owner_id,relative_path:'test/'+owner_id+'/'+relative_path,
                 _sha256_file=lambda path:hashlib.sha256(path.read_bytes()).hexdigest())
            with tempfile.TemporaryDirectory() as d:
                f=Path(d)/'mix.m4a'; f.write_bytes(b'safe audio')
                uri=ns['upload_file_create_only'](inst,f,owner_id='synthetic',relative_path='assets/mix.m4a')
                self.assertEqual(uri,'gs://fake/test/synthetic/assets/mix.m4a')
                self.assertEqual(ns['upload_file_create_only'](inst,f,owner_id='synthetic',relative_path='assets/mix.m4a'),uri)
                f.write_bytes(b'changed audio')
                with self.assertRaises(RuntimeError):
                    ns['upload_file_create_only'](inst,f,owner_id='synthetic',relative_path='assets/mix.m4a')
                self.assertEqual(records['test/synthetic/assets/mix.m4a'][0], b'safe audio')

if __name__ == '__main__':
    unittest.main(verbosity=2)
