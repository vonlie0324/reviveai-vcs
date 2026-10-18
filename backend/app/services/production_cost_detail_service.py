from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from app.core.firebase_clients import get_firestore_client


class ProductionCostDetailService:
    """
    Detailed production cost view built on reviveai-prod Firestore data.
    """

    def __init__(self):
        self.db = get_firestore_client()

    def get_detail(self, production_id: str) -> Dict[str, Any]:
        transactions = []

        docs = (
            self.db.collection("production_cost_transactions")
            .where("productionId", "==", production_id)
            .stream()
        )

        estimated = 0.0
        actual = 0.0

        for doc in docs:
            data = doc.to_dict() or {}
            estimated += float(data.get("estimatedCost", 0) or 0)
            actual += float(data.get("actualCost", 0) or 0)

            transactions.append({
                "id": doc.id,
                "status": data.get("status"),
                "estimated_cost": data.get("estimatedCost", 0),
                "actual_cost": data.get("actualCost", 0),
                "created_at": data.get("createdAt"),
            })

        variance = actual - estimated

        return {
            "production_id": production_id,
            "summary": {
                "estimated_cost": estimated,
                "actual_cost": actual,
                "variance": variance,
                "health": "HEALTHY" if variance <= 0 else "WARNING",
            },
            "transactions": transactions,
        }

    def get_timeline(self, production_id: str) -> Dict[str, Any]:
        detail = self.get_detail(production_id)

        events: List[Dict[str, Any]] = []

        for item in detail["transactions"]:
            events.append({
                "type": item.get("status"),
                "timestamp": item.get("created_at"),
                "cost": item.get("actual_cost") or item.get("estimated_cost"),
            })

        return {
            "production_id": production_id,
            "events": events,
        }
