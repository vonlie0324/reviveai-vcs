from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from app.core.config import get_settings
from app.core.firebase_clients import get_runtime_firestore_client
from app.core.tenant import tenant_namespace_context
from app.models.youtube_publishing import YouTubePublication
from app.services.delivery_package_service import delivery_package_store
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.revival_learning_service import LearningWorkspace
from app.services.youtube_publication_claim_service import youtube_publication_claim_service


def main() -> int:
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)
    publication_repo = FirestoreJobRepository("youtube_publications")
    learning_repo = FirestoreJobRepository("revival_learning")

    namespaces: set[str] = set()
    try:
        for snap in get_runtime_firestore_client().collection_group("youtube_publications").stream():
            tenant_doc = snap.reference.parent.parent
            if tenant_doc:
                namespaces.add(str(tenant_doc.id))
        for snap in get_runtime_firestore_client().collection_group("revival_learning").stream():
            tenant_doc = snap.reference.parent.parent
            if tenant_doc:
                namespaces.add(str(tenant_doc.id))
    except Exception:
        pass
    local_root = base / "revival_learning" / "tenants"
    if local_root.exists():
        namespaces.update(p.name for p in local_root.iterdir() if p.is_dir())

    publications = claims_missing = duplicate_groups = duplicate_unsuppressed = 0
    learning_cloud = learning_invalid = errors = 0

    for namespace in sorted(namespaces):
        try:
            for _, payload in learning_repo.stream(namespace=namespace):
                try:
                    LearningWorkspace.model_validate(payload)
                    learning_cloud += 1
                except Exception:
                    learning_invalid += 1
        except Exception:
            errors += 1

        grouped: dict[str, list[YouTubePublication]] = defaultdict(list)
        with tenant_namespace_context(namespace):
            try:
                rows = list(publication_repo.stream(namespace=namespace))
            except Exception:
                errors += 1
                continue
            for _, payload in rows:
                try:
                    pub = YouTubePublication.model_validate(payload)
                    publications += 1
                    package = delivery_package_store.get(pub.package_id)
                    fingerprint = youtube_publication_claim_service.master_fingerprint(
                        audio_job_id=package.audio_job_id,
                        audio_version=package.audio_version,
                        delivery_asset_id=package.delivery_asset_id,
                    )
                    grouped[fingerprint].append(pub)
                except Exception:
                    errors += 1

            tenant_ref = get_runtime_firestore_client().collection("reviveai_tenants").document(namespace)
            for fingerprint, group in grouped.items():
                if len(group) > 1:
                    duplicate_groups += 1
                    active = [p for p in group if not p.superseded_by_publication_id]
                    if len(active) != 1:
                        duplicate_unsuppressed += 1
                claim = tenant_ref.collection("youtube_publication_claims").document(fingerprint).get()
                if not claim.exists:
                    claims_missing += 1
                    continue
                data = claim.to_dict() or {}
                canonical = str(data.get("publication_id") or "")
                if canonical not in {p.publication_id for p in group}:
                    claims_missing += 1

    print("ReviveAI v3.4 continuous-autonomy verification")
    print("----------------------------------------------")
    print(f"tenant namespaces checked : {len(namespaces)}")
    print(f"cloud learning workspaces : {learning_cloud}")
    print(f"invalid learning payloads : {learning_invalid}")
    print(f"publications checked      : {publications}")
    print(f"duplicate master groups   : {duplicate_groups}")
    print(f"unsuppressed duplicate groups: {duplicate_unsuppressed}")
    print(f"missing publication claims: {claims_missing}")
    print(f"errors                    : {errors}")
    print()
    ok = learning_invalid == 0 and duplicate_unsuppressed == 0 and claims_missing == 0 and errors == 0
    if ok:
        print("OK: continuous learning and YouTube publication idempotency are cloud-durable.")
    else:
        print("NOT READY: fix the counts above before enabling continuous unattended production.")
    print("No Firebase UIDs, titles, video IDs, asset names, prompts, tokens, or secret values were printed.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
