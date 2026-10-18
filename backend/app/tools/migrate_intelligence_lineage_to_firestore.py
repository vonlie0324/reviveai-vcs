from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings
from app.models.content_dna import ContentDnaJob
from app.models.recovery import RecoveryJob
from app.models.revival_program import RevivalProgram
from app.models.trend_direction import TrendDirectionSet
from app.models.youtube import AnalysisJob
from app.services.autopilot_state_service import AutopilotStateRecord
from app.services.firestore_job_repository import FirestoreJobRepository


ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass
class Stats:
    discovered: int = 0
    valid: int = 0
    invalid: int = 0
    would_write: int = 0
    written: int = 0
    cloud_newer_skipped: int = 0
    cloud_current_skipped: int = 0
    errors: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate tenant-scoped ReviveAI channel intelligence checkpoints into "
            "the configured Firestore database. Payloads and user identifiers are never printed."
        )
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write eligible local checkpoints to Firestore. Without this flag the command is a dry run.",
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Optional hashed tenant namespace. Defaults to every local tenant namespace.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow a local checkpoint to overwrite a newer Firestore document.",
    )
    return parser.parse_args()


def as_utc(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def model_timestamp(item: BaseModel) -> datetime:
    if isinstance(item, AutopilotStateRecord):
        return as_utc(item.saved_at)
    if isinstance(item, TrendDirectionSet):
        return as_utc(item.generated_at)
    value = getattr(item, "updated_at", None) or getattr(item, "created_at", None)
    return as_utc(value)


def process_file(
    *,
    path: Path,
    namespace: str,
    repository: FirestoreJobRepository,
    validator: Callable[[str], ModelT],
    document_id: Callable[[ModelT], str],
    args: argparse.Namespace,
    stats: Stats,
) -> None:
    stats.discovered += 1
    try:
        item = validator(path.read_text(encoding="utf-8"))
    except Exception:
        stats.invalid += 1
        return

    stats.valid += 1
    item_id = document_id(item)

    try:
        local_payload = item.model_dump(mode="json")
        existing_payload = repository.load(item_id, namespace=namespace)
        existing = None
        if existing_payload:
            try:
                existing = item.__class__.model_validate(existing_payload)
            except Exception:
                existing = None

        if existing_payload == local_payload:
            stats.cloud_current_skipped += 1
            return

        if existing is not None and not args.force and model_timestamp(existing) > model_timestamp(item):
            stats.cloud_newer_skipped += 1
            return

        stats.would_write += 1
        if args.apply:
            repository.save(item_id, local_payload, namespace=namespace)
            stats.written += 1
    except Exception:
        stats.errors += 1


def tenant_dirs(root: Path, requested: Optional[str]) -> list[Path]:
    if not root.exists():
        return []
    result = [path for path in sorted(root.iterdir()) if path.is_dir()]
    if requested:
        result = [path for path in result if path.name == requested]
    return result


def main() -> int:
    args = parse_args()
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)

    categories: dict[str, Stats] = {
        "analysis": Stats(),
        "content_dna": Stats(),
        "recovery": Stats(),
        "autopilot": Stats(),
        "revival_program": Stats(),
        "trend_directions": Stats(),
    }

    specs = [
        (
            "analysis",
            base / "channel_analysis" / "tenants",
            "ana_*.json",
            FirestoreJobRepository("analysis_jobs"),
            AnalysisJob.model_validate_json,
            lambda item: item.job_id,
        ),
        (
            "content_dna",
            base / "content_dna_jobs" / "tenants",
            "dna_*.json",
            FirestoreJobRepository("content_dna_jobs"),
            ContentDnaJob.model_validate_json,
            lambda item: item.job_id,
        ),
        (
            "recovery",
            base / "recovery_jobs" / "tenants",
            "recovery_*.json",
            FirestoreJobRepository("recovery_jobs"),
            RecoveryJob.model_validate_json,
            lambda item: item.job_id,
        ),
        (
            "autopilot",
            base / "autopilot_state" / "tenants",
            "active_session.json",
            FirestoreJobRepository("autopilot_state"),
            AutopilotStateRecord.model_validate_json,
            lambda _item: "active_session",
        ),
        (
            "trend_directions",
            base / "trend_directions" / "tenants",
            "*.json",
            FirestoreJobRepository("trend_directions"),
            TrendDirectionSet.model_validate_json,
            lambda item: "".join(ch for ch in item.recovery_job_id if ch.isalnum() or ch in {"-", "_"}),
        ),
    ]

    for category, root, pattern, repository, validator, document_id in specs:
        for namespace_dir in tenant_dirs(root, args.namespace):
            for path in sorted(namespace_dir.glob(pattern)):
                process_file(
                    path=path,
                    namespace=namespace_dir.name,
                    repository=repository,
                    validator=validator,
                    document_id=document_id,
                    args=args,
                    stats=categories[category],
                )

    # Revival programs use one subdirectory per Recovery job.
    revival_root = base / "revival_programs" / "tenants"
    revival_repo = FirestoreJobRepository("revival_programs")
    for namespace_dir in tenant_dirs(revival_root, args.namespace):
        for path in sorted(namespace_dir.glob("*/latest.json")):
            process_file(
                path=path,
                namespace=namespace_dir.name,
                repository=revival_repo,
                validator=RevivalProgram.model_validate_json,
                document_id=lambda item: item.recovery_job_id,
                args=args,
                stats=categories["revival_program"],
            )

    print("ReviveAI intelligence-lineage migration")
    print("---------------------------------------")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"overwrite newer cloud data: {'YES' if args.force else 'NO'}")
    print()
    print("category          discovered  valid  write  cloud-current  skipped-newer  invalid  errors")
    print("----------------  ----------  -----  -----  -------------  -------------  -------  ------")
    for name, stats in categories.items():
        print(
            f"{name:<16}  {stats.discovered:>10}  {stats.valid:>5}  "
            f"{(stats.written if args.apply else stats.would_write):>5}  "
            f"{stats.cloud_current_skipped:>13}  {stats.cloud_newer_skipped:>13}  "
            f"{stats.invalid:>7}  {stats.errors:>6}"
        )

    totals = Stats()
    for stats in categories.values():
        for field in totals.__dataclass_fields__:
            setattr(totals, field, getattr(totals, field) + getattr(stats, field))

    print()
    print(f"total discovered : {totals.discovered}")
    print(f"total valid      : {totals.valid}")
    print(f"total written    : {totals.written if args.apply else 0}")
    print(f"would write      : {totals.would_write}")
    print(f"cloud current    : {totals.cloud_current_skipped}")
    print(f"skipped newer    : {totals.cloud_newer_skipped}")
    print(f"invalid          : {totals.invalid}")
    print(f"errors           : {totals.errors}")
    print()
    print("No checkpoint payloads, Firebase UIDs, tokens, or secret values were printed.")

    if not args.apply and totals.would_write:
        print("Run again with --apply to persist eligible checkpoints to Firestore.")

    return 1 if totals.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
