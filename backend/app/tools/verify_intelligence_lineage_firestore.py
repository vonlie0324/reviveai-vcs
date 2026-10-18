from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.services.firestore_job_repository import FirestoreJobRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare local tenant-scoped intelligence checkpoint counts with Firestore counts without printing payloads."
    )
    parser.add_argument(
        "--namespace",
        default=None,
        help="Optional hashed tenant namespace. Defaults to all namespaces found locally.",
    )
    return parser.parse_args()


def namespaces_for(roots: list[Path], requested: str | None) -> list[str]:
    if requested:
        return [requested]
    names: set[str] = set()
    for root in roots:
        if root.exists():
            names.update(path.name for path in root.iterdir() if path.is_dir())
    return sorted(names)


def count_local_flat(root: Path, namespace: str, pattern: str) -> int:
    folder = root / namespace
    if not folder.exists():
        return 0
    return sum(1 for _ in folder.glob(pattern))


def count_local_revival(root: Path, namespace: str) -> int:
    folder = root / namespace
    if not folder.exists():
        return 0
    return sum(1 for _ in folder.glob("*/latest.json"))


def count_cloud(collection: str, namespace: str) -> int:
    repo = FirestoreJobRepository(collection)
    return sum(1 for _doc_id, _payload in repo.stream(namespace=namespace))


def main() -> int:
    args = parse_args()
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)

    analysis_root = base / "channel_analysis" / "tenants"
    dna_root = base / "content_dna_jobs" / "tenants"
    recovery_root = base / "recovery_jobs" / "tenants"
    autopilot_root = base / "autopilot_state" / "tenants"
    revival_root = base / "revival_programs" / "tenants"
    trends_root = base / "trend_directions" / "tenants"
    roots = [analysis_root, dna_root, recovery_root, autopilot_root, revival_root, trends_root]

    namespaces = namespaces_for(roots, args.namespace)
    if not namespaces:
        print("No local tenant namespaces were found.")
        return 0

    totals: dict[str, dict[str, int]] = {
        "analysis": {"local": 0, "cloud": 0, "errors": 0},
        "content_dna": {"local": 0, "cloud": 0, "errors": 0},
        "recovery": {"local": 0, "cloud": 0, "errors": 0},
        "autopilot": {"local": 0, "cloud": 0, "errors": 0},
        "revival_program": {"local": 0, "cloud": 0, "errors": 0},
        "trend_directions": {"local": 0, "cloud": 0, "errors": 0},
    }

    specs = [
        ("analysis", analysis_root, "ana_*.json", "analysis_jobs", False),
        ("content_dna", dna_root, "dna_*.json", "content_dna_jobs", False),
        ("recovery", recovery_root, "recovery_*.json", "recovery_jobs", False),
        ("autopilot", autopilot_root, "active_session.json", "autopilot_state", False),
        ("revival_program", revival_root, "", "revival_programs", True),
        ("trend_directions", trends_root, "*.json", "trend_directions", False),
    ]

    for namespace in namespaces:
        for category, root, pattern, collection, nested in specs:
            local_count = count_local_revival(root, namespace) if nested else count_local_flat(root, namespace, pattern)
            totals[category]["local"] += local_count
            try:
                totals[category]["cloud"] += count_cloud(collection, namespace)
            except Exception:
                totals[category]["errors"] += 1

    print("ReviveAI intelligence-lineage verification")
    print("------------------------------------------")
    print(f"tenant namespaces checked: {len(namespaces)}")
    print()
    print("category          local  firestore  status")
    print("----------------  -----  ---------  ------")
    all_ok = True
    for category, values in totals.items():
        local_count = values["local"]
        cloud_count = values["cloud"]
        if values["errors"]:
            status = "ERROR"
            cloud_text = "?"
            all_ok = False
        elif cloud_count >= local_count:
            status = "OK"
            cloud_text = str(cloud_count)
        else:
            status = "MISSING"
            cloud_text = str(cloud_count)
            all_ok = False
        print(f"{category:<16}  {local_count:>5}  {cloud_text:>9}  {status}")

    print()
    if all_ok:
        print("OK: Firestore contains at least all locally discovered lineage checkpoints.")
    else:
        print("WARNING: one or more lineage categories are missing data or could not be checked.")
    print("No checkpoint payloads, Firebase UIDs, tokens, or secret values were printed.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
