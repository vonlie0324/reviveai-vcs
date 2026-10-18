"""Static contract checks for the production-brief cost boundary."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'app' / 'services'


def test_identity_wired_from_durable_job():
    source = (ROOT / 'production_brief_job_service.py').read_text()
    assert 'service.configure_budget_identity(job_id, analysis.channel.channel_id)' in source


def test_billable_attempt_reserved_before_submission():
    source = (ROOT / 'production_brief_service.py').read_text()
    assert source.index('ledger, operation_id, estimate = self._reserve_gemini_attempt()') < source.index('client.aio.models.generate_content(')
    assert source.index('ledger.reconcile(self._budget_production_id, operation_id, estimate, estimate)') < source.index('parsed = getattr(response, "parsed", None)')


def test_unknown_provider_outcome_does_not_retry():
    source = (ROOT / 'production_brief_service.py').read_text()
    assert 'reservation held for reconciliation' in source
    assert 'raise ProductionBriefError(' in source
