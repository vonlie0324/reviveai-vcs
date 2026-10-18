from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.models.production_brief import ProductionBriefJob
from app.services.firestore_job_repository import FirestoreJobRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate existing tenant-scoped local ProductionBriefJob checkpoints "
            "into the configured Firestore database. No production content is printed."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write documents to Firestore. Without this flag the command is a dry run.",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Optional hashed tenant namespace to migrate. Defaults to all local tenant folders.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    root = Path(settings.content_dna_checkpoint_dir) / "production_history" / "tenants"
    repository = FirestoreJobRepository("production_brief_jobs")

    if not root.exists():
        print("No local tenant-scoped production history directory was found.")
        return 0

    namespaces = [path for path in sorted(root.iterdir()) if path.is_dir()]
    if args.namespace:
        namespaces = [path for path in namespaces if path.name == args.namespace]

    discovered = 0
    valid = 0
    written = 0
    invalid = 0

    for namespace_dir in namespaces:
        for path in sorted(namespace_dir.glob("production_*.json")):
            discovered += 1
            try:
                job = ProductionBriefJob.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception:
                invalid += 1
                continue

            valid += 1
            if args.apply:
                repository.save(
                    job.job_id,
                    job.model_dump(mode="json"),
                    namespace=namespace_dir.name,
                )
                written += 1

    print("ReviveAI production-history migration")
    print("-----------------------------------")
    print(f"mode       : {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"discovered : {discovered}")
    print(f"valid      : {valid}")
    print(f"invalid    : {invalid}")
    print(f"written    : {written}")
    print("No production payloads or secret values were printed.")

    if not args.apply and valid:
        print("Run again with --apply to persist the valid checkpoints to Firestore.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
