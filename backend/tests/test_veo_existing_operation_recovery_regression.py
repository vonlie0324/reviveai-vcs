"""Offline structural guards for the no-duplicate Veo adoption path."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'services'


def test_adoption_does_not_submit_new_generation():
    source = (ROOT / 'veo_existing_operation_adoption.py').read_text()
    tree = ast.parse(source)
    assert 'generate_videos(' not in source
    assert 'operations.get(' in source
    assert 'VEO_OUTCOME_UNKNOWN' in source
    assert 'VEO_OUTPUT_LINEAGE_MISMATCH' in source
    assert 'costBasis' in source
    assert any(isinstance(n, ast.FunctionDef) and n.name == 'adopt_existing_veo_operation' for n in ast.walk(tree))


def test_recovery_occurs_before_new_media_studio_claims():
    source = (ROOT / 'media_studio_job_service.py').read_text()
    tree = ast.parse(source)
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))]
    by_name = {n.name: n for n in functions}
    for func_name in ('generate_video_clips_for_job', 'regenerate_video_clip_for_job'):
        func = by_name[func_name]
        snippet = ast.get_source_segment(source, func)
        assert snippet.index('recover_existing_veo_clip(') < snippet.index('store.claim_video_generation(')


def test_capture_uses_configured_runtime_database():
    source = (ROOT / 'veo_operation_capture_service.py').read_text()
    assert 'get_runtime_firestore_client()' in source
    assert 'self.db = firestore.Client()' not in source
