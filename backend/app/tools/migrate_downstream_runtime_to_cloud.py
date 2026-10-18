from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app.core.config import get_settings
from app.core.tenant import tenant_namespace_context
from app.models.audio_finishing import AudioFinishingJob
from app.models.delivery_package import DeliveryPackage
from app.models.delivery_qc import DeliveryQcReport
from app.models.final_assembly import FinalAssemblyJob
from app.models.media_studio import MediaStudioJob
from app.models.publishing_assistant import PublishingDraft
from app.services.audio_finishing_job_service import audio_finishing_job_store
from app.services.autopilot_operation_service import autopilot_operation_store
from app.services.delivery_package_service import delivery_package_store
from app.services.delivery_qc_service import delivery_qc_store
from app.services.final_assembly_job_service import final_assembly_job_store
from app.services.media_studio_job_service import media_studio_job_store
from app.services.publishing_assistant_service import publishing_draft_store


@dataclass
class Stats:
    discovered: int = 0
    valid: int = 0
    would_write: int = 0
    written: int = 0
    invalid: int = 0
    errors: int = 0
    local_artifacts: int = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate tenant-scoped downstream ReviveAI runtime checkpoints to Firestore "
            "and referenced runtime artifacts to GCS. IDs and payload contents are not printed."
        )
    )
    parser.add_argument("--apply", action="store_true", help="Persist eligible checkpoints and artifacts.")
    parser.add_argument("--namespace", default=None, help="Optional hashed tenant namespace.")
    return parser.parse_args()


def tenant_dirs(root: Path, requested: Optional[str]) -> list[Path]:
    if not root.exists():
        return []
    dirs = [path for path in sorted(root.iterdir()) if path.is_dir()]
    return [path for path in dirs if not requested or path.name == requested]


def media_artifact_count(job: MediaStudioJob, root: Path) -> int:
    if not job.result:
        return 0
    assets = []
    if job.result.reference_asset:
        assets.append(job.result.reference_asset)
    assets.extend(job.result.keyframes)
    assets.extend(job.result.video_clips)
    return sum(1 for asset in assets if (root / job.job_id / "assets" / asset.filename).exists() or getattr(asset, "gcs_uri", None))


def assembly_artifact_count(job: FinalAssemblyJob, root: Path) -> int:
    if not job.result:
        return 0
    assets = [job.result.final_video] + ([job.result.subtitles] if job.result.subtitles else [])
    return sum(1 for asset in assets if (root / job.job_id / "assets" / asset.filename).exists() or asset.gcs_uri)


def audio_artifact_count(job: AudioFinishingJob, root: Path) -> int:
    if not job.result:
        return 0
    assets = [job.result.delivery_video]
    if job.result.audio_mix:
        assets.append(job.result.audio_mix)
    if job.result.subtitles:
        assets.append(job.result.subtitles)
    return sum(1 for asset in assets if (root / job.job_id / "assets" / asset.filename).exists() or asset.gcs_uri)


def package_artifact_count(package: DeliveryPackage, package_dir: Path) -> int:
    count = 0
    for asset in package.assets:
        if (package_dir / "files" / asset.filename).exists() or asset.gcs_uri:
            count += 1
    if (package_dir / package.zip_asset.filename).exists() or package.zip_asset.gcs_uri:
        count += 1
    return count


def process_model_file(
    *,
    path: Path,
    namespace: str,
    validator: Callable[[str], object],
    persist: Callable[[object], None],
    artifact_counter: Optional[Callable[[object], int]],
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
    if artifact_counter:
        try:
            stats.local_artifacts += int(artifact_counter(item))
        except Exception:
            pass
    stats.would_write += 1
    if not args.apply:
        return
    try:
        with tenant_namespace_context(namespace):
            persist(item)
        stats.written += 1
    except Exception:
        stats.errors += 1


def main() -> int:
    args = parse_args()
    settings = get_settings()
    base = Path(settings.content_dna_checkpoint_dir)

    if args.apply and not settings.effective_runtime_asset_gcs_uri:
        print("ERROR: runtime artifact GCS is not configured.")
        print("Set RUNTIME_ASSET_GCS_URI or VIDEO_OUTPUT_GCS_URI before applying this migration.")
        return 2

    # Force fail-closed persistence behavior inside this one-shot process so migration
    # cannot report success when a Firestore/GCS write failed under local APP_ENV.
    original_env = settings.app_env
    if args.apply:
        settings.app_env = "production"

    categories = {
        "media": Stats(),
        "assembly": Stats(),
        "audio": Stats(),
        "delivery_qc": Stats(),
        "package": Stats(),
        "publishing": Stats(),
        "operation": Stats(),
    }

    try:
        media_root = base / "media_studio" / "tenants"
        for ns_dir in tenant_dirs(media_root, args.namespace):
            tenant_media_root = ns_dir
            for path in sorted(ns_dir.glob("*/job.json")):
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=MediaStudioJob.model_validate_json,
                    persist=lambda item: media_studio_job_store._persist(item),  # trusted migration path
                    artifact_counter=lambda item, r=tenant_media_root: media_artifact_count(item, r),
                    args=args,
                    stats=categories["media"],
                )

        assembly_root = base / "final_assembly" / "tenants"
        for ns_dir in tenant_dirs(assembly_root, args.namespace):
            tenant_root = ns_dir
            for path in sorted(ns_dir.glob("*/job.json")):
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=FinalAssemblyJob.model_validate_json,
                    persist=lambda item: final_assembly_job_store._persist(item),
                    artifact_counter=lambda item, r=tenant_root: assembly_artifact_count(item, r),
                    args=args,
                    stats=categories["assembly"],
                )

        audio_root = base / "audio_finishing" / "tenants"
        for ns_dir in tenant_dirs(audio_root, args.namespace):
            tenant_root = ns_dir
            for path in sorted(ns_dir.glob("*/job.json")):
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=AudioFinishingJob.model_validate_json,
                    persist=lambda item: audio_finishing_job_store._persist(item),
                    artifact_counter=lambda item, r=tenant_root: audio_artifact_count(item, r),
                    args=args,
                    stats=categories["audio"],
                )

        qc_root = base / "delivery_qc" / "tenants"
        for ns_dir in tenant_dirs(qc_root, args.namespace):
            for path in sorted(ns_dir.glob("*/latest.json")):
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=DeliveryQcReport.model_validate_json,
                    persist=lambda item: delivery_qc_store.save(item),
                    artifact_counter=None,
                    args=args,
                    stats=categories["delivery_qc"],
                )

        package_root = base / "delivery_packages" / "tenants"
        for ns_dir in tenant_dirs(package_root, args.namespace):
            for path in sorted(ns_dir.glob("*/*/package.json")):
                package_dir = path.parent
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=DeliveryPackage.model_validate_json,
                    persist=lambda item: delivery_package_store.save(item),
                    artifact_counter=lambda item, d=package_dir: package_artifact_count(item, d),
                    args=args,
                    stats=categories["package"],
                )

        publishing_root = base / "publishing_assistant" / "tenants"
        for ns_dir in tenant_dirs(publishing_root, args.namespace):
            for path in sorted(ns_dir.glob("*/*/draft.json")):
                process_model_file(
                    path=path,
                    namespace=ns_dir.name,
                    validator=PublishingDraft.model_validate_json,
                    persist=lambda item: publishing_draft_store.save(item),
                    artifact_counter=None,
                    args=args,
                    stats=categories["publishing"],
                )

        operation_root = base / "autopilot_operations" / "tenants"
        for ns_dir in tenant_dirs(operation_root, args.namespace):
            for path in sorted(ns_dir.glob("*.json")):
                stats = categories["operation"]
                stats.discovered += 1
                try:
                    value = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(value, dict) or not value.get("job_id") or not value.get("operation_key"):
                        raise ValueError("invalid operation lease")
                    stats.valid += 1
                    stats.would_write += 1
                    if args.apply:
                        with tenant_namespace_context(ns_dir.name):
                            autopilot_operation_store._save(value)
                        stats.written += 1
                except Exception:
                    stats.errors += 1
    finally:
        settings.app_env = original_env

    print("ReviveAI downstream-runtime cloud migration")
    print("-----------------------------------------")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print(f"runtime artifact GCS configured: {'YES' if settings.effective_runtime_asset_gcs_uri else 'NO'}")
    print()
    print("category       discovered  valid  write  artifacts  invalid  errors")
    print("-------------  ----------  -----  -----  ---------  -------  ------")
    for name, st in categories.items():
        print(
            f"{name:<13}  {st.discovered:>10}  {st.valid:>5}  "
            f"{(st.written if args.apply else st.would_write):>5}  {st.local_artifacts:>9}  {st.invalid:>7}  {st.errors:>6}"
        )

    totals = Stats()
    for st in categories.values():
        for field in totals.__dataclass_fields__:
            setattr(totals, field, getattr(totals, field) + getattr(st, field))
    print()
    print(f"total discovered : {totals.discovered}")
    print(f"total valid      : {totals.valid}")
    print(f"total written    : {totals.written if args.apply else 0}")
    print(f"would write      : {totals.would_write}")
    print(f"local artifacts  : {totals.local_artifacts}")
    print(f"invalid          : {totals.invalid}")
    print(f"errors           : {totals.errors}")
    print()
    print("No checkpoint payloads, Firebase UIDs, job IDs, tokens, prompts, or secret values were printed.")
    if not args.apply and totals.would_write:
        print("Run again with --apply after reviewing this dry run.")
    return 1 if totals.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
