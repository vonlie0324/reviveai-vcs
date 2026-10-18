from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings
from app.core.tenant import tenant_namespace


SERVICE_DIRS = (
    "channel_analysis",
    "content_dna_jobs",
    "recovery_jobs",
    "production_history",
    "media_studio",
    "final_assembly",
    "audio_finishing",
    "delivery_qc",
    "delivery_packages",
    "publishing_assistant",
    "music_match",
)


def _copy_entry(source: Path, destination: Path, *, apply: bool) -> tuple[int, int]:
    if destination.exists():
        print(f"SKIP exists: {destination}")
        return (0, 1)
    print(f"{'COPY' if apply else 'WOULD COPY'} {source} -> {destination}")
    if not apply:
        return (1, 0)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return (1, 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Safely adopt pre-M2D.2.1 unscoped ReviveAI data into one authenticated tenant. "
            "Dry-run is the default; pass --apply to copy. Legacy sources are never deleted."
        )
    )
    owner = parser.add_mutually_exclusive_group(required=True)
    owner.add_argument("--uid", help="Firebase uid that should own the legacy data")
    owner.add_argument("--tenant-id", help="Trusted Firebase custom tenant_id claim for a shared organization")
    parser.add_argument("--apply", action="store_true", help="Copy data into the isolated namespace")
    args = parser.parse_args()

    logical_tenant = f"tenant:{args.tenant_id}" if args.tenant_id else f"user:{args.uid}"
    namespace = tenant_namespace(logical_tenant)
    settings = Settings()
    checkpoint_root = Path(settings.content_dna_checkpoint_dir).resolve()
    copied = 0
    skipped = 0

    print(f"Target namespace: {namespace}")
    print(f"Checkpoint root: {checkpoint_root}")

    # Service-specific stores use <service>/tenants/<namespace>/...
    for service in SERVICE_DIRS:
        service_root = checkpoint_root / service
        if not service_root.exists():
            continue
        tenant_root = service_root / "tenants" / namespace
        for source in service_root.iterdir():
            if source.name == "tenants":
                continue
            c, s = _copy_entry(source, tenant_root / source.name, apply=args.apply)
            copied += c
            skipped += s

    # Shared checkpoint-root services use <checkpoint>/tenants/<namespace>/<feature>/...
    scoped_root = checkpoint_root / "tenants" / namespace
    for feature in ("production_briefs", "audio_music_previews"):
        source_root = checkpoint_root / feature
        if not source_root.exists():
            continue
        for source in source_root.iterdir():
            c, s = _copy_entry(source, scoped_root / feature / source.name, apply=args.apply)
            copied += c
            skipped += s

    # Old Content DNA classification cache files were stored directly at checkpoint root.
    for source in checkpoint_root.glob("*.json"):
        c, s = _copy_entry(source, scoped_root / "content_dna_cache" / source.name, apply=args.apply)
        copied += c
        skipped += s

    # Creator-imported YouTube Audio Library catalog and files.
    catalog = Path(settings.audio_youtube_library_catalog_path).resolve()
    if catalog.exists():
        catalog_target = catalog.parent / "tenants" / namespace / catalog.name
        c, s = _copy_entry(catalog, catalog_target, apply=args.apply)
        copied += c
        skipped += s

    audio_root = Path(settings.audio_youtube_library_dir).resolve()
    legacy_tracks = audio_root / "tracks"
    if legacy_tracks.exists():
        target_tracks = audio_root / "tenants" / namespace / "tracks"
        for source in legacy_tracks.iterdir():
            if source.name == ".gitkeep":
                continue
            c, s = _copy_entry(source, target_tracks / source.name, apply=args.apply)
            copied += c
            skipped += s

    print()
    if args.apply:
        print(f"Migration copy complete. Copied {copied}; skipped {skipped} existing target(s).")
        print("Legacy unscoped files were intentionally left in place for rollback. M2D.2.1 ignores them at runtime.")
    else:
        print(f"Dry run complete. {copied} item(s) would be copied; {skipped} target collision(s).")
        print("Run again with --apply after confirming the Firebase uid / tenant_id is correct.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
