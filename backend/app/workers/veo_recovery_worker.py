from app.services.veo_operation_recovery_service import (
    VeoOperationRecoveryService,
)
from app.services.veo_recovery_metrics_service import VeoRecoveryMetricsService
from app.services.veo_recovery_lock_service import (
    VeoRecoveryLockService,
)


class VeoRecoveryWorker:
    """
    Background recovery worker.
    """

    def __init__(self):
        self.service = VeoOperationRecoveryService()
        self.lock = VeoRecoveryLockService()
        self.metrics = VeoRecoveryMetricsService()

    def run(self):
        if not self.lock.acquire():
            self.metrics.increment("lock_skipped")
            return []

        try:
            stale = self.service.mark_stale_operations()
            self.metrics.increment("stale_detected")

            for operation_id in stale:
                self.service.recover(operation_id)

            return stale

        finally:
            self.lock.release()
