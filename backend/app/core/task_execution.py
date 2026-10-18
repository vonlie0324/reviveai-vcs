from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_in_internal_task: ContextVar[bool] = ContextVar("reviveai_in_internal_task", default=False)


def in_internal_task() -> bool:
    return bool(_in_internal_task.get())


@contextmanager
def internal_task_context():
    token = _in_internal_task.set(True)
    try:
        yield
    finally:
        _in_internal_task.reset(token)
