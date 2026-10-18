"""Source regression tests: budget exhaustion must remain terminal/non-retryable.

These narrow checks complement the project's existing integration tests; they do
not replace live verification of Firestore reservations or Veo operations.
"""
import ast
from pathlib import Path

SERVICES = Path(__file__).resolve().parents[1] / 'app' / 'services'


def test_budget_exhaustion_is_preserved_in_localized_regeneration():
    source = (SERVICES / 'media_studio_job_service.py').read_text(encoding='utf-8')
    ast.parse(source)
    assert 'budget_blocked = "BUDGET_EXCEEDED" in str(exc).upper()' in source
    assert 'status=ClipOperationStatus.BUDGET_EXCEEDED if budget_blocked else ClipOperationStatus.FAILED' in source


def test_autopilot_checks_every_operation_for_budget_failure_before_retry():
    source = (SERVICES / 'autopilot_supervisor_service.py').read_text(encoding='utf-8')
    ast.parse(source)
    budget_check = source.index('budget_block = next((op for op in operations')
    failed_check = source.index('failed = next((op for op in operations if op.status == ClipOperationStatus.FAILED)')
    retry = source.index('await self._regenerate_clip(media_job.job_id, failed.shot_number')
    assert budget_check < failed_check < retry
    assert '"BUDGET_EXCEEDED" in str(op.error or "").upper()' in source
