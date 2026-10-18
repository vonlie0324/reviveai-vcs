from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace_context
from app.models.youtube_publishing import YouTubePublication, YouTubePublishStatus
from app.services.delivery_package_service import delivery_package_store
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.revival_learning_service import LearningWorkspace
from app.services.youtube_publication_claim_service import youtube_publication_claim_service


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate v3.4 continuous-learning state and backfill publication idempotency claims.")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--namespace", default=None)
    return p.parse_args()


def as_utc(value) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def discover_namespaces(base: Path) -> set[str]:
    out: set[str] = set()
    for root in [base / "revival_learning" / "tenants", base / "youtube_publishing" / "tenants"]:
        if root.exists():
            out.update(path.name for path in root.iterdir() if path.is_dir())
    try:
        client = get_runtime_firestore_client()
        for collection_name in ("youtube_publications", "revival_learning"):
            for snap in client.collection_group(collection_name).stream():
                tenant_doc = snap.reference.parent.parent
                if tenant_doc:
                    out.add(str(tenant_doc.id))
    except Exception:
        pass
    return out


def choose_canonical(publications: list[YouTubePublication], current_publication_id: str | None) -> YouTubePublication:
    rank = {
        YouTubePublishStatus.PUBLISHED: 4,
        YouTubePublishStatus.SCHEDULED: 3,
        YouTubePublishStatus.UPLOADING: 2,
        YouTubePublishStatus.FAILED: 1,
    }
    return max(
        publications,
        key=lambda p: (
            1 if p.publication_id == current_publication_id else 0,
            rank.get(p.status, 0),
            1 if p.youtube_video_id else 0,
            as_utc(p.updated_at),
        ),
    )


def main() -> int:
    args = parse_args()
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)
    namespaces = sorted(discover_namespaces(base))
    if args.namespace:
        namespaces = [ns for ns in namespaces if ns == args.namespace]

    learning_discovered = learning_valid = learning_written = 0
    publications_seen = publication_updates = 0
    claim_writes = duplicate_groups = superseded_records = errors = 0

    learning_repo = FirestoreJobRepository("revival_learning")
    publication_repo = FirestoreJobRepository("youtube_publications")
    autopilot_repo = FirestoreJobRepository("autopilot_state")

    for namespace in namespaces:
        # Local learning workspace -> durable Firestore.
        local_learning_dir = base / "revival_learning" / "tenants" / namespace
        if local_learning_dir.exists():
            for path in sorted(local_learning_dir.glob("*.json")):
                learning_discovered += 1
                try:
                    workspace = LearningWorkspace.model_validate_json(path.read_text(encoding="utf-8"))
                    learning_valid += 1
                    existing = learning_repo.load(workspace.program_id, namespace=namespace)
                    should_write = True
                    if existing:
                        try:
                            cloud = LearningWorkspace.model_validate(existing)
                            should_write = as_utc(workspace.updated_at) > as_utc(cloud.updated_at)
                        except Exception:
                            should_write = True
                    if should_write and args.apply:
                        learning_repo.save(workspace.program_id, workspace.model_dump(mode="json"), namespace=namespace)
                        learning_written += 1
                except Exception:
                    errors += 1

        try:
            raw_publications = list(publication_repo.stream(namespace=namespace))
        except Exception:
            errors += 1
            continue

        publications: list[YouTubePublication] = []
        for _, payload in raw_publications:
            try:
                publications.append(YouTubePublication.model_validate(payload))
            except Exception:
                errors += 1
        publications_seen += len(publications)

        current_publication_id = None
        try:
            state = autopilot_repo.load("active_session", namespace=namespace) or {}
            session = state.get("session") if isinstance(state, dict) else {}
            if isinstance(session, dict):
                current_publication_id = str(session.get("currentPublicationId") or "") or None
        except Exception:
            pass

        groups: dict[str, list[YouTubePublication]] = defaultdict(list)
        original_fingerprints: dict[str, str | None] = {}
        with tenant_namespace_context(namespace):
            for pub in publications:
                try:
                    package = delivery_package_store.get(pub.package_id)
                    fingerprint = youtube_publication_claim_service.master_fingerprint(
                        audio_job_id=package.audio_job_id,
                        audio_version=package.audio_version,
                        delivery_asset_id=package.delivery_asset_id,
                    )
                    original_fingerprints[pub.publication_id] = pub.master_fingerprint
                    pub.master_fingerprint = fingerprint
                    groups[fingerprint].append(pub)
                except Exception:
                    errors += 1

            for fingerprint, group in groups.items():
                canonical = choose_canonical(group, current_publication_id)
                if len(group) > 1:
                    duplicate_groups += 1
                for pub in group:
                    changed = False
                    if original_fingerprints.get(pub.publication_id) != fingerprint:
                        pub.master_fingerprint = fingerprint
                        changed = True
                    if pub.publication_id == canonical.publication_id:
                        if pub.superseded_by_publication_id is not None:
                            pub.superseded_by_publication_id = None
                            pub.superseded_at = None
                            changed = True
                    else:
                        superseded_records += 1
                        if pub.superseded_by_publication_id != canonical.publication_id:
                            pub.superseded_by_publication_id = canonical.publication_id
                            pub.superseded_at = datetime.now(timezone.utc)
                            changed = True
                    if changed:
                        publication_updates += 1
                        if args.apply:
                            publication_repo.save(pub.publication_id, pub.model_dump(mode="json"), namespace=namespace)

                if args.apply:
                    get_runtime_firestore_client().collection("reviveai_tenants").document(namespace).collection("youtube_publication_claims").document(fingerprint).set(
                        {
                            "master_fingerprint": fingerprint,
                            "publication_id": canonical.publication_id,
                            "status": "PERSISTED",
                            "claim_owner": "",
                            "lease_expires_at": datetime.now(timezone.utc),
                            "persisted_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                            "migration": "v3.4",
                        },
                        merge=True,
                    )
                    claim_writes += 1

    print("ReviveAI v3.4 continuous-autonomy migration")
    print("-------------------------------------------")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"tenant namespaces checked : {len(namespaces)}")
    print(f"learning workspaces found  : {learning_discovered}")
    print(f"learning workspaces valid  : {learning_valid}")
    print(f"learning workspaces written: {learning_written if args.apply else 0}")
    print(f"publications inspected     : {publications_seen}")
    print(f"publication updates        : {publication_updates}")
    print(f"publication claims written : {claim_writes if args.apply else 0}")
    print(f"duplicate master groups    : {duplicate_groups}")
    print(f"legacy records superseded  : {superseded_records}")
    print(f"errors                     : {errors}")
    print()
    print("No Firebase UIDs, titles, video IDs, upload-session URLs, tokens, prompts, or secret values were printed.")
    if not args.apply:
        print("Run again with --apply after reviewing this dry run.")
    if duplicate_groups:
        print("Duplicate master groups are canonicalized inside ReviveAI only; this tool never deletes a YouTube video.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
