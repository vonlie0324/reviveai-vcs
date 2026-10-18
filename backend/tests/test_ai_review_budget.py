"""Small deterministic tests; no external cloud calls."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.services.ai_review_budget import review_cost_reservation_usd


class ReviewBudgetTests(unittest.TestCase):
    def test_unconfigured_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                review_cost_reservation_usd()

    def test_invalid_and_zero_rejected(self):
        for value in ('-1', '0', 'NaN', 'Infinity', 'abc'):
            with self.subTest(value=value), patch.dict(os.environ, {'REVIVEAI_GEMINI_REVIEW_RESERVATION_USD': value}):
                with self.assertRaises(ValueError):
                    review_cost_reservation_usd()

    def test_configured_estimate_is_used(self):
        with patch.dict(os.environ, {'REVIVEAI_GEMINI_REVIEW_RESERVATION_USD': '0.05'}):
            self.assertEqual(review_cost_reservation_usd(), 0.05)

if __name__ == '__main__':
    unittest.main()
