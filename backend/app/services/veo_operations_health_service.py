from datetime import datetime, timezone


class VeoOperationsHealthService:
    """
    Runtime health and operational metrics facade.
    """

    def __init__(self, metrics=None):
        self.metrics = metrics

    def get_status(self):
        metrics = (
            self.metrics.snapshot()
            if self.metrics
            else {}
        )

        return {
            "service": "veo_recovery_worker",
            "status": "RUNNING",
            "metrics": metrics,
            "timestamp": datetime.now(timezone.utc),
        }
