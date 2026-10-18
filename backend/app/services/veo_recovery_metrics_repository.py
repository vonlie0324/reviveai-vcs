from datetime import datetime, timezone


class VeoRecoveryMetricsRepository:
    """
    Persistence abstraction for recovery metrics.
    """

    def __init__(self, db=None):
        self.db = db

    def save_snapshot(self, metrics):
        document = {
            **metrics,
            "createdAt": datetime.now(timezone.utc),
        }

        if self.db:
            self.db.collection(
                "veo_recovery_metrics"
            ).add(document)

        return document
