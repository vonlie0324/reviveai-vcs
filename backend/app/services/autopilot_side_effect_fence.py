"""V18 cooperative supervisor-only lease fence. No cloud client created on import.

Not a transaction or a mechanism to cancel an in-flight provider request.
"""
from __future__ import annotations
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator

_ACTIVE_SUPERVISOR = ContextVar("reviveai_v18_supervisor_lease", default=None)

@contextmanager
def supervisor_lease_scope(namespace: str, owner: str) -> Iterator[None]:
    if not namespace or not owner:
        raise ValueError("supervisor lease identity required")
    token = _ACTIVE_SUPERVISOR.set((namespace, owner))
    try:
        yield
    finally:
        _ACTIVE_SUPERVISOR.reset(token)

def require_supervisor_lease(boundary: str) -> None:
    """Fail closed for scoped supervisor work; other callers use their existing authorization.

    Failures are not converted to retryable side effects here.
    """
    current = _ACTIVE_SUPERVISOR.get()
    if current is None:
        return
    from app.services.autopilot_supervisor_queue import autopilot_supervisor_queue
    namespace, owner = current
    if not autopilot_supervisor_queue.assert_supervisor_lease(namespace=namespace, owner=owner):
        raise RuntimeError(f"Autopilot supervisor lease invalid before {boundary}")
