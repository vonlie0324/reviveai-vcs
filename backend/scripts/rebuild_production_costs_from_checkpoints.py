"""
ReviveAI Phase 2E - Rebuild Production Costs From Checkpoints

Reads:
.reviveai_checkpoints/media_studio/**/job.json

Extracts:
- production id
- media job id
- Veo model
- provider operation name
- estimated_cost_usd

Updates Firestore:
reviveai-prod / production_cost_transactions

Run:
python -m scripts.rebuild_production_costs_from_checkpoints
"""

from pathlib import Path
import json
import sys
from datetime import datetime, timezone

from google.cloud import firestore
from app.core.config import get_settings


DATABASE = "reviveai-prod"


def add_backend_root():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_values(obj, results=None):
    if results is None:
        results = []

    if isinstance(obj, dict):
        if (
            "provider_operation_name" in obj
            or "estimated_cost_usd" in obj
        ):
            results.append(obj)

        for value in obj.values():
            find_values(value, results)

    elif isinstance(obj, list):
        for item in obj:
            find_values(item, results)

    return results


def rebuild():
    add_backend_root()

    settings = get_settings()
    root = Path(settings.content_dna_checkpoint_dir).resolve()

    print("Checkpoint root:")
    print(root)

    db = firestore.Client(database=DATABASE)

    source = root / "media_studio"

    if not source.exists():
        print("media_studio folder not found")
        return

    updated = 0

    for job_file in source.rglob("job.json"):
        data = load_json(job_file)

        production_id = data.get("production_brief_job_id")
        media_job_id = data.get("job_id")

        source_snapshot = (
            data.get("result", {})
            .get("source_snapshot", {})
        )

        title = source_snapshot.get("working_title")
        channel_id = data.get("channel_id")
        created_at = data.get("created_at")

        if not production_id:
            continue

        model = (
            data.get("detail", {}).get("video_model")
            or data.get("video_model")
        )

        operations = find_values(data)

        for operation in operations:
            estimated = operation.get("estimated_cost_usd")

            if estimated is None:
                continue

            provider_operation = operation.get(
                "provider_operation_name"
            )

            doc_id = f"veo_{media_job_id}"

            db.collection(
                "production_cost_transactions"
            ).document(doc_id).set(
                {
                    "productionId": production_id,
                    "title": title,
                    "productionTitle": title,
                    "channelId": channel_id,
                    "createdAt": created_at,
                    "mediaJobId": media_job_id,
                    "provider": "google_veo",
                    "model": operation.get("model") or model,
                    "providerOperationName": provider_operation,
                    "estimatedCostUsd": estimated,
                    "status": "CHECKPOINT_RECOVERED",
                    "source": "checkpoint_rebuild",
                    "updatedAt": datetime.now(timezone.utc),
                },
                merge=True,
            )

            updated += 1

    print("")
    print("Cost rebuild completed")
    print("----------------------")
    print("Updated:", updated)


if __name__ == "__main__":
    rebuild()
