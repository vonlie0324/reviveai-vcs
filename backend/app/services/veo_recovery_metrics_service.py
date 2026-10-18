from datetime import datetime, timezone


class VeoRecoveryMetricsService:
    """
    Lightweight recovery metrics collector.
    """

    def __init__(self):
        self.metrics = {
            "recovered": 0,
            "failed": 0,
            "stale_detected": 0,
            "lock_skipped": 0,
        }

    def increment(self, metric):
        if metric in self.metrics:
            self.metrics[metric] += 1

    def snapshot(self):
        return {
            **self.metrics,
            "timestamp": datetime.now(timezone.utc),
        }
