"""Focused structural checks for all image submission entry points.

Runs without Google Cloud dependencies; cloud integration remains required.
"""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'services'


def _method(filename, method_name):
    module = ast.parse((ROOT / filename).read_text(encoding='utf-8'))
    for obj in ast.walk(module):
        if isinstance(obj, ast.AsyncFunctionDef) and obj.name == method_name:
            return obj
    raise AssertionError(f'Missing {method_name}')


def test_image_provider_request_is_budget_gated():
    node = _method('media_generation_service.py', '_generate_image')
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    names = [ast.unparse(n.func) for n in calls]
    assert 'budget.ensure_production_budget' in names
    assert 'budget.reserve' in names
    assert 'budget.complete' in names
    assert 'client.aio.models.generate_content' in names
    # Reservation must occur prior to provider submission in the same branch.
    source = ast.unparse(node)
    assert source.index('budget.reserve(') < source.index('client.aio.models.generate_content(')
    assert "existing_operation_requires_recovery" not in source  # leave claim semantics to ledger


def test_image_paths_forward_identity():
    for name in ('generate_reference', 'generate_keyframe'):
        node = _method('media_generation_service.py', name)
        image_calls = [n for n in ast.walk(node) if isinstance(n, ast.Call) and ast.unparse(n.func) == 'self._generate_image']
        assert len(image_calls) == 1
        kws = {kw.arg: ast.unparse(kw.value) for kw in image_calls[0].keywords}
        assert kws['production_id'] == 'source.production_brief_job_id'
        assert kws['channel_id'] == 'channel_id'


def test_job_entry_points_pass_channel_id():
    module = ast.parse((ROOT / 'media_studio_job_service.py').read_text(encoding='utf-8'))
    calls = [n for n in ast.walk(module) if isinstance(n, ast.Call) and ast.unparse(n.func) in ('service.generate_reference', 'service.generate_keyframe')]
    assert len(calls) == 3
    for call in calls:
        kw = {x.arg: ast.unparse(x.value) for x in call.keywords}
        assert kw['channel_id'] == 'job.channel_id'
