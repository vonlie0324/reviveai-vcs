"""V17 static contract check. No app startup, no network."""
from pathlib import Path
import ast
root=Path(__file__).resolve().parents[1]
q=(root/'app/services/autopilot_supervisor_queue.py').read_text(encoding='utf-8')
w=(root/'app/workers/autopilot_supervisor_worker.py').read_text(encoding='utf-8')
for name,src in [('queue',q),('worker',w)]: ast.parse(src, filename=name)
assert 'def assert_supervisor_lease' in q
for token in ['self._maintenance_active(data, now)', 'data.get("lease_owner") == owner', 'expiry > now', 'snap = self._collection().document(namespace).get()']:
 assert token in q,token
assert w.count('autopilot_supervisor_queue.assert_supervisor_lease')==2
assert 'if lease_lost.is_set():' in w
print('V17: OFFLINE BOUNDARY CHECKS PASSED; NO NETWORK OR WRITES')
