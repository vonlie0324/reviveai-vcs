"""
Distributed lock abstraction for recovery execution.

The implementation can be backed by:
- Firestore transaction lock
- Redis lock
- Database advisory lock
"""


class SoundtrackRecoveryLock:

    def __init__(self, backend=None):
        self.backend = backend

    async def acquire(self, key):
        if self.backend:
            return await self.backend.acquire(key)

        return True

    async def release(self, key):
        if self.backend:
            return await self.backend.release(key)

        return True
