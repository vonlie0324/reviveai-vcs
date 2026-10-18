"""Run with plain python; no app import, Cloud SDK or network."""
from dataclasses import replace
from legacy_audio_v15_coordination import Simulator, State, UnsafeRecovery

def blocked(fn):
    try: fn()
    except UnsafeRecovery: return
    raise AssertionError('expected UnsafeRecovery')

def test():
    total=0
    def ok(label):
        nonlocal total
        total+=1; print('PASS:',label)
    a=Simulator(); gen=a.maintenance_acquire('recovery-A',10468); assert gen==1; ok('atomic maintenance claim')
    assert not a.supervisor_acquire('supervisor-2'); ok('supervisor cannot reacquire during maintenance')
    blocked(lambda:a.maintenance_acquire('recovery-B',10468)); ok('concurrent recovery refused')
    blocked(lambda:a.commit('recovery-A',gen,10468,1));ok('unverified artifacts block commit')
    a.mark_artifacts('recovery-A',gen,journal_verified=True,assets_verified=True);a.commit('recovery-A',gen,10468,1)
    assert a.state.review_status=='NEEDS_REVIEW' and a.state.completed; ok('verified commit remains NEEDS_REVIEW')
    blocked(lambda:a.commit('recovery-A',gen,10468,1));ok('duplicate completion blocked')
    b=Simulator(State(supervisor_owner='worker',supervisor_expired=False));blocked(lambda:b.maintenance_acquire('recover',10468));ok('live supervisor blocks claim')
    c=Simulator(State());g=c.maintenance_acquire('r1',10468);c.state=replace(c.state,maintenance_expired=True)
    g2=c.maintenance_acquire('r2',10468);assert g2>g;blocked(lambda:c.commit('r1',g,10468,1));ok('expired owner is fenced')
    c.mark_artifacts('r2',g2,journal_verified=True,assets_verified=True);c.state=replace(c.state,revision=10469)
    blocked(lambda:c.commit('r2',g2,10468,1));ok('session revision change blocks commit')
    d=Simulator();g=d.maintenance_acquire('r1',10468);d.mark_artifacts('r1',g,journal_verified=True,assets_verified=True)
    d.state=replace(d.state,publication='ytpub_created');blocked(lambda:d.commit('r1',g,10468,1));ok('publication race blocks commit')
    e=Simulator();g=e.maintenance_acquire('r1',10468);e.state=replace(e.state,job_generation=2)
    e.mark_artifacts('r1',g,journal_verified=True,assets_verified=True);blocked(lambda:e.commit('r1',g,10468,1));ok('job generation fence')
    f=Simulator();g=f.maintenance_acquire('r1',10468);assert not f.release('r2',g) and f.release('r1',g);ok('only owner can release claim')
    z=Simulator(State(audio_checkpoint=True));blocked(lambda:z.maintenance_acquire('r1',10468));ok('checkpoint presence blocks legacy recovery')
    print(f'V15: {total}/{total} OFFLINE COORDINATION TESTS PASSED; NO CLOUD CLIENTS OR WRITES')
if __name__=='__main__':test()
