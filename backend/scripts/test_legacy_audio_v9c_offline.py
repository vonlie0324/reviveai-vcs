"""Static/offline checks; no Google SDK, auth, or network required."""
import importlib.util
import os
import pathlib
import subprocess
import sys
import unittest

SOURCE = pathlib.Path(__file__).with_name('test_legacy_audio_v9c_emulator.py')
spec = importlib.util.spec_from_file_location('v9c_emulator_module', SOURCE)
v9 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v9)

class Tests(unittest.TestCase):
    def test_roundtrip_inline(self):
        job = v9.job_fixture(10)
        manifest, chunks = v9.make_manifest(job, v9.MODE_INLINE)
        self.assertFalse(chunks)
        self.assertEqual(v9.digest(v9.encode(job)), manifest['payload_sha256'])
    def test_chunk_payload(self):
        job = v9.job_fixture(850_000)
        manifest, chunks = v9.make_manifest(job, v9.MODE_CHUNKED)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(v9.digest(b''.join(chunks)), manifest['compressed_sha256'])
        self.assertEqual(v9.encode(job), v9.gzip.decompress(b''.join(chunks)))
    def test_isolation_guard_rejects_absent_host(self):
        saved = os.environ.pop('FIRESTORE_EMULATOR_HOST', None)
        try:
            with self.assertRaises(SystemExit): v9.ensure_isolated()
        finally:
            if saved is not None:os.environ['FIRESTORE_EMULATOR_HOST']=saved
    def test_no_app_import_and_no_prod_writes(self):
        src = SOURCE.read_text(encoding='utf-8')
        self.assertNotIn('from app.', src)
        self.assertNotIn('gs://reviveai/', src)
        self.assertNotIn('reviveai-prod', src)
    def test_current_payload_expected_review(self):
        job = v9.job_fixture(10)
        class Dummy:pass
        candidate,_ = v9.prepare_candidate(Dummy(), job, v9.MODE_INLINE)
        j = v9.json.loads(candidate['payload_json'])
        self.assertEqual(j['result']['review_status'], 'NEEDS_REVIEW')
        self.assertEqual(j['detail']['source_visual_asset_id'], 'visual-synthetic')

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():sys.exit(1)
    print('ALL 5 V9C OFFLINE CHECKS PASSED')
