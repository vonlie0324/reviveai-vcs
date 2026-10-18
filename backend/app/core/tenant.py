from __future__ import annotations

import hashlib
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Generic, Optional, TypeVar


_DEFAULT_TENANT_ID = "local-dev-user"
_current_tenant_id: ContextVar[str] = ContextVar("reviveai_tenant_id", default=_DEFAULT_TENANT_ID)
_current_tenant_namespace_override: ContextVar[Optional[str]] = ContextVar("reviveai_tenant_namespace_override", default=None)

K = TypeVar("K")
V = TypeVar("V")


class TenantContextError(RuntimeError):
    pass


def normalize_tenant_id(value: str | None) -> str:
    tenant_id = (value or "").strip()
    if not tenant_id:
        raise TenantContextError("Authenticated user is missing a Firebase uid.")
    if len(tenant_id) > 256:
        raise TenantContextError("Authenticated Firebase uid is invalid.")
    return tenant_id


def set_current_tenant(tenant_id: str) -> Token[str]:
    return _current_tenant_id.set(normalize_tenant_id(tenant_id))


def reset_current_tenant(token: Token[str]) -> None:
    _current_tenant_id.reset(token)


def current_tenant_id() -> str:
    return normalize_tenant_id(_current_tenant_id.get())


@contextmanager
def tenant_context(tenant_id: str):
    token = set_current_tenant(tenant_id)
    namespace_token = _current_tenant_namespace_override.set(None)
    try:
        yield
    finally:
        _current_tenant_namespace_override.reset(namespace_token)
        reset_current_tenant(token)


def normalize_tenant_namespace(value: str) -> str:
    namespace = (value or "").strip().lower()
    if len(namespace) != 32 or any(ch not in "0123456789abcdef" for ch in namespace):
        raise TenantContextError("Tenant namespace is invalid.")
    return namespace


@contextmanager
def tenant_namespace_context(namespace: str):
    """Use an already-hashed tenant namespace for trusted backend workers.

    This is intentionally separate from tenant_context(): background supervisors only
    know the non-PII namespace stored in Firestore and must not attempt to reverse it
    into a Firebase UID.
    """
    token = _current_tenant_namespace_override.set(normalize_tenant_namespace(namespace))
    try:
        yield
    finally:
        _current_tenant_namespace_override.reset(token)


def tenant_namespace(tenant_id: str | None = None) -> str:
    """Return a filesystem-safe, non-PII tenant namespace.

    Firebase UIDs are intentionally not written verbatim into paths. The stable digest
    is sufficient to isolate tenant files while avoiding user identifiers in filenames.
    """
    if tenant_id is None:
        override = _current_tenant_namespace_override.get()
        if override:
            return normalize_tenant_namespace(override)
    raw = normalize_tenant_id(tenant_id or current_tenant_id())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def tenant_scoped_root(base: Path | str, *, create: bool = True) -> Path:
    path = Path(base) / "tenants" / tenant_namespace()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


class TenantScopedDict(MutableMapping[K, V], Generic[K, V]):
    """Dictionary whose visible keyspace is automatically scoped to the current tenant.

    Existing job-store code can keep using ``get(job_id)``, ``values()`` and item
    assignment without accidentally sharing one process-wide in-memory cache between
    authenticated users.
    """

    def __init__(self) -> None:
        self._data: dict[tuple[str, K], V] = {}

    def _key(self, key: K) -> tuple[str, K]:
        return (tenant_namespace(), key)

    def __getitem__(self, key: K) -> V:
        return self._data[self._key(key)]

    def __setitem__(self, key: K, value: V) -> None:
        self._data[self._key(key)] = value

    def __delitem__(self, key: K) -> None:
        del self._data[self._key(key)]

    def __iter__(self) -> Iterator[K]:
        namespace = tenant_namespace()
        for (tenant_key, key), _value in self._data.items():
            if tenant_key == namespace:
                yield key

    def __len__(self) -> int:
        namespace = tenant_namespace()
        return sum(1 for tenant_key, _key in self._data if tenant_key == namespace)

    def get(self, key: K, default=None):  # type: ignore[override]
        return self._data.get(self._key(key), default)

    def values(self):  # type: ignore[override]
        namespace = tenant_namespace()
        return [value for (tenant_key, _key), value in self._data.items() if tenant_key == namespace]

    def clear(self) -> None:  # type: ignore[override]
        namespace = tenant_namespace()
        doomed = [key for key in self._data if key[0] == namespace]
        for key in doomed:
            del self._data[key]


def tenant_bound(func):
    """Capture the current tenant for a FastAPI BackgroundTask callback.

    Request handlers capture the authenticated Firebase UID. Trusted headless workers
    capture the already-hashed namespace override so their spawned background tasks
    stay inside the same tenant without needing access to the original UID.
    """
    import inspect

    namespace_override = _current_tenant_namespace_override.get()
    tenant_id = None if namespace_override else current_tenant_id()

    async def _runner(*args, **kwargs):
        context = (
            tenant_namespace_context(namespace_override)
            if namespace_override
            else tenant_context(tenant_id or _DEFAULT_TENANT_ID)
        )
        with context:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

    return _runner
