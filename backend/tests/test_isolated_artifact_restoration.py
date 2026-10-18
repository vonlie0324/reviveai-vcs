"""No app imports or live cloud access: exercises actual artifact-store and mux code via AST."""
import ast
import copy
import hashlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_isolated_audio_mux_recovery import environment as recovery_environment, Stage

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_SOURCE = ROOT / 'app/services/runtime_artifact_store.py'

class FakeBlob:
    def __init__(self, backend, bucket, name):
        self.backend, self.bucket, self.name = backend, bucket, name
        self.metadata = {}
        self.size = None
        self.generation = 1
    def exists(self):
        return (self.bucket, self.name) in self.backend.data
    def reload(self):
        if self.exists():
            self.size = len(self.backend.data[self.bucket, self.name])
            self.metadata = dict(self.backend.meta.get((self.bucket, self.name), {}))
    def upload_from_filename(self, path, content_type=None, if_generation_match=None):
        self.backend.data[self.bucket, self.name] = Path(path).read_bytes()
        self.size = len(self.backend.data[self.bucket, self.name])
        self.generation = 1
        self.backend.meta[self.bucket, self.name] = dict(self.metadata)
    def download_to_file(self, out, if_generation_match=None):
        out.write(self.backend.data[self.bucket, self.name])
    def download_to_filename(self, path):
        Path(path).write_bytes(self.backend.data[self.bucket, self.name])
    def patch(self):
        self.backend.meta[self.bucket, self.name] = dict(self.metadata)

class FakeBucket:
    def __init__(self, backend, name): self.backend, self.name = backend, name
    def blob(self, name): return FakeBlob(self.backend, self.name, name)

class FakeGCS:
    def __init__(self):
        self.data = {}
        self.meta = {}
    def bucket(self, name): return FakeBucket(self, name)


def create_runtime_store(gcs, category='audio_finishing'):
    # Cloud SDK is optional in isolated AST tests; do not access credentials.
    import sys, types
    try:
        from google.api_core.exceptions import PreconditionFailed
    except ImportError:
        api_core = sys.modules.setdefault('google.api_core', types.ModuleType('google.api_core'))
        exceptions = sys.modules.setdefault('google.api_core.exceptions', types.ModuleType('google.api_core.exceptions'))
        exceptions.PreconditionFailed = type('PreconditionFailed', (Exception,), {})
        api_core.exceptions = exceptions

    tree = ast.parse(ARTIFACT_SOURCE.read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RuntimeArtifactStore']
    assert len(nodes) == 1
    import hashlib
    import logging
    from pathlib import Path, PurePosixPath
    from threading import Lock
    ns = {'Path': Path, 'PurePosixPath': PurePosixPath, 'Lock': Lock,
          'hashlib': hashlib, 'logger': logging.getLogger('fake-gcs'),
          'Optional': __import__('typing').Optional,
          'Settings': object, 'get_settings': lambda: None,
          'tenant_namespace': lambda: 'isolated-tenant',
          'get_storage_client': lambda: gcs,
          'parse_gcs_uri': lambda uri: {'bucket': uri[5:].split('/',1)[0],
                                        'prefix': uri[5:].split('/',1)[1] if '/' in uri[5:] else ''}}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ARTIFACT_SOURCE), 'exec'), ns)
    return ns['RuntimeArtifactStore'](category, settings=SimpleNamespace(effective_runtime_asset_gcs_uri='gs://fake-only/test'))

class RestoringAudioStore:
    def __init__(self, base, artifact):
        self.base = base
        self._artifacts = artifact
        self._jobs = base._jobs
        self._lock = base._lock
        self.job = base.job
    def get(self, job_id): return self.base.get(job_id)
    def assets_dir(self, job_id): return self.base.assets_dir(job_id)
    def asset_path(self, job_id, asset_id):
        asset = next(a for a in (self.base.job.result.audio_mix, self.base.job.result.delivery_video) if a.asset_id == asset_id)
        path = self.base.assets_dir(job_id) / asset.filename
        restored = self._artifacts.ensure_local(path, owner_id=job_id, relative_path='assets/'+asset.filename, gcs_uri=asset.gcs_uri)
        if not restored.is_file(): raise FileNotFoundError(path)
        return restored, asset.mime_type

class RestoringAssemblyStore:
    def __init__(self, base, artifact, asset_uri):
        self.base, self.artifact, self.uri = base, artifact, asset_uri
    def get(self, job_id): return self.base.get(job_id)
    def asset_path(self, job_id, asset_id):
        path = self.base.visual
        restored = self.artifact.ensure_local(path, owner_id=job_id, relative_path='assets/visual.mp4', gcs_uri=self.uri)
        if not restored.is_file(): raise FileNotFoundError(path)
        return restored, 'video/mp4'

@pytest.fixture
def recovered_setup(recovery_environment):
    base_store, ns, visual, mix = recovery_environment
    fake = FakeGCS()
    artifact = create_runtime_store(fake)
    mix_uri = artifact.upload_file(mix, owner_id='test-audio', relative_path='assets/mix-test.m4a', content_type='audio/mp4')
    visual_uri = artifact.upload_file(visual, owner_id='test-assembly', relative_path='assets/visual.mp4', content_type='video/mp4')
    assert mix_uri and visual_uri
    base_store.job.result.audio_mix.gcs_uri = mix_uri
    original_assembly = ns['final_assembly_job_store']
    restoring = RestoringAudioStore(base_store, artifact)
    ns['audio_finishing_job_store'] = restoring
    ns['final_assembly_job_store'] = RestoringAssemblyStore(original_assembly, artifact, visual_uri)
    return base_store, ns, visual, mix, fake, artifact

def test_restart_restores_mix_and_visual_then_muxes(recovered_setup):
    store, ns, visual, mix, fake, artifact = recovered_setup
    original_hashes = (hashlib.sha256(visual.read_bytes()).hexdigest(), hashlib.sha256(mix.read_bytes()).hexdigest())
    visual.unlink(); mix.unlink()
    assert not visual.exists() and not mix.exists()
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED
    assert store.commits and visual.is_file() and mix.is_file()
    assert hashlib.sha256(visual.read_bytes()).hexdigest() == original_hashes[0]
    assert hashlib.sha256(mix.read_bytes()).hexdigest() == original_hashes[1]
    destination = store.assets_dir('test-audio') / store.job.result.delivery_video.filename
    assert ns['_probe_mux_media'](destination, require_video=True, require_audio=True)
    assert store.job.result.delivery_video.gcs_uri
    assert any(name.endswith(destination.name) for _,name in fake.data)

def test_missing_durable_mix_refuses_commit(recovered_setup):
    store, ns, visual, mix, fake, artifact = recovered_setup
    mix.unlink()
    fake.data.clear()
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert not store.commits

def test_upload_failure_prevents_completion(recovered_setup):
    store, ns, visual, mix, fake, artifact = recovered_setup
    def fail_upload(*args, **kwargs): raise ConnectionError('Simulated disconnected storage')
    artifact.upload_file_create_only = fail_upload
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert not store.commits

def test_absent_storage_service_prevents_completion(recovered_setup):
    store, ns, visual, mix, fake, artifact = recovered_setup
    artifact.upload_file_create_only = lambda *args, **kwargs: None
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert not store.commits

def test_failed_remote_restore_does_not_create_valid_local_mix(recovered_setup):
    store, ns, visual, mix, fake, artifact = recovered_setup
    mix.unlink()
    fake.data.pop(('fake-only', 'test/tenants/isolated-tenant/audio_finishing/test-audio/assets/mix-test.m4a'))
    ns['resume_audio_final_mux']('test-audio', object())
    assert not mix.exists() and not store.commits
