import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).resolve().parents[1] / 'app/api/routes/autopilot_state.py'

class TestCaptionRecoveryLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding='utf-8')
        cls.tree = ast.parse(cls.source)

    def test_lifecycle_endpoints_present(self):
        names = {node.name for node in ast.walk(self.tree) if isinstance(node, ast.AsyncFunctionDef)}
        self.assertIn('resume_caption_recovery', names)
        self.assertIn('caption_recovery_operation_status', names)

    def test_preserves_historical_counters_and_limits_managed_attempts(self):
        self.assertIn('caption-recovery-managed:', self.source)
        self.assertIn('targeted-caption-realign-v3:', self.source)
        self.assertIn('if attempt_no >= 2:', self.source)
        self.assertIn('attempts = {**s.attempts, attempt_key: attempt_no + 1}', self.source)

    def test_guards_assets_and_terminal_states(self):
        for snippet in ('latest.job_id != audio.job_id', "'status': 'FAILED'", "'status': 'SUCCEEDED'", 'lease_expires_at', 'expected_revision=current.revision'):
            self.assertIn(snippet, self.source)

if __name__ == '__main__':
    unittest.main()
