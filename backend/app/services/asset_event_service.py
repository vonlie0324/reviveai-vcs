from datetime import datetime, timezone
from uuid import uuid4

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class AssetEventService:
    def __init__(self):
        self.db = firestore.Client() if firestore else None

    def log(self, production_id, event_type, metadata=None):
        event = {
            "id": f"event_{uuid4().hex}",
            "productionId": production_id,
            "eventType": event_type,
            "metadata": metadata or {},
            "createdAt": datetime.now(timezone.utc),
        }

        if self.db:
            self.db.collection("asset_events").document(
                event["id"]
            ).set(event)

        return event
