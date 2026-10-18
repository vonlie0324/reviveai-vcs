"""
ReviveAI Phase 2E - Checkpoint-aware production migration

Migrates legacy checkpoint-based production data into Firestore:
Database: reviveai-prod

Run:
    python scripts/migrate_previous_productions.py
"""

from pathlib import Path
import json
from datetime import datetime, timezone

from google.cloud import firestore

from app.core.config import get_settings


FIRESTORE_DATABASE = "reviveai-prod"


def safe_read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_production_id(payload: dict, path: Path) -> str:
    return (
        payload.get("production_id")
        or payload.get("job_id")
        or payload.get("id")
        or path.stem
    )


def migrate():
    settings = get_settings()

    checkpoint_root = Path(
        settings.content_dna_checkpoint_dir
    ).resolve()

    print("Checkpoint root:")
    print(checkpoint_root)

    if not checkpoint_root.exists():
        print("Checkpoint directory does not exist.")
        return

    db = firestore.Client(
        database=FIRESTORE_DATABASE
    )

    folders = [
        "production_history",
        "media_studio",
        "final_assembly",
        "audio_finishing",
        "delivery_qc",
    ]

    found = 0
    migrated = 0
    skipped = 0

    for folder in folders:
        source = checkpoint_root / folder

        print("")
        print("Scanning:", folder)

        if not source.exists():
            print("  Not found")
            continue

        for file in source.rglob("*.json"):
            found += 1

            payload = safe_read_json(file)

            production_id = find_production_id(
                payload,
                file
            )

            production_ref = (
                db.collection("productions")
                .document(production_id)
            )

            if production_ref.get().exists:
                skipped += 1
                continue

            production_ref.set({
                "production_id": production_id,
                "source": "checkpoint_migration",
                "source_folder": folder,
                "source_file": str(file),
                "migrated_at": datetime.now(
                    timezone.utc
                ),
            })

            transaction_ref = (
                db.collection(
                    "production_cost_transactions"
                )
                .document(
                    f"migration_{production_id}"
                )
            )

            if not transaction_ref.get().exists:
                transaction_ref.set({
                    "productionId": production_id,
                    "estimatedCost": None,
                    "actualCost": None,
                    "status": "LEGACY_IMPORTED",
                    "source": "checkpoint_migration",
                    "createdAt": datetime.now(
                        timezone.utc
                    ),
                })

            migrated += 1

    print("")
    print("Migration completed")
    print("-------------------")
    print("Found:", found)
    print("Migrated:", migrated)
    print("Skipped:", skipped)


if __name__ == "__main__":
    migrate()
