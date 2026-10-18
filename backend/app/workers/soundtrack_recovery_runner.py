"""
Runtime runner for scheduled soundtrack recovery.
"""


class SoundtrackRecoveryRunner:

    def __init__(
        self,
        scheduler,
        lock,
    ):
        self.scheduler = scheduler
        self.lock = lock

    async def run(
        self,
        job_ids,
    ):
        lock_key = "soundtrack_recovery_worker"

        acquired = await self.lock.acquire(
            lock_key
        )

        if not acquired:
            return []

        try:
            return self.scheduler.run_once(
                job_ids
            )
        finally:
            await self.lock.release(
                lock_key
            )
