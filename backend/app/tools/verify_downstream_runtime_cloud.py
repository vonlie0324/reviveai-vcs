from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import get_settings
from app.core.tenant import tenant_namespace_context
from app.models.audio_finishing import AudioFinishingJob
from app.models.delivery_package import DeliveryPackage
from app.models.final_assembly import FinalAssemblyJob
from app.models.media_studio import MediaStudioJob
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.runtime_artifact_store import RuntimeArtifactStore


@dataclass
class Counts:
    local: int = 0
    cloud: int = 0
    errors: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify downstream ReviveAI Firestore + GCS durability without printing identifiers.")
    parser.add_argument("--namespace", default=None, help="Optional hashed tenant namespace.")
    return parser.parse_args()


def namespaces(base: Path, requested: Optional[str]) -> list[str]:
    roots = [
        base / "media_studio" / "tenants",
        base / "final_assembly" / "tenants",
        base / "audio_finishing" / "tenants",
        base / "delivery_qc" / "tenants",
        base / "delivery_packages" / "tenants",
        base / "publishing_assistant" / "tenants",
        base / "autopilot_operations" / "tenants",
        base / "autopilot_state" / "tenants",
    ]
    found: set[str] = set()
    for root in roots:
        if root.exists():
            found.update(p.name for p in root.iterdir() if p.is_dir())
    if requested:
        return [requested] if requested in found else []
    return sorted(found)


def local_count(base: Path, category: str, ns: str) -> int:
    patterns = {
        "media": (base / "media_studio" / "tenants" / ns, "*/job.json"),
        "assembly": (base / "final_assembly" / "tenants" / ns, "*/job.json"),
        "audio": (base / "audio_finishing" / "tenants" / ns, "*/job.json"),
        "delivery_qc": (base / "delivery_qc" / "tenants" / ns, "*/latest.json"),
        "package": (base / "delivery_packages" / "tenants" / ns, "*/*/package.json"),
        "publishing": (base / "publishing_assistant" / "tenants" / ns, "*/*/draft.json"),
        "operation": (base / "autopilot_operations" / "tenants" / ns, "*.json"),
    }
    root, pattern = patterns[category]
    return len(list(root.glob(pattern))) if root.exists() else 0


def verify_media_assets(payload: dict, store: RuntimeArtifactStore) -> tuple[int, int]:
    try:
        job = MediaStudioJob.model_validate(payload)
    except Exception:
        return 0, 0
    if not job.result:
        return 0, 0
    assets = []
    if job.result.reference_asset:
        assets.append(job.result.reference_asset)
    assets.extend(job.result.keyframes)
    assets.extend(job.result.video_clips)
    total = missing = 0
    for asset in assets:
        total += 1
        uri = getattr(asset, "gcs_uri", None)
        try:
            exists = store.exists(owner_id=job.job_id, relative_path=f"assets/{asset.filename}", gcs_uri=uri)
        except Exception:
            exists = False
        if not exists:
            missing += 1
    return total, missing


def verify_assembly_assets(payload: dict, store: RuntimeArtifactStore) -> tuple[int, int]:
    try:
        job = FinalAssemblyJob.model_validate(payload)
    except Exception:
        return 0, 0
    if not job.result:
        return 0, 0
    assets = [job.result.final_video] + ([job.result.subtitles] if job.result.subtitles else [])
    missing = 0
    for asset in assets:
        try:
            if not store.exists(owner_id=job.job_id, relative_path=f"assets/{asset.filename}", gcs_uri=asset.gcs_uri):
                missing += 1
        except Exception:
            missing += 1
    return len(assets), missing


def verify_audio_assets(payload: dict, store: RuntimeArtifactStore) -> tuple[int, int]:
    try:
        job = AudioFinishingJob.model_validate(payload)
    except Exception:
        return 0, 0
    if not job.result:
        return 0, 0
    assets = [job.result.delivery_video]
    if job.result.audio_mix:
        assets.append(job.result.audio_mix)
    if job.result.subtitles:
        assets.append(job.result.subtitles)
    missing = 0
    for asset in assets:
        try:
            if not store.exists(owner_id=job.job_id, relative_path=f"assets/{asset.filename}", gcs_uri=asset.gcs_uri):
                missing += 1
        except Exception:
            missing += 1
    return len(assets), missing


def verify_package_assets(payload: dict, store: RuntimeArtifactStore) -> tuple[int, int]:
    try:
        package = DeliveryPackage.model_validate(payload)
    except Exception:
        return 0, 0
    assets = [package.zip_asset, *package.assets]
    missing = 0
    for asset in assets:
        relative = asset.filename if asset.key == "package_zip" else f"files/{asset.filename}"
        try:
            if not store.exists(owner_id=package.package_id, relative_path=relative, gcs_uri=asset.gcs_uri):
                missing += 1
        except Exception:
            missing += 1
    return len(assets), missing


def main() -> int:
    args = parse_args()
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)
    ns_list = namespaces(base, args.namespace)

    repos = {
        "media": FirestoreJobRepository("media_studio_jobs"),
        "assembly": FirestoreJobRepository("final_assembly_jobs"),
        "audio": FirestoreJobRepository("audio_finishing_jobs"),
        "delivery_qc": FirestoreJobRepository("delivery_qc_reports"),
        "package": FirestoreJobRepository("delivery_packages"),
        "publishing": FirestoreJobRepository("publishing_drafts"),
        "operation": FirestoreJobRepository("autopilot_operations"),
    }
    totals = {name: Counts() for name in repos}
    artifact_total = 0
    artifact_missing = 0
    chain_refs = 0
    chain_missing = 0

    artifact_stores = {
        "media": RuntimeArtifactStore("media_studio"),
        "assembly": RuntimeArtifactStore("final_assembly"),
        "audio": RuntimeArtifactStore("audio_finishing"),
        "package": RuntimeArtifactStore("delivery_packages"),
    }

    for ns in ns_list:
        for name, repo in repos.items():
            st = totals[name]
            st.local += local_count(base, name, ns)
            try:
                docs = list(repo.stream(namespace=ns))
                st.cloud += len(docs)
                with tenant_namespace_context(ns):
                    for _doc_id, payload in docs:
                        if name == "media":
                            total, missing = verify_media_assets(payload, artifact_stores["media"])
                        elif name == "assembly":
                            total, missing = verify_assembly_assets(payload, artifact_stores["assembly"])
                        elif name == "audio":
                            total, missing = verify_audio_assets(payload, artifact_stores["audio"])
                        elif name == "package":
                            total, missing = verify_package_assets(payload, artifact_stores["package"])
                        else:
                            total = missing = 0
                        artifact_total += total
                        artifact_missing += missing
            except Exception:
                st.errors += 1

        # Verify the active Autopilot downstream IDs resolve from cloud stores.
        try:
            state = FirestoreJobRepository("autopilot_state").load("active_session", namespace=ns)
            session = state.get("session") if isinstance(state, dict) else None
            if isinstance(session, dict):
                refs = [
                    (session.get("currentMediaJobId"), repos["media"]),
                    (session.get("currentAssemblyJobId"), repos["assembly"]),
                    (session.get("currentAudioJobId"), repos["audio"]),
                    (session.get("currentDeliveryPackageId"), repos["package"]),
                    (session.get("currentPublishingDraftId"), repos["publishing"]),
                ]
                for item_id, repo in refs:
                    if not item_id:
                        continue
                    chain_refs += 1
                    if repo.load(str(item_id), namespace=ns) is None:
                        chain_missing += 1
        except Exception:
            chain_missing += 1

    print("ReviveAI downstream-runtime cloud verification")
    print("--------------------------------------------")
    print(f"tenant namespaces checked: {len(ns_list)}")
    print(f"runtime artifact GCS configured: {'YES' if settings.effective_runtime_asset_gcs_uri else 'NO'}")
    print()
    print("category       local  firestore  status")
    print("-------------  -----  ---------  ------")
    bad = False
    for name, st in totals.items():
        ok = st.errors == 0 and st.cloud >= st.local
        bad = bad or not ok
        print(f"{name:<13}  {st.local:>5}  {st.cloud:>9}  {'OK' if ok else 'MISSING'}")
    print()
    print(f"cloud artifact references : {artifact_total}")
    print(f"missing GCS artifacts      : {artifact_missing}")
    print(f"active Autopilot refs      : {chain_refs}")
    print(f"missing active refs         : {chain_missing}")
    print()
    if artifact_missing or chain_missing:
        bad = True
    if bad:
        print("WARNING: downstream runtime is not fully restart-durable yet.")
    else:
        print("OK: downstream checkpoints, active Autopilot references, and persisted artifacts are cloud-durable.")
    print("No Firebase UIDs, job IDs, asset names, payloads, prompts, tokens, or secret values were printed.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
