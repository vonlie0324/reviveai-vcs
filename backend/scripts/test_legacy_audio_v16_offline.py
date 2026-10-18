"""Syntax/source gate: no cloud imports or clients instantiated."""
import ast
from pathlib import Path
p=Path(__file__).resolve().parents[1]/'app/services/autopilot_supervisor_queue.py'
t=p.read_text(encoding='utf-8')
root=ast.parse(t)
cls=next(n for n in root.body if isinstance(n,ast.ClassDef) and n.name=='AutopilotSupervisorQueue')
methods={n.name: n for n in cls.body if isinstance(n,ast.FunctionDef)}
for name in ('_maintenance_active','acquire_recovery_maintenance','renew_recovery_maintenance','release_recovery_maintenance','acquire_lease','renew_lease','get_due','list_running','schedule_pending'):
    assert name in methods, name
for name in ('acquire_lease','renew_lease','get_due','list_running','schedule_pending'):
    assert '_maintenance_active' in ast.unparse(methods[name]), name
assert 'transaction.set(ref, {"recovery_maintenance"' in t
print('V16: OFFLINE STATIC GUARD CHECKS PASSED — NO NETWORK')
