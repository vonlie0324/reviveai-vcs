"""
ReviveAI Phase 2E - Production Cost Enrichment Migration

Purpose:
- Enrich migrated LEGACY_IMPORTED production records.
- Resolve production titles.
- Extract cost information from checkpoint JSON files.
- Update reviveai-prod production_cost_transactions.

Run:
    python scripts/enrich_production_costs.py
"""

from pathlib import Path
import json
from datetime import datetime, timezone

from google.cloud import firestore
from app.core.config import get_settings


DATABASE = "reviveai-prod"


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def first_value(data, keys):
    for key in keys:
        value = data.get(key)
        if value:
            return value
    return None


def extract_title(data, fallback):
    return (
        first_value(
            data,
            [
                "title",
                "name",
                "production_name",
                "productionTitle",
            ],
        )
        or data.get("brief", {}).get("title")
        or fallback
    )


def extract_cost(data):
    estimated = first_value(
        data,
        [
            "estimated_cost",
            "estimatedCost",
            "cost_estimate",
        ],
    )

    actual = first_value(
        data,
        [
            "actual_cost",
            "actualCost",
            "cost",
        ],
    )

    return estimated, actual


def collect_files(root):
    folders = [
        "production_history",
        "media_studio",
        "final_assembly",
        "audio_finishing",
        "delivery_qc",
    ]

    for folder in folders:
        path = root / folder
        if not path.exists():
            continue

        for file in path.rglob("*.json"):
            yield file


def enrich():
    settings = get_settings()
    root = Path(settings.content_dna_checkpoint_dir).resolve()

    print("Checkpoint root:")
    print(root)

    db = firestore.Client(database=DATABASE)

    updated = 0
    skipped = 0

    for file in collect_files(root):
        payload = read_json(file)

        production_id = (
            payload.get("production_id")
            or payload.get("id")
            or payload.get("job_id")
        )

        if not production_id:
            continue

        title = extract_title(payload, production_id)

        production_ref = (
            db.collection("productions")
            .document(production_id)
        )

        production_ref.set(
            {
                "title": title,
                "updated_at": datetime.now(timezone.utc),
            },
            merge=True,
        )

        estimated, actual = extract_cost(payload)

        transaction_ref = (
            db.collection("production_cost_transactions")
            .document(f"migration_{production_id}")
        )

        if transaction_ref.get().exists:
            transaction_ref.set(
                {
                    "productionTitle": title,
                    "estimatedCost": estimated or 0,
                    "actualCost": actual or 0,
                    "status": "LEGACY_ENRICHED",
                    "updatedAt": datetime.now(timezone.utc),
                },
                merge=True,
            )
            updated += 1
        else:
            skipped += 1

    print("")
    print("Enrichment completed")
    print("--------------------")
    print("Updated:", updated)
    print("Skipped:", skipped)


if __name__ == "__main__":
    enrich()
