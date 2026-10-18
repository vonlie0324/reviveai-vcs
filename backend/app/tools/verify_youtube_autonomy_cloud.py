from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings
from app.core.tenant import tenant_scoped_root
from app.models.youtube_publishing import YouTubePublication, YouTubePerformanceSnapshot
from app.services.youtube_publishing_service import youtube_publishing_service


def main() -> int:
    settings = get_settings()
    root = tenant_scoped_root(Path(settings.content_dna_checkpoint_dir) / "youtube_publishing")
    pub_dir = root / "publications"
    local_connection = int((root / "oauth.json").exists())
    cloud_connection = int(youtube_publishing_service._connections.load("connection") is not None)
    local_pubs: set[str] = set()
    local_snaps: set[str] = set()
    if pub_dir.exists():
        for path in pub_dir.glob("*.json"):
            if path.name.endswith(".snapshots.json"):
                continue
            try:
                pub = YouTubePublication.model_validate_json(path.read_text(encoding="utf-8"))
                local_pubs.add(pub.publication_id)
            except Exception:
                pass
        for path in pub_dir.glob("*.snapshots.json"):
            pid = path.name.removesuffix(".snapshots.json")
            try:
                for row in json.loads(path.read_text(encoding="utf-8")):
                    snap = YouTubePerformanceSnapshot.model_validate(row)
                    local_snaps.add(f"{pid}:{snap.checkpoint}")
            except Exception:
                pass
    cloud_pubs = {doc_id for doc_id, _ in youtube_publishing_service._publications.stream()}
    cloud_snaps = {doc_id for doc_id, _ in youtube_publishing_service._snapshots.stream()}
    missing_pubs = local_pubs - cloud_pubs
    missing_snaps = local_snaps - cloud_snaps
    ok = (not local_connection or cloud_connection) and not missing_pubs and not missing_snaps

    print("ReviveAI YouTube autonomy cloud verification")
    print("-------------------------------------------")
    print(f"connection local/cloud : {local_connection}/{cloud_connection}")
    print(f"publications local/cloud: {len(local_pubs)}/{len(cloud_pubs)}")
    print(f"snapshots local/cloud   : {len(local_snaps)}/{len(cloud_snaps)}")
    print(f"missing publications    : {len(missing_pubs)}")
    print(f"missing snapshots       : {len(missing_snaps)}")
    print(f"autonomous publish flag : {settings.autopilot_autonomous_publish_enabled}")
    print(f"final approval flag     : {settings.autopilot_autonomous_final_approval_enabled}")
    print("OK: YouTube autonomy state is cloud-durable." if ok else "FAILED: migrate/repair the missing YouTube autonomy state before enabling unattended publishing.")
    print("No refresh tokens, OAuth state, publication ids, video ids, titles, prompts, or secret values were printed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
