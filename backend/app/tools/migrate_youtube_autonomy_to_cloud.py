from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.models.youtube_publishing import YouTubePublication, YouTubePerformanceSnapshot
from app.services.youtube_publishing_service import youtube_publishing_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate local YouTube autonomy state into Firestore.")
    parser.add_argument("--apply", action="store_true", help="Write to Firestore. Default is dry-run.")
    args = parser.parse_args()
    settings = get_settings()
    root = tenant_scoped_root(Path(settings.content_dna_checkpoint_dir) / "youtube_publishing")
    token_path = root / "oauth.json"
    pub_dir = root / "publications"

    connection = 0
    publications = 0
    snapshots = 0
    invalid = 0
    errors = 0

    if token_path.exists():
        try:
            payload = json.loads(token_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("refresh_token"):
                connection = 1
                if args.apply:
                    youtube_publishing_service._connections.save("connection", payload)
            else:
                invalid += 1
        except Exception:
            invalid += 1

    if pub_dir.exists():
        for path in pub_dir.glob("*.json"):
            if path.name.endswith(".snapshots.json"):
                continue
            try:
                pub = YouTubePublication.model_validate_json(path.read_text(encoding="utf-8"))
                publications += 1
                if args.apply:
                    youtube_publishing_service._publications.save(pub.publication_id, pub.model_dump(mode="json"))
            except Exception:
                invalid += 1
        for path in pub_dir.glob("*.snapshots.json"):
            publication_id = path.name.removesuffix(".snapshots.json")
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(rows, list):
                    raise ValueError("snapshot payload is not a list")
                for row in rows:
                    snap = YouTubePerformanceSnapshot.model_validate(row)
                    snapshots += 1
                    if args.apply:
                        youtube_publishing_service._snapshots.save(
                            f"{publication_id}:{snap.checkpoint}",
                            {"publication_id": publication_id, "snapshot": snap.model_dump(mode="json")},
                        )
            except Exception:
                invalid += 1

    if args.apply and publications:
        try:
            from app.services.youtube_autonomy_queue import youtube_autonomy_queue
            youtube_autonomy_queue.sync(active=True, next_run_seconds=0)
        except Exception:
            errors += 1

    print("ReviveAI YouTube autonomy cloud migration")
    print("----------------------------------------")
    print(f"mode             : {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"connection       : {connection}")
    print(f"publications     : {publications}")
    print(f"snapshots        : {snapshots}")
    print(f"invalid          : {invalid}")
    print(f"errors           : {errors}")
    print("No refresh tokens, OAuth state, publication ids, video ids, titles, prompts, or secret values were printed.")
    if not args.apply:
        print("Run again with --apply after reviewing this dry run.")
    return 0 if invalid == 0 and errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
