import asyncio
import os
import unittest
from unittest.mock import patch

from app.services.channel_intelligence_budget import (
    ChannelIntelligenceBudget, IntelligenceProviderOutcomeUncertain,
    configured_cost, configured_monthly_cap,
)


class TestIntelligenceLimits(unittest.TestCase):
    def test_missing_limits_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                configured_cost()
            with self.assertRaises(RuntimeError):
                configured_monthly_cap()

    def test_invalid_limits_fail_closed(self):
        with patch.dict(os.environ, {
            'REVIVEAI_CHANNEL_INTELLIGENCE_RESERVATION_USD': 'NaN',
            'REVIVEAI_CHANNEL_INTELLIGENCE_MONTHLY_BUDGET_USD': '-1',
        }):
            with self.assertRaises(RuntimeError):
                configured_cost()
            with self.assertRaises(RuntimeError):
                configured_monthly_cap()

    def test_no_firestore_blocks_reservation(self):
        with patch('app.services.channel_intelligence_budget.firestore', None):
            with self.assertRaises(RuntimeError):
                ChannelIntelligenceBudget(db=object()).reserve('channel', category='dna')

    def test_timeout_preserves_hold_and_blocks_retry(self):
        class Models:
            async def generate_content(self, **kwargs):
                raise TimeoutError('upstream timeout')
        class Aio:
            models = Models()
        class Client:
            aio = Aio()
        class FakeBudget(ChannelIntelligenceBudget):
            def reserve(self, *args, **kwargs):
                return 'ci_held'
            def reconcile(self, *args, **kwargs):
                raise AssertionError('must not reconcile failed provider call')
        with self.assertRaises(IntelligenceProviderOutcomeUncertain) as exc:
            asyncio.run(FakeBudget(db=object()).generate(
                channel_id='c1', category='dna', client=Client(), model='fake', contents='prompt'))
        self.assertIn('ci_held', str(exc.exception))

    def test_success_reconciles_once(self):
        calls=[]
        class Models:
            async def generate_content(self, **kwargs):
                return 'response'
        class Aio:
            models = Models()
        class Client:
            aio = Aio()
        class FakeBudget(ChannelIntelligenceBudget):
            def reserve(self, *args, **kwargs):
                calls.append('reserve')
                return 'ci_success'
            def reconcile(self, operation_id, **kwargs):
                calls.append(('reconcile', operation_id))
        result=asyncio.run(FakeBudget(db=object()).generate(
            channel_id='c1', category='dna', client=Client(), model='fake', contents='prompt'))
        self.assertEqual(result, 'response')
        self.assertEqual(calls, ['reserve', ('reconcile', 'ci_success')])

    def test_reconciliation_error_blocks_provider_retry(self):
        class Models:
            async def generate_content(self, **kwargs):
                return 'response'
        class Aio:
            models = Models()
        class Client:
            aio = Aio()
        class FakeBudget(ChannelIntelligenceBudget):
            def reserve(self, *args, **kwargs):
                return 'ci_reconcile'
            def reconcile(self, *args, **kwargs):
                raise RuntimeError('firestore unavailable')
        with self.assertRaises(IntelligenceProviderOutcomeUncertain):
            asyncio.run(FakeBudget(db=object()).generate(
                channel_id='c1', category='dna', client=Client(), model='fake'))


if __name__ == '__main__':
    unittest.main()
