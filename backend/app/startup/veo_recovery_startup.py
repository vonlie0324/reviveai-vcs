import asyncio

from app.workers.veo_recovery_worker import (
    VeoRecoveryWorker,
)


async def start_veo_recovery_worker():
    """
    Startup hook for FastAPI/application lifecycle.
    """

    worker = VeoRecoveryWorker()

    while True:
        worker.run()
        await asyncio.sleep(300)
