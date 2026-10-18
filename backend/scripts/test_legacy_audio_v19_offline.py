"""Offline fail-closed validation of V19 emulator-only integration test."""
import ast, pathlib
p=pathlib.Path(__file__).with_name('test_legacy_audio_v19_emulator.py')
s=p.read_text(encoding='utf8')
ast.parse(s)
assert s.index('isolation()') < s.index('from google.cloud import firestore',s.index('def main():'))
for token in ('queue.get(transaction=t)','session.get(transaction=t)','job.get(transaction=t)','journal.get(transaction=t)','STAGED_VERIFIED','NEEDS_REVIEW','currentPublicationId','recovery_maintenance','SYNTHETIC_CROSS_DOCUMENT_EMULATOR_PASSED_COMMIT_DISABLED'):
    assert token in s,token
print('V19: OFFLINE SOURCE SAFETY CHECKS PASSED; ZERO NETWORK')
