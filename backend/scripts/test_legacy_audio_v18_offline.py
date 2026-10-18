"""No-cloud V18 tests: source boundaries and fail-closed context checks."""
import ast
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.services.autopilot_side_effect_fence import supervisor_lease_scope,require_supervisor_lease

for path in [ROOT/'app/services/autopilot_supervisor_service.py',ROOT/'app/services/audio_finishing_job_service.py',ROOT/'app/workers/autopilot_supervisor_worker.py',ROOT/'app/services/autopilot_supervisor_queue.py']:
    ast.parse(path.read_text(encoding='utf8'))
print('PASS: modified production-source syntax')

# The dependency is stubbed before import, so no Firestore SDK is contacted.
import types
stub=types.ModuleType('app.services.autopilot_supervisor_queue')
status={'valid':True,'calls':[]}
def check(**kw):
    status['calls'].append(kw)
    return status['valid']
stub.autopilot_supervisor_queue=SimpleNamespace(assert_supervisor_lease=check)
with patch.dict(sys.modules,{'app.services.autopilot_supervisor_queue':stub}):
    require_supervisor_lease('unscoped')
    assert not status['calls']
    with supervisor_lease_scope('synthetic-tenant','synthetic-worker'):
        require_supervisor_lease('audio render start')
        status['valid']=False
        try:require_supervisor_lease('autonomous YouTube publish request')
        except RuntimeError:pass
        else:raise AssertionError('stale owner was accepted')
    require_supervisor_lease('outside context')
    assert len(status['calls'])==2
    assert status['calls'][0]=={'namespace':'synthetic-tenant','owner':'synthetic-worker'}
print('PASS: scoped pass, stale owner refused, context cleanup')
text=(ROOT/'app/services/autopilot_supervisor_service.py').read_text()
assert text.index('require_supervisor_lease("autonomous YouTube publish request")') < text.index('existing_publication = await youtube_publishing_service.publish(')
assert 'require_supervisor_lease("audio render start")' in (ROOT/'app/services/audio_finishing_job_service.py').read_text()
assert 'with supervisor_lease_scope(namespace, invocation_owner):' in (ROOT/'app/workers/autopilot_supervisor_worker.py').read_text()
print('PASS: targeted render and publish call-site guards present')
print('V18: OFFLINE TARGETED FENCE TESTS PASSED; NO NETWORK, NO CLOUD WRITES')
