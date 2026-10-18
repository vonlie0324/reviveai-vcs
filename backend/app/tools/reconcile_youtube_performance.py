"""Repair YouTube performance for one explicitly selected tenant.

Run from backend with the existing environment/ADC configuration. The default
is a dry run. This tool never uploads, generates, or republishes videos.
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.tenant import tenant_context, tenant_namespace_context
from app.models.youtube_publishing import YouTubePublishStatus
from app.services.youtube_publishing_service import youtube_publishing_service


async def reconcile(args) -> int:
    context = tenant_context(args.tenant_id) if args.tenant_id else tenant_namespace_context(args.tenant_namespace)
    checked = repaired = failed = pending = clocks = 0
    with context:
        publications = youtube_publishing_service.list()
        if args.publication_id:
            publications = [p for p in publications if p.publication_id == args.publication_id]
            if not publications:
                print("No publication found for the selected tenant and publication id.")
                return 1
        for pub in publications:
            if pub.superseded_by_publication_id or pub.status != YouTubePublishStatus.PUBLISHED or not pub.public_confirmed_at:
                continue
            needs_clock_repair = pub.release_clock_version < 2 or not pub.public_release_at
            if needs_clock_repair:
                clocks += 1
                if args.apply:
                    try:
                        pub = await youtube_publishing_service.reconcile_remote_status(pub.publication_id)
                    except Exception as exc:
                        failed += 1
                        print(f"Release timing could not be verified ({type(exc).__name__}); inspect the backend logs.")
                        continue
                    if pub.status != YouTubePublishStatus.PUBLISHED:
                        continue
            snapshots = youtube_publishing_service.snapshots(pub.publication_id)
            targets = [s.checkpoint for s in snapshots if youtube_publishing_service._needs_reconciliation(s)]
            due = youtube_publishing_service.due_checkpoint(pub)
            if due and due not in targets:
                targets.append(due)
            if not snapshots and not targets:
                targets = [None]
            # Old history is repaired first; the mature record supplies learning.
            for checkpoint in targets:
                checked += 1
                if not args.apply:
                    continue
                try:
                    snap = await youtube_publishing_service.refresh_analytics(pub.publication_id, checkpoint=checkpoint)
                    repaired += 1
                    pending += int(snap.analytics_status != "READY" or not snap.statistics_ready)
                except Exception as exc:
                    failed += 1
                    print(f"A checkpoint could not be repaired ({type(exc).__name__}); inspect the backend logs.")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"Checkpoints eligible: {checked}; refreshed: {repaired}; pending: {pending}; failed: {failed}")
    print(f"Publications requiring release-clock verification: {clocks}")
    if not args.apply:
        print("Repeat the same command with --apply to fetch fresh API evidence.")
        if clocks:
            print("Due checkpoints will be recalculated after YouTube release timing is verified in APPLY mode.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--tenant-id", help="Exact Firebase Auth UID for the affected signed-in account.")
    scope.add_argument("--tenant-namespace", help="Existing 32-character tenant namespace from Firestore.")
    parser.add_argument("--publication-id", help="Optional publication to repair within this tenant.")
    parser.add_argument("--apply", action="store_true", help="Fetch and persist evidence; default is dry run.")
    return asyncio.run(reconcile(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
