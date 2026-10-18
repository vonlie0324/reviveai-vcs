import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.services.youtube_upload_recovery_policy import parse_committed_bytes


class YouTubeUploadRecoveryPolicyTests(unittest.TestCase):
    def test_empty_range_starts_at_zero(self):
        self.assertEqual(parse_committed_bytes(None, 100).committed, 0)

    def test_partial_resumes_next_byte(self):
        value = parse_committed_bytes('bytes=0-49', 100)
        self.assertEqual(value.committed, 50)
        self.assertFalse(value.complete_without_video_id)

    def test_fully_committed_needs_reconciliation(self):
        value = parse_committed_bytes('bytes=0-99', 100)
        self.assertTrue(value.complete_without_video_id)

    def test_invalid_server_ranges_are_rejected(self):
        for item in ('bytes=50-99', 'bytes=0-100', 'garbage', 'bytes=0--1'):
            with self.subTest(item=item), self.assertRaises(ValueError):
                parse_committed_bytes(item, 100)

    def test_invalid_total(self):
        with self.assertRaises(ValueError):
            parse_committed_bytes(None, -1)


if __name__ == '__main__':
    unittest.main()
