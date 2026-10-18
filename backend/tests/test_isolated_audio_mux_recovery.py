"""Offline regression tests of ACTUAL production function bodies extracted from source.

Do not import app.*: its module-level services may initialize production clients.
No Firestore, GCS, Cloud Tasks, YouTube or paid-provider interactions occur.
"""
import ast
import copy
import logging
import json
import uuid
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SRC = Path(__file__).resolve().parents[1] / 'app' / 'services' / 'audio_finishing_job_service.py'


class Stage:
    RENDERING = 'RENDERING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'


class FinishingError(RuntimeError):
    pass


class ReviewStatus:
    APPROVED = 'APPROVED'


class DummyStore:
    def __init__(self, root, job):
        self.root = root
        self.job = copy.deepcopy(job)
        self.failures = []
        self.saves = 0
        self.commits = []
        self._artifacts = SimpleNamespace(
            upload_file=lambda path, **kw: 'gs://isolated-test/' + Path(path).name,
            upload_file_create_only=lambda path, **kw: 'gs://isolated-test/' + Path(path).name,
        )
        self._lock = __import__('threading').Lock()
        self._jobs = {}

    def get(self, job_id):
        assert job_id == self.job.job_id
        return copy.deepcopy(self.job)

    def save(self, job):
        self.job = copy.deepcopy(job)
        self.saves += 1

    def fail(self, job_id, message):
        assert job_id == self.job.job_id
        self.job.stage = Stage.FAILED
        self.job.error = message
        self.failures.append(message)

    def assets_dir(self, job_id):
        p = self.root / 'audio' / job_id / 'assets'
        p.mkdir(parents=True, exist_ok=True)
        return p

    def asset_path(self, job_id, asset_id):
        for asset in (self.job.result.audio_mix, self.job.result.delivery_video):
            if asset.asset_id == asset_id:
                path = self.assets_dir(job_id) / asset.filename
                if not path.is_file():
                    raise FileNotFoundError(f'Missing checkpoint asset: {path}')
                return path, asset.mime_type
        raise KeyError(asset_id)


class DummyAssemblyStore:
    def __init__(self, assembly, visual):
        self.assembly = assembly
        self.visual = visual

    def get(self, job_id):
        assert job_id == self.assembly.job_id
        return copy.deepcopy(self.assembly)

    def asset_path(self, job_id, asset_id):
        assert job_id == self.assembly.job_id
        assert asset_id == self.assembly.result.final_video.asset_id
        return self.visual, 'video/mp4'


def function_namespace(store, assembly_store, ffmpeg):
    """Compile only the named production functions with no package imports/side effects."""
    tree = ast.parse(SRC.read_text(encoding='utf-8'), filename=str(SRC))
    requested = {'_run', '_mux_delivery', '_probe_mux_media', 'resume_audio_final_mux'}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in requested]
    assert {node.name for node in nodes} == requested, 'Source structure changed; do not silently test a mock implementation'
    unit = ast.Module(body=nodes, type_ignores=[])
    ns = {
        'subprocess': subprocess, 'Path': Path, 'datetime': datetime, 'timezone': timezone,
        'shutil': shutil, 'json': json, 'uuid4': uuid.uuid4,
        'AudioFinishingError': FinishingError, 'AudioFinishingJobStage': Stage,
        'FinalAssemblyReviewStatus': ReviewStatus,
        'audio_finishing_job_store': store,
        'final_assembly_job_store': assembly_store,
        '_ffmpeg_executable': lambda: ffmpeg,
        'logger': logging.getLogger('isolated-mux-test'), 'Settings': object,
        '_acquire_mux_recovery_claim': lambda job_id, owner: True,
        '_owns_mux_recovery_claim': lambda job_id, owner: True,
        '_release_mux_recovery_claim': lambda job_id, owner: None,
        '_mux_recovery_claim_generation': lambda job_id, owner: 1,
        '_commit_mux_recovery_fenced': lambda job_id, owner, generation, filename, uri: commit_local(job_id, owner, generation, filename, uri),
    }
    def commit_local(job_id, owner, generation, filename, uri):
        current = store.job
        if current.stage != Stage.RENDERING:
            return False
        current.stage = Stage.COMPLETED
        current.progress_current = current.progress_total
        current.result.delivery_video.filename = filename
        current.result.delivery_video.gcs_uri = uri
        current.detail['render_checkpoint']['state'] = 'COMPLETED'
        store.commits.append((owner, generation))
        return True
    exec(compile(unit, str(SRC), 'exec'), ns)
    return ns


def ffmpeg_command(ffmpeg, *args):
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', *args], check=True, capture_output=True)


@pytest.fixture
def environment(tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        pytest.skip('Install both FFmpeg and FFprobe before running real-media mux regression')
    visual = tmp_path / 'visual.mp4'
    ffmpeg_command(ffmpeg, '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:r=10:d=2', '-c:v', 'mpeg4', visual.as_posix())
    audio_dir = tmp_path / 'audio' / 'test-audio' / 'assets'
    audio_dir.mkdir(parents=True)
    mix = audio_dir / 'mix-test.m4a'
    ffmpeg_command(ffmpeg, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:a', 'aac', mix.as_posix())
    mix_asset = SimpleNamespace(asset_id='mix-test', filename=mix.name, mime_type='audio/mp4')
    delivery_asset = SimpleNamespace(asset_id='delivery-test', filename='delivery-test.mp4', mime_type='video/mp4')
    assembly = SimpleNamespace(job_id='test-assembly', result=SimpleNamespace(
        review_status=ReviewStatus.APPROVED,
        final_video=SimpleNamespace(asset_id='visual-test')))
    job = SimpleNamespace(job_id='test-audio', assembly_job_id=assembly.job_id,
        stage=Stage.RENDERING, version_number=1, progress_current=4, progress_total=5,
        detail={'source_visual_asset_id': 'visual-test', 'render_checkpoint': {
            'version': 1, 'state': 'MUX_READY', 'delivery_asset_id': 'delivery-test', 'mix_asset_id': 'mix-test'}},
        result=SimpleNamespace(audio_mix=mix_asset, delivery_video=delivery_asset), error=None, message='Rendering')
    store = DummyStore(tmp_path, job)
    ns = function_namespace(store, DummyAssemblyStore(assembly, visual), ffmpeg)
    return store, ns, visual, mix


def test_completed_mux_from_checkpoint_without_provider_calls(environment):
    store, ns, visual, mix = environment
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED, store.job.error
    assert store.job.progress_current == store.job.progress_total
    assert store.job.detail['render_checkpoint']['state'] == 'COMPLETED'
    delivery = store.assets_dir('test-audio') / store.job.result.delivery_video.filename
    assert delivery.stat().st_size > 1024
    assert visual.exists() and mix.exists()
    assert store.failures == []


def test_missing_durable_checkpoint_fails_closed(environment):
    store, ns, _, _ = environment
    del store.job.detail['render_checkpoint']
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert not store.commits


def test_wrong_visual_lineage_fails_closed(environment):
    store, ns, _, _ = environment
    store.job.detail['source_visual_asset_id'] = 'wrong-visual'
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert not store.commits


def test_missing_mix_does_not_regenerate_provider_audio(environment):
    store, ns, _, mix = environment
    mix.unlink()
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert store.saves == 0
    assert not store.commits


def test_completed_job_is_not_replayed(environment):
    store, ns, _, _ = environment
    store.job.stage = Stage.COMPLETED
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED
    assert store.saves == 0
    assert not store.commits


def test_existing_valid_delivery_is_preserved(environment):
    store, ns, _, _ = environment
    output = store.assets_dir('test-audio') / 'delivery-test.mp4'
    ffmpeg = shutil.which('ffmpeg')
    ffmpeg_command(ffmpeg, '-i', str(store.root / 'visual.mp4'), '-i',
        str(store.assets_dir('test-audio') / 'mix-test.m4a'),
        '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-c:a', 'aac', output.as_posix())
    before = output.read_bytes()
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED
    assert output.read_bytes() == before
    assert store.job.result.delivery_video.filename != output.name


def test_corrupt_existing_delivery_is_remuxed(environment):
    store, ns, _, _ = environment
    output = store.assets_dir('test-audio') / 'delivery-test.mp4'
    output.write_bytes(b'x' * 4096)
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED
    assert ns['_probe_mux_media'](store.assets_dir('test-audio') / store.job.result.delivery_video.filename, require_video=True, require_audio=True)
    assert output.read_bytes() == b'x' * 4096


def test_existing_video_only_delivery_is_remuxed(environment):
    store, ns, visual, _ = environment
    output = store.assets_dir('test-audio') / 'delivery-test.mp4'
    output.write_bytes(visual.read_bytes())
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.COMPLETED
    assert ns['_probe_mux_media'](store.assets_dir('test-audio') / store.job.result.delivery_video.filename, require_video=True, require_audio=True)


def test_competing_claim_never_writes(environment):
    store, ns, _, _ = environment
    ns['_acquire_mux_recovery_claim'] = lambda job_id, owner: False
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.saves == 0 and store.failures == []
    assert not store.commits


def test_lost_claim_never_commits(environment):
    store, ns, _, _ = environment
    ns['_owns_mux_recovery_claim'] = lambda job_id, owner: False
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.saves == 0 and store.failures == []
    assert store.job.stage == Stage.RENDERING
    assert not store.commits


def test_missing_ffprobe_fails_closed(environment):
    store, ns, _, _ = environment
    ns['_probe_mux_media'] = lambda *args, **kwargs: False
    ns['resume_audio_final_mux']('test-audio', object())
    assert store.job.stage == Stage.RENDERING
    assert store.saves == 0
