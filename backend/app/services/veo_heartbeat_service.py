from datetime import datetime, timezone


class VeoHeartbeatService:
    """
    Updates operation heartbeat while polling long-running Veo jobs.
    """

    def __init__(self, db=None):
        self.db = db

    def heartbeat(self, operation_id):
        if not self.db:
            return

        self.db.collection(
            "veo_operations"
        ).document(operation_id).update({
            "lastHeartbeat": datetime.now(timezone.utc),
            "updatedAt": datetime.now(timezone.utc),
        })
