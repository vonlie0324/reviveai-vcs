from datetime import datetime, timezone
from uuid import uuid4

try:
    from google.cloud import firestore
except Exception:
    firestore = None


class AssetRegistryService:
    """Firestore-backed asset registry.

    Stores generated assets as immutable versions.
    """

    def __init__(self):
        self.db = firestore.Client() if firestore else None

    def create_asset(self, production_id: str, data: dict):
        asset_id = f"asset_{uuid4().hex}"

        record = {
            "assetId": asset_id,
            "productionId": production_id,
            "status": data.get("status", "GENERATING"),
            "type": data.get("type"),
            "version": data.get("version", 1),
            "generation": data.get("generation", {}),
            "createdAt": datetime.now(timezone.utc),
        }

        if self.db:
            self.db.collection("productions").document(
                production_id
            ).collection("assets").document(asset_id).set(record)

        return record

    def update_status(self, production_id, asset_id, status):
        if self.db:
            self.db.collection("productions").document(
                production_id
            ).collection("assets").document(asset_id).update({
                "status": status,
                "updatedAt": datetime.now(timezone.utc),
            })
