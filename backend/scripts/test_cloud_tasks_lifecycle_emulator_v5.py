"""Isolated, emulator-only tests of real ReviveAI queue and worker methods.

Usage: FIRESTORE_EMULATOR_HOST=127.0.0.1:8085 python test_cloud_tasks_lifecycle_emulator.py
No ReviveAI imports, no Cloud Tasks dispatch, no production project credentials.
"""
from __future__ import annotations
import ast
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

HOST = os.getenv('FIRESTORE_EMULATOR_HOST')
if HOST != '127.0.0.1:8085':
    raise SystemExit('REFUSING: require FIRESTORE_EMULATOR_HOST=127.0.0.1:8085')
from google.cloud import firestore
DB = firestore.Client(project='reviveai-local-test', database='(default)')
if DB.project != 'reviveai-local-test':
    raise SystemExit('REFUSING: unexpected project')
ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'
if not APP.is_dir():
    raise SystemExit('Missing ./app folder: place script beside app/')
settings = SimpleNamespace(
    autopilot_autonomous_final_approval_enabled=False,
    autopilot_continuous_campaign_enabled=False,
    autopilot_auto_replenish_enabled=False,
    autopilot_event_driven_enabled=False,
    autopilot_supervisor_lease_seconds=120,
)

@contextmanager
def noop_context(*_a, **_kw):
    yield

def load_class(source_file, class_name, bindings):
    tree = ast.parse(source_file.read_text(encoding='utf-8'))
    cls = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        raise AssertionError(f'{class_name} missing')
    compiled = compile(ast.Module(body=[cls], type_ignores=[]), str(source_file), 'exec')
    exec(compiled, bindings)
    return bindings[class_name]

queue_globals = {
    'get_runtime_firestore_client': lambda: DB,
    'get_settings': lambda: settings,
    'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone,
    'Optional': __import__('typing').Optional,
    'in_internal_task': lambda: True,
    'AutopilotQueueItem': dataclass(frozen=True)(type('AutopilotQueueItem', (), {'__annotations__': {
        'namespace': str, 'status': str, 'revision': int,
        'execution_owner': str, 'next_run_at': __import__('typing').Optional[datetime]}})),
}
Queue = load_class(APP/'services/autopilot_supervisor_queue.py', 'AutopilotSupervisorQueue', queue_globals)
queue = Queue()
# Avoid even a hypothetical external dispatcher. The tests drive emulator docs explicitly.
queue._dispatch = lambda *_a, **_kw: True
namespace = 'offline-lifecycle-' + uuid4().hex
ref = DB.collection(queue.COLLECTION).document(namespace)

def fresh():
    ref.set({'namespace': namespace, 'status': 'RUNNING', 'revision': 1,
             'execution_owner': 'BACKEND', 'next_run_at': datetime.now(timezone.utc) - timedelta(seconds=10)})

try:
    fresh()
    assert queue.get_due(namespace) is not None
    print('PASS: due task selected from emulator')
    assert queue.acquire_lease(namespace=namespace, owner='worker-A', lease_seconds=120)
    assert not queue.acquire_lease(namespace=namespace, owner='worker-B', lease_seconds=120)
    print('PASS: duplicate delivery blocked by active supervisor lease')
    queue.release_lease(namespace=namespace, owner='worker-B')
    assert (ref.get().to_dict() or {}).get('lease_owner') == 'worker-A'
    print('PASS: competitor cannot release another worker lease')
    ref.update({'lease_expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)})
    assert queue.acquire_lease(namespace=namespace, owner='worker-B', lease_seconds=120)
    queue.release_lease(namespace=namespace, owner='worker-A')
    assert (ref.get().to_dict() or {}).get('lease_owner') == 'worker-B'
    print('PASS: expired lease takeover rejects old owner release')
    queue.release_lease(namespace=namespace, owner='worker-B')
    queue.defer(namespace, 1800, reason='test-future-wakeup')
    assert queue.get_due(namespace) is None
    print('PASS: duplicate scheduled task is ignored before next wake-up')
    ref.update({'next_run_at': datetime.now(timezone.utc)-timedelta(seconds=1)})
    assert queue.get_due(namespace) is not None
    print('PASS: due task becomes eligible after wake time')

    class Supervisor:
        def __init__(self):
            self.advances=0; self.drains=0; self.fail=False; self.record=None
        async def advance_current_tenant(self):
            self.advances+=1
            if self.fail: raise RuntimeError('synthetic interruption')
            return self.record
        async def drain_spawned(self): self.drains+=1
        def _status_is_actionable(self, session): return True
        def next_wake_delay(self, record): return 1800
    sup = Supervisor()
    sup.record=SimpleNamespace(revision=2, session=SimpleNamespace(status='RUNNING'))
    worker_globals={
        'get_settings':lambda:settings,
        'autopilot_supervisor_queue':queue,
        'autopilot_supervisor_service':sup,
        'internal_task_context': noop_context,
        'tenant_namespace_context': noop_context,
        'logger':logging.getLogger('isolated-worker'),
        'asyncio':asyncio,
        'os':os,
        'socket':__import__('socket'),
        'uuid4':uuid4,
    }
    Worker=load_class(APP/'workers/autopilot_supervisor_worker.py','AutopilotSupervisorWorker',worker_globals)
    worker=Worker()
    settings.autopilot_event_driven_enabled=True  # enables drain, but _dispatch is force-disabled
    a=asyncio.run(worker.run_namespace(namespace))
    assert a['result']=='advanced' and sup.advances==1 and sup.drains==1
    b=asyncio.run(worker.run_namespace(namespace))
    assert b['result']=='not_due' and sup.advances==1
    print('PASS: worker advances once, drains tasks, duplicate delivery not due')
    ref.update({'next_run_at':datetime.now(timezone.utc)-timedelta(seconds=1)})
    sup.fail=True
    c=asyncio.run(worker.run_namespace(namespace))
    assert c['result']=='retry_scheduled'
    assert (ref.get().to_dict() or {}).get('lease_owner') == ''
    assert queue.get_due(namespace) is None  # deferred 60 seconds
    print('PASS: synthetic worker failure releases lease and defers retry')
    print('ALL 8 ISOLATED LIFECYCLE CHECKS PASSED')
    # Confirm renewal can extend the valid owner lease but not a competitor's.
    fresh()
    assert queue.acquire_lease(namespace=namespace, owner='heartbeat-A', lease_seconds=30)
    prior = (ref.get().to_dict() or {})['lease_expires_at']
    assert queue.renew_lease(namespace=namespace, owner='heartbeat-A', lease_seconds=120)
    renewed = (ref.get().to_dict() or {})['lease_expires_at']
    assert renewed > prior
    assert not queue.renew_lease(namespace=namespace, owner='heartbeat-B', lease_seconds=120)
    ref.update({'lease_expires_at': datetime.now(timezone.utc)-timedelta(seconds=1)})
    assert not queue.renew_lease(namespace=namespace, owner='heartbeat-A', lease_seconds=120)
    print('PASS: lease renewed only for current unexpired owner')
    queue.release_lease(namespace=namespace, owner='heartbeat-A')
    # An unsuccessful dispatch MUST result in an exception, not a false HTTP-200 acknowledgement.
    fresh()
    queue._dispatch = lambda *_a, **_kw: False
    sup.fail = True
    try:
        asyncio.run(worker.run_namespace(namespace))
    except RuntimeError as exc:
        assert 'dispatch' in str(exc).lower()
        print('PASS: failed Cloud Tasks retry dispatch raises for HTTP non-2xx')
    else:
        raise AssertionError('Worker silently acknowledged failed retry dispatch')
    # A duplicate request executed by the SAME worker object must not reuse owner identity.
    queue._dispatch = lambda *_a, **_kw: True
    fresh()
    sup.fail = False
    class SlowSupervisor(Supervisor):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.release = asyncio.Event()
            self.record = SimpleNamespace(revision=3, session=SimpleNamespace(status='RUNNING'))
        async def advance_current_tenant(self):
            self.advances += 1
            self.entered.set()
            await self.release.wait()
            return self.record
    slow = SlowSupervisor()
    worker_globals['autopilot_supervisor_service'] = slow
    worker_globals['autopilot_supervisor_queue'] = queue
    Worker2 = load_class(APP/'workers/autopilot_supervisor_worker.py', 'AutopilotSupervisorWorker', worker_globals)
    same_worker = Worker2()
    async def overlap():
        first = asyncio.create_task(same_worker.run_namespace(namespace))
        await slow.entered.wait()
        second = await same_worker.run_namespace(namespace)
        assert second['result'] == 'leased_elsewhere'
        slow.release.set()
        one = await first
        assert one['result'] == 'advanced' and slow.advances == 1
    asyncio.run(overlap())
    print('PASS: duplicate task on SAME worker instance cannot share lease')
    fresh()
    blocked = SlowSupervisor()
    worker_globals['autopilot_supervisor_service'] = blocked
    Worker3 = load_class(APP/'workers/autopilot_supervisor_worker.py', 'AutopilotSupervisorWorker', worker_globals)
    abort_worker = Worker3()
    async def cancel_execution():
        task = asyncio.create_task(abort_worker.run_namespace(namespace))
        await blocked.entered.wait()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('Synthetic cancellation was ignored')
    asyncio.run(cancel_execution())
    assert (ref.get().to_dict() or {}).get('lease_owner') == ''
    print('PASS: task cancellation releases supervisor lease')
    print('ALL 12 ISOLATED LIFECYCLE CHECKS PASSED')
    print('NOTE: worker catches exceptions and returns result=error; endpoint may still return HTTP 200.')
finally:
    ref.delete()
