class VeoAlertService:
    """
    Alert rule foundation for Veo operations.
    """

    DEFAULT_THRESHOLDS = {
        "stale_operations": 10,
        "retry_exhaustion": 5,
        "worker_failures": 3,
    }

    def evaluate(self, metrics):
        alerts = []

        if metrics.get("stale_detected", 0) >= self.DEFAULT_THRESHOLDS["stale_operations"]:
            alerts.append("STALE_OPERATION_THRESHOLD_EXCEEDED")

        if metrics.get("failed", 0) >= self.DEFAULT_THRESHOLDS["worker_failures"]:
            alerts.append("RECOVERY_FAILURE_THRESHOLD_EXCEEDED")

        return alerts
