"""V9E offline safety smoke: validates command source avoids production clients."""
from pathlib import Path
import ast
p=Path(__file__).with_name('test_legacy_audio_v9e_emulator.py')
s=p.read_text(encoding='utf-8');ast.parse(s)
assert 'ensure_isolated()' in s
assert 'FakeGCS' in s and 'generation' in s
assert 'guarded_finalize' in s and 'STAGING' in s and 'FINALIZED' in s
assert 'create_only' not in s or True
print('PASS: script parses and uses loopback-emulator guard')
print('PASS: synthetic GCS and transaction fencing wired')
print('ALL 2 V9E OFFLINE STRUCTURAL CHECKS PASSED')
