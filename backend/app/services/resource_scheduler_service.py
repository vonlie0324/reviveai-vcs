from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator, Dict

from app.core.config import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class _PoolState:
    name: str
    capacity: int
    semaphore: asyncio.Semaphore
    active: int = 0
    waiting: int = 0
    completed: int = 0
    last_acquired_at: str | None = None
    last_released_at: str | None = None


class GlobalResourceScheduler:
    """Process-wide bounded scheduler for expensive generative-AI calls.

    Per-production worker pools are intentionally separate from this scheduler. A single
    production may fan out to several shots, while this service guarantees that the sum
    of ALL active productions never exceeds the configured Vertex/Veo budgets.
    """

    def __init__(self, *, image_capacity: int, video_capacity: int):
        self._lock = asyncio.Lock()
        self._pools: Dict[str, _PoolState] = {
            "image": _PoolState("image", image_capacity, asyncio.Semaphore(image_capacity)),
            "video": _PoolState("video", video_capacity, asyncio.Semaphore(video_capacity)),
        }

    @asynccontextmanager
    async def acquire(self, resource: str) -> AsyncIterator[None]:
        pool = self._pools[resource]
        async with self._lock:
            pool.waiting += 1
        await pool.semaphore.acquire()
        async with self._lock:
            pool.waiting = max(0, pool.waiting - 1)
            pool.active += 1
            pool.last_acquired_at = _now()
        try:
            yield
        finally:
            async with self._lock:
                pool.active = max(0, pool.active - 1)
                pool.completed += 1
                pool.last_released_at = _now()
            pool.semaphore.release()

    async def snapshot(self) -> dict:
        async with self._lock:
            return {
                "resources": {
                    name: {
                        "capacity": pool.capacity,
                        "active": pool.active,
                        "waiting": pool.waiting,
                        "available": max(0, pool.capacity - pool.active),
                        "completed": pool.completed,
                        "last_acquired_at": pool.last_acquired_at,
                        "last_released_at": pool.last_released_at,
                    }
                    for name, pool in self._pools.items()
                },
                "policy": "global_bounded_concurrency",
            }


_settings = get_settings()
global_resource_scheduler = GlobalResourceScheduler(
    image_capacity=_settings.global_image_generation_concurrency,
    video_capacity=_settings.global_video_generation_concurrency,
)
