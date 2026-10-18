import os
import unittest
from unittest.mock import patch
from app.services.narration_budget import estimated_tts_usd


class NarrationBudgetTests(unittest.TestCase):
    def test_requires_configured_rate(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                estimated_tts_usd('hello')

    def test_estimate_accounts_for_retries(self):
        with patch.dict(os.environ, {'REVIVEAI_TTS_USD_PER_MILLION_CHARS': '20'}):
            self.assertAlmostEqual(estimated_tts_usd('a' * 1000), 0.06)

    def test_rejects_invalid_rate(self):
        with patch.dict(os.environ, {'REVIVEAI_TTS_USD_PER_MILLION_CHARS': 'nan'}):
            with self.assertRaises(ValueError):
                estimated_tts_usd('hello')


if __name__ == '__main__':
    unittest.main()
