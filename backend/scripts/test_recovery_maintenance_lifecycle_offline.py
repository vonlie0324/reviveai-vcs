"""Pure offline tests; no cloud SDK or backend startup."""
from reviveai_recovery_maintenance_lifecycle import run_with_maintenance, MaintenanceLost

class Queue:
    def __init__(self):
        self.g=0; self.active=False; self.renewals=0; self.fail_at=0; self.released=False
    def acquire_recovery_maintenance(self, **kw):
        if self.active: return 0
        self.g+=1; self.active=True; return self.g
    def renew_recovery_maintenance(self, **kw):
        self.renewals+=1
        return self.active and kw['generation']==self.g and self.renewals!=self.fail_at
    def release_recovery_maintenance(self, **kw):
        self.released=kw['generation']==self.g
        if self.released:self.active=False
        return self.released

def run(q,op):
    return run_with_maintenance(q,namespace='fake-tenant',audio_job_id='fake-job',owner='local',
        expected_revision=7,operation=op,lease_seconds=30,heartbeat_seconds=0.1)

def main():
    q=Queue()
    assert run(q,lambda c,check: (check(),c.generation)[1])==1
    assert q.released and not q.active
    q=Queue();q.active=True
    try: run(q,lambda c,check:True)
    except MaintenanceLost:pass
    else:raise AssertionError('competing claim accepted')
    q=Queue();q.fail_at=2
    try:run(q,lambda c,check:check())
    except MaintenanceLost:pass
    else:raise AssertionError('lost lease allowed finalization')
    assert q.released
    q=Queue()
    try:run(q,lambda c,check: (_ for _ in ()).throw(RuntimeError('upload interrupted')))
    except RuntimeError:pass
    else:raise AssertionError('interruption swallowed')
    assert q.released
    print('PASS: acquire/renew/release, competing claim, lease loss, interrupted operation')
    print('MAINTENANCE LIFECYCLE: OFFLINE PASSED; NO CLOUD CLIENTS')
if __name__=='__main__':main()
