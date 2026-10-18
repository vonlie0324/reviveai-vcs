"""Structural regression tests for budget authority and error classification.

Run full repository tests as well; these intentionally avoid external services.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'services'


def _method(file_name, cls, method):
    tree = ast.parse((ROOT / file_name).read_text(encoding='utf-8'))
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    return next(n for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == method)


def test_production_scoped_claim_does_not_use_legacy_video_cap():
    node = _method('media_studio_job_service.py', 'MediaStudioJobStore', 'claim_video_generation')
    source = ast.unparse(node)
    assert 'legacy_unscoped_job = not bool(getattr(job, \'production_brief_job_id\', None))' in source
    assert 'legacy_unscoped_job and settings.video_budget_enforced' in source


def test_firestore_budget_remains_authoritative():
    node = _method('media_generation_service.py', 'MediaGenerationService', 'generate_video_clip')
    source = ast.unparse(node)
    assert 'self.firestore_budget_service.reserve(' in source
    assert 'if not reservation.get(\'allowed\'):' in source
    assert 'BUDGET_RESERVATION_REJECTED' in source
    assert 'BUDGET_EXCEEDED' in source


def test_insufficient_funds_has_explicit_reason():
    node = _method('firestore_budget_service.py', 'FirestoreBudgetService', 'reserve')
    source = ast.unparse(node)
    assert "'reason': 'insufficient_funds'" in source
    assert "'requested': estimated_cost" in source
