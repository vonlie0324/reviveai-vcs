import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from app.services.gemini_usage_meter import gemini_token_cost


class UsageMeterTests(unittest.TestCase):
    def test_usage_with_thinking(self):
        response = SimpleNamespace(usage_metadata=SimpleNamespace(prompt_token_count=1000, candidates_token_count=400, thoughts_token_count=100))
        with patch.dict(os.environ, {"REVIVEAI_GEMINI_INPUT_USD_PER_MILLION_TOKENS": "2", "REVIVEAI_GEMINI_OUTPUT_USD_PER_MILLION_TOKENS": "10"}):
            cost, counts = gemini_token_cost(response)
        self.assertAlmostEqual(cost, 0.007)
        self.assertEqual(counts["thinking_tokens"], 100)

    def test_missing_usage_is_not_zero(self):
        with self.assertRaises(ValueError):
            gemini_token_cost(SimpleNamespace())

    def test_bad_rate_rejected(self):
        response = {"usage_metadata": {"prompt_token_count": 2, "candidates_token_count": 1}}
        with patch.dict(os.environ, {"REVIVEAI_GEMINI_INPUT_USD_PER_MILLION_TOKENS": "nan", "REVIVEAI_GEMINI_OUTPUT_USD_PER_MILLION_TOKENS": "10"}):
            with self.assertRaises(ValueError):
                gemini_token_cost(response)

    def test_missing_rate_fails(self):
        response = {"usage_metadata": {"prompt_token_count": 2, "candidates_token_count": 1}}
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                gemini_token_cost(response)


if __name__ == "__main__":
    unittest.main()
