from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, Optional, TYPE_CHECKING
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import TenantScopedDict, tenant_scoped_root
from app.models.audio_finishing import MusicSource
from app.models.delivery_package import DeliveryPackage, DeliveryPackageAsset, DeliveryPackageAssetKind
from app.models.delivery_qc import DeliveryQcOverallStatus
from app.services.audio_finishing_job_service import (
    AudioFinishingJobNotFoundError,
    audio_finishing_job_store,
)
from app.services.delivery_qc_service import DeliveryQcReportNotFoundError, delivery_qc_store, qc_allows_manual_delivery
from app.services.firestore_job_repository import FirestoreJobRepository
from app.services.runtime_artifact_store import RuntimeArtifactStore

if TYPE_CHECKING:
    from app.models.publishing_assistant import PublishingDraft

logger = logging.getLogger(__name__)


class DeliveryPackageError(RuntimeError):
    pass


class DeliveryPackageNotFoundError(KeyError):
    pass


class DeliveryPackageAssetNotFoundError(KeyError):
    pass


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", (value or "reviveai-delivery").strip()).strip("-").lower()
    return (cleaned[:72] or "reviveai-delivery")


def _ffmpeg_executable() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise DeliveryPackageError("M2C.4 requires imageio-ffmpeg. Run pip install -r requirements.txt.") from exc


def _run(command: list[str], *, timeout: int = 90) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise DeliveryPackageError("Delivery package media preparation timed out.") from exc
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or "")[-1800:]
        raise DeliveryPackageError(f"Could not prepare the delivery package. {tail}")


def _srt_to_vtt(source: str) -> str:
    # SRT and WebVTT cue payloads are structurally close enough for this deterministic conversion.
    # Remove numeric cue counters and convert decimal commas in timestamps to dots.
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out = ["WEBVTT", ""]
    for line in lines:
        if re.fullmatch(r"\s*\d+\s*", line):
            continue
        if "-->" in line:
            line = line.replace(",", ".")
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _music_attribution_text(audio_job) -> str:
    result = audio_job.result
    if not result or not result.options.music_enabled:
        return "No background music is embedded in this delivery master.\n"

    if result.effective_music_source == MusicSource.YOUTUBE_AUDIO_LIBRARY and result.selected_youtube_audio_library_track:
        track = result.selected_youtube_audio_library_track
        rows = [
            "MUSIC USAGE RECORD",
            "",
            f"Track: {track.title}",
            f"Artist: {track.artist or 'Not provided'}",
            "Source: YouTube Audio Library",
            f"License type: {track.license_type.value}",
            f"Attribution required: {'Yes' if track.attribution_required else 'No'}",
        ]
        if track.attribution_required and track.attribution_text:
            rows += ["", "Required attribution:", track.attribution_text.strip()]
        if track.source_url:
            rows += ["", f"Reference: {track.source_url}"]
        rows += ["", "Verify current license terms before publishing outside the intended platform/workflow."]
        return "\n".join(rows).rstrip() + "\n"

    if result.effective_music_source == MusicSource.TRENDING_LICENSED and result.selected_trending_track:
        track = result.selected_trending_track
        rows = [
            "MUSIC USAGE RECORD",
            "",
            f"Track: {track.title}",
            f"Artist: {track.artist or 'Not provided'}",
            f"Provider: {track.provider or 'Not provided'}",
            f"License reference: {track.license_reference or 'Not provided'}",
            f"Commercial use recorded: {'Yes' if track.commercial_use_allowed else 'No'}",
            f"Allowed platforms: {', '.join(track.allowed_platforms) or 'Not provided'}",
            f"Allowed regions: {', '.join(track.allowed_regions) or 'Not provided'}",
        ]
        if track.license_expires_at:
            rows.append(f"License expires: {track.license_expires_at.isoformat()}")
        return "\n".join(rows).rstrip() + "\n"

    return (
        "MUSIC USAGE RECORD\n\n"
        f"Source: ReviveAI generated music\n"
        f"Preset: {result.effective_music_preset.value}\n"
        "Third-party attribution required: No\n"
    )


class DeliveryPackageStore:
    """Versioned delivery packages with Firestore manifests and GCS files."""

    def __init__(self, checkpoint_root: str):
        self._root = Path(checkpoint_root) / "delivery_packages"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._cache: TenantScopedDict[str, DeliveryPackage] = TenantScopedDict()
        self._cloud = FirestoreJobRepository("delivery_packages")
        self._artifacts = RuntimeArtifactStore("delivery_packages")

    def _assembly_root(self, assembly_job_id: str) -> Path:
        path = tenant_scoped_root(self._root) / assembly_job_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _package_dir(self, assembly_job_id: str, package_id: str) -> Path:
        return self._assembly_root(assembly_job_id) / package_id

    def _manifest_path(self, assembly_job_id: str, package_id: str) -> Path:
        return self._package_dir(assembly_job_id, package_id) / "package.json"

    @staticmethod
    def _validate_payload(payload: dict | None) -> Optional[DeliveryPackage]:
        if not payload:
            return None
        try:
            return DeliveryPackage.model_validate(payload)
        except Exception:
            return None

    def _load_manifest(self, path: Path) -> Optional[DeliveryPackage]:
        try:
            return DeliveryPackage.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Could not load delivery package checkpoint %s", path)
            return None

    def _sync_artifacts(self, package: DeliveryPackage) -> None:
        package_dir = self._package_dir(package.assembly_job_id, package.package_id)
        for asset in package.assets:
            path = package_dir / "files" / asset.filename
            if not path.exists():
                if asset.gcs_uri:
                    continue
                raise FileNotFoundError(f"Delivery package artifact is missing from the local cache: {asset.filename}")
            uri = self._artifacts.upload_file(
                path, owner_id=package.package_id, relative_path=f"files/{asset.filename}", content_type=asset.mime_type
            )
            if uri:
                asset.gcs_uri = uri
        zip_path = package_dir / package.zip_asset.filename
        if not zip_path.exists():
            if not package.zip_asset.gcs_uri:
                raise FileNotFoundError(f"Delivery package ZIP is missing from the local cache: {package.zip_asset.filename}")
        else:
            uri = self._artifacts.upload_file(
                zip_path, owner_id=package.package_id, relative_path=package.zip_asset.filename, content_type=package.zip_asset.mime_type
            )
            if uri:
                package.zip_asset.gcs_uri = uri

    def _persist_local(self, package: DeliveryPackage) -> None:
        manifest = self._manifest_path(package.assembly_job_id, package.package_id)
        manifest.parent.mkdir(parents=True, exist_ok=True)
        tmp = manifest.with_suffix(".tmp")
        tmp.write_text(json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(manifest)

    def _persist_cloud(self, package: DeliveryPackage) -> None:
        self._cloud.save(package.package_id, package.model_dump(mode="json"))

    def _backfill_cloud(self, package: DeliveryPackage) -> None:
        try:
            self._sync_artifacts(package)
            self._persist_cloud(package)
        except Exception:
            logger.exception("Could not backfill delivery package %s to cloud persistence", package.package_id)

    def _all_for_assembly(self, assembly_job_id: str) -> list[DeliveryPackage]:
        items: Dict[str, DeliveryPackage] = {}
        try:
            for _doc_id, payload in self._cloud.stream():
                loaded = self._validate_payload(payload)
                if loaded and loaded.assembly_job_id == assembly_job_id:
                    items[loaded.package_id] = loaded
        except Exception:
            logger.exception("Could not list delivery packages from Firestore; using local mirror")

        for path in self._assembly_root(assembly_job_id).glob("*/package.json"):
            loaded = self._load_manifest(path)
            if loaded:
                items[loaded.package_id] = loaded
                try:
                    if self._cloud.load(loaded.package_id) is None:
                        self._backfill_cloud(loaded)
                except Exception:
                    logger.exception("Could not inspect cloud delivery package %s", loaded.package_id)
        with self._lock:
            for loaded in self._cache.values():
                if loaded.assembly_job_id == assembly_job_id:
                    items[loaded.package_id] = loaded.model_copy(deep=True)
        return sorted(items.values(), key=lambda item: (item.package_version, item.generated_at), reverse=True)

    def list_for_assembly_job(self, assembly_job_id: str) -> list[DeliveryPackage]:
        return self._all_for_assembly(assembly_job_id)

    def list_for_audio_job(self, audio_job_id: str) -> list[DeliveryPackage]:
        try:
            audio_job = audio_finishing_job_store.get(audio_job_id)
        except AudioFinishingJobNotFoundError as exc:
            raise DeliveryPackageNotFoundError(audio_job_id) from exc
        return [item for item in self._all_for_assembly(audio_job.assembly_job_id) if item.audio_job_id == audio_job_id]

    def latest_for_audio_job(self, audio_job_id: str) -> Optional[DeliveryPackage]:
        items = self.list_for_audio_job(audio_job_id)
        return items[0] if items else None

    def save(self, package: DeliveryPackage) -> None:
        artifact_error: Exception | None = None
        cloud_error: Exception | None = None
        try:
            self._sync_artifacts(package)
        except Exception as exc:
            artifact_error = exc
            logger.exception("Could not mirror delivery package %s to GCS", package.package_id)
        try:
            self._persist_cloud(package)
        except Exception as exc:
            cloud_error = exc
            logger.exception("Could not persist delivery package %s to Firestore", package.package_id)
        self._persist_local(package)
        with self._lock:
            self._cache[package.package_id] = package.model_copy(deep=True)
        if get_settings().app_env.strip().lower() in {"production", "prod"}:
            if artifact_error is not None:
                raise RuntimeError("Durable GCS artifact persistence failed for the delivery package") from artifact_error
            if cloud_error is not None:
                raise RuntimeError("Durable Firestore persistence failed for the delivery package") from cloud_error

    def get(self, package_id: str) -> DeliveryPackage:
        with self._lock:
            cached = self._cache.get(package_id)
            if cached:
                return cached.model_copy(deep=True)
        loaded = None
        try:
            loaded = self._validate_payload(self._cloud.load(package_id))
        except Exception:
            logger.exception("Could not read delivery package %s from Firestore", package_id)
        if loaded is None:
            for path in tenant_scoped_root(self._root).glob(f"*/{package_id}/package.json"):
                loaded = self._load_manifest(path)
                if loaded:
                    self._backfill_cloud(loaded)
                    break
        if loaded is None:
            raise DeliveryPackageNotFoundError(package_id)
        with self._lock:
            self._cache[package_id] = loaded
        return loaded.model_copy(deep=True)

    def asset_path(self, package_id: str, key: str) -> tuple[Path, str, str]:
        package = self.get(package_id)
        candidates = [package.zip_asset, *package.assets]
        asset = next((item for item in candidates if item.key == key), None)
        if not asset:
            raise DeliveryPackageAssetNotFoundError(key)
        if key == "package_zip":
            relative = asset.filename
            path = self._package_dir(package.assembly_job_id, package.package_id) / asset.filename
        else:
            relative = f"files/{asset.filename}"
            path = self._package_dir(package.assembly_job_id, package.package_id) / "files" / asset.filename
        if not path.exists():
            self._artifacts.ensure_local(
                path, owner_id=package.package_id, relative_path=relative, gcs_uri=asset.gcs_uri
            )
        if not path.exists():
            raise DeliveryPackageAssetNotFoundError(key)
        return path, asset.mime_type, asset.filename

    def next_version(self, assembly_job_id: str) -> int:
        return max((item.package_version for item in self._all_for_assembly(assembly_job_id)), default=0) + 1


delivery_package_store = DeliveryPackageStore(get_settings().content_dna_checkpoint_dir)


def _asset(package_id: str, key: str, label: str, kind: DeliveryPackageAssetKind, path: Path, mime_type: str) -> DeliveryPackageAsset:
    return DeliveryPackageAsset(
        key=key,
        label=label,
        kind=kind,
        filename=path.name,
        mime_type=mime_type,
        size_bytes=path.stat().st_size,
        asset_url=f"/api/v1/youtube/delivery-packages/{package_id}/assets/{key}",
    )


def create_delivery_package(audio_job_id: str, settings: Settings, publishing_draft: Optional["PublishingDraft"] = None) -> DeliveryPackage:
    try:
        audio_job = audio_finishing_job_store.get(audio_job_id)
    except AudioFinishingJobNotFoundError as exc:
        raise DeliveryPackageNotFoundError(audio_job_id) from exc
    if not audio_job.result:
        raise DeliveryPackageError("The selected audio master has not finished rendering.")

    try:
        qc = delivery_qc_store.get(audio_job_id)
    except DeliveryQcReportNotFoundError as exc:
        raise DeliveryPackageError("Run Final Delivery QC before creating the delivery package.") from exc
    if not qc_allows_manual_delivery(qc):
        raise DeliveryPackageError("Final Delivery QC requires READY or creator acknowledgment of all current non-blocking warnings.")
    if qc.audio_version != audio_job.version_number:
        raise DeliveryPackageError("The saved QC report does not match the selected audio-master version. Rerun QC.")

    if publishing_draft is not None:
        if publishing_draft.audio_job_id != audio_job_id:
            raise DeliveryPackageError("The approved publishing draft does not belong to this audio master.")
        if publishing_draft.qc_report_id != qc.report_id:
            raise DeliveryPackageError("The publishing draft was generated from a different QC report. Create a fresh publishing draft.")
        if publishing_draft.status.value != "APPROVED":
            raise DeliveryPackageError("Approve the publishing draft before adding it to a delivery package.")

    for existing in delivery_package_store.list_for_audio_job(audio_job_id):
        if (
            existing.qc_report_id == qc.report_id
            and existing.publishing_draft_id == (publishing_draft.draft_id if publishing_draft else None)
        ):
            return existing

    package_version = delivery_package_store.next_version(audio_job.assembly_job_id)
    package_milestone = "M2C.5" if publishing_draft else "M2C.4"
    package_id = f"deliverypkg_{uuid4().hex}"
    title_slug = _slug(audio_job.result.working_title)
    root_folder = f"{title_slug}-audio-v{audio_job.version_number}-delivery-v{package_version}"
    package_dir = delivery_package_store._package_dir(audio_job.assembly_job_id, package_id)
    files_dir = package_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)

    try:
        source_video, _ = audio_finishing_job_store.asset_path(audio_job_id, audio_job.result.delivery_video.asset_id)
        master_path = files_dir / f"{title_slug}-master-v{audio_job.version_number}.mp4"
        shutil.copy2(source_video, master_path)

        assets: list[DeliveryPackageAsset] = []
        assets.append(_asset(package_id, "master_video", "Final master", DeliveryPackageAssetKind.MASTER_VIDEO, master_path, "video/mp4"))

        if audio_job.result.subtitles:
            source_srt, _ = audio_finishing_job_store.asset_path(audio_job_id, audio_job.result.subtitles.asset_id)
            srt_path = files_dir / "captions.srt"
            shutil.copy2(source_srt, srt_path)
            assets.append(_asset(package_id, "captions_srt", "Captions (SRT)", DeliveryPackageAssetKind.CAPTIONS_SRT, srt_path, "application/x-subrip"))

            vtt_path = files_dir / "captions.vtt"
            vtt_path.write_text(_srt_to_vtt(srt_path.read_text(encoding="utf-8")), encoding="utf-8")
            assets.append(_asset(package_id, "captions_vtt", "Captions (VTT)", DeliveryPackageAssetKind.CAPTIONS_VTT, vtt_path, "text/vtt"))

        attribution_text = _music_attribution_text(audio_job)
        attribution_path = files_dir / "music-attribution.txt"
        attribution_path.write_text(attribution_text, encoding="utf-8")
        assets.append(_asset(package_id, "music_attribution", "Music attribution", DeliveryPackageAssetKind.MUSIC_ATTRIBUTION, attribution_path, "text/plain"))

        if publishing_draft is not None:
            yt = publishing_draft.content.youtube
            title_path = files_dir / "youtube-title.txt"
            title_path.write_text(yt.title.strip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "youtube_title", "YouTube title", DeliveryPackageAssetKind.YOUTUBE_TITLE, title_path, "text/plain"))

            description = yt.description.strip()
            track = audio_job.result.selected_youtube_audio_library_track
            if track and track.attribution_required and track.attribution_text:
                exact = track.attribution_text.strip()
                if exact and exact not in description:
                    description = f"{description}\n\nMusic attribution:\n{exact}"
            description_path = files_dir / "youtube-description.txt"
            description_path.write_text(description.rstrip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "youtube_description", "YouTube description", DeliveryPackageAssetKind.YOUTUBE_DESCRIPTION, description_path, "text/plain"))

            hashtags_path = files_dir / "youtube-hashtags.txt"
            hashtags_path.write_text(" ".join(yt.hashtags).strip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "youtube_hashtags", "YouTube hashtags", DeliveryPackageAssetKind.YOUTUBE_HASHTAGS, hashtags_path, "text/plain"))

            tags_path = files_dir / "youtube-tags.txt"
            tags_path.write_text(", ".join(yt.tags).strip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "youtube_tags", "YouTube tags", DeliveryPackageAssetKind.YOUTUBE_TAGS, tags_path, "text/plain"))

            tiktok_path = files_dir / "tiktok-caption.txt"
            tiktok = publishing_draft.content.tiktok
            tiktok_text = "\n".join(part for part in [tiktok.hook.strip(), tiktok.caption.strip(), " ".join(tiktok.hashtags).strip(), tiktok.cta.strip()] if part).rstrip() + "\n"
            tiktok_path.write_text(tiktok_text, encoding="utf-8")
            assets.append(_asset(package_id, "tiktok_caption", "TikTok caption", DeliveryPackageAssetKind.TIKTOK_CAPTION, tiktok_path, "text/plain"))

            ig = publishing_draft.content.instagram
            instagram_path = files_dir / "instagram-caption.txt"
            instagram_text = "\n\n".join(part for part in [ig.caption_long.strip(), " ".join(ig.hashtags).strip(), ig.cta.strip()] if part).rstrip() + "\n"
            instagram_path.write_text(instagram_text, encoding="utf-8")
            assets.append(_asset(package_id, "instagram_caption", "Instagram caption", DeliveryPackageAssetKind.INSTAGRAM_CAPTION, instagram_path, "text/plain"))

            alt_path = files_dir / "instagram-alt-text.txt"
            alt_path.write_text(ig.alt_text.strip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "instagram_alt_text", "Instagram alt text", DeliveryPackageAssetKind.INSTAGRAM_ALT_TEXT, alt_path, "text/plain"))

            draft_path = files_dir / "publishing-draft.json"
            draft_path.write_text(json.dumps(publishing_draft.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            assets.append(_asset(package_id, "publishing_draft", "Publishing draft", DeliveryPackageAssetKind.PUBLISHING_DRAFT, draft_path, "application/json"))
        else:
            description_path = files_dir / "youtube-description.txt"
            description_path.write_text(audio_job.result.publishing.description.strip() + "\n", encoding="utf-8")
            assets.append(_asset(package_id, "youtube_description", "YouTube description", DeliveryPackageAssetKind.YOUTUBE_DESCRIPTION, description_path, "text/plain"))

        thumbnail_path = files_dir / "thumbnail.jpg"
        ffmpeg = _ffmpeg_executable()
        seek_seconds = min(1.0, max(0.0, audio_job.result.total_duration_seconds * 0.20))
        _run([
            ffmpeg, "-y", "-ss", f"{seek_seconds:.3f}", "-i", str(source_video.resolve()),
            "-frames:v", "1", "-q:v", "2", str(thumbnail_path.resolve()),
        ], timeout=45)
        assets.append(_asset(package_id, "thumbnail", "Thumbnail", DeliveryPackageAssetKind.THUMBNAIL, thumbnail_path, "image/jpeg"))

        production_summary = {
            "milestone": package_milestone,
            "package_id": package_id,
            "package_version": package_version,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "working_title": audio_job.result.working_title,
            "assembly_job_id": audio_job.assembly_job_id,
            "audio_job_id": audio_job.job_id,
            "audio_version": audio_job.version_number,
            "qc_report_id": qc.report_id,
            "qc_status": qc.overall_status.value,
            "source_visual_asset_id": qc.source_visual_asset_id,
            "delivery_asset_id": qc.delivery_asset_id,
            "duration_seconds": audio_job.result.total_duration_seconds,
            "publishing": audio_job.result.publishing.model_dump(mode="json"),
            "audio_options": audio_job.result.options.model_dump(mode="json"),
            "audio_layers": [layer.model_dump(mode="json") for layer in audio_job.result.layers],
            "effective_music_source": audio_job.result.effective_music_source.value,
            "effective_music_preset": audio_job.result.effective_music_preset.value,
            "selected_youtube_audio_library_track": (
                audio_job.result.selected_youtube_audio_library_track.model_dump(mode="json")
                if audio_job.result.selected_youtube_audio_library_track else None
            ),
            "selected_trending_track": (
                audio_job.result.selected_trending_track.model_dump(mode="json")
                if audio_job.result.selected_trending_track else None
            ),
            "qc_metrics": qc.metrics,
            "publishing_draft": publishing_draft.model_dump(mode="json") if publishing_draft else None,
        }
        summary_path = files_dir / "production-summary.json"
        summary_path.write_text(json.dumps(production_summary, ensure_ascii=False, indent=2), encoding="utf-8")
        assets.append(_asset(package_id, "production_summary", "Production summary", DeliveryPackageAssetKind.PRODUCTION_SUMMARY, summary_path, "application/json"))

        qc_path = files_dir / "delivery-qc.json"
        qc_path.write_text(json.dumps(qc.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        assets.append(_asset(package_id, "delivery_qc", "Delivery QC report", DeliveryPackageAssetKind.DELIVERY_QC, qc_path, "application/json"))

        loudness = (qc.metrics.get("loudness") or {}) if isinstance(qc.metrics, dict) else {}
        container = (qc.metrics.get("container") or {}) if isinstance(qc.metrics, dict) else {}
        music_text = "ReviveAI generated / none"
        if audio_job.result.selected_youtube_audio_library_track:
            track = audio_job.result.selected_youtube_audio_library_track
            music_text = f"{track.title}{' — ' + track.artist if track.artist else ''} (YouTube Audio Library)"
        elif audio_job.result.selected_trending_track:
            track = audio_job.result.selected_trending_track
            music_text = f"{track.title}{' — ' + track.artist if track.artist else ''} ({track.provider or 'licensed provider'})"

        readme = f"""REVIVEAI DELIVERY PACKAGE

Project
{audio_job.result.working_title}

Delivery lineage
Visual master asset: {qc.source_visual_asset_id or 'unknown'}
Audio master: v{audio_job.version_number}
Delivery package: v{package_version}
QC report: {qc.report_id}

Video
{container.get('width', settings.assembly_render_width)} × {container.get('height', settings.assembly_render_height)}
{container.get('fps', settings.assembly_frame_rate)} fps
{audio_job.result.total_duration_seconds:.2f} seconds
H.264 / AAC delivery master

Audio
Integrated loudness: {loudness.get('integrated_lufs', 'unknown')} LUFS
True peak: {loudness.get('true_peak_dbfs', 'unknown')} dBTP

Music
{music_text}

Final QC
{qc.overall_status.value}
{qc.pass_count} passed
{qc.warn_count} warnings
{qc.fail_count} failures

Package contents
- final master MP4
- captions when available (SRT + VTT)
- YouTube publishing copy
- TikTok + Instagram publishing copy when an approved M2C.5 draft is attached
- music attribution / rights record
- thumbnail
- production summary JSON
- delivery QC JSON

Created
{datetime.now(timezone.utc).isoformat()}

ReviveAI {package_milestone} packages existing approved assets{' plus creator-approved publishing copy' if publishing_draft else ''}. It does not regenerate the approved visual or audio master.
"""
        readme_path = files_dir / "README.txt"
        readme_path.write_text(readme, encoding="utf-8")
        assets.append(_asset(package_id, "readme", "README", DeliveryPackageAssetKind.README, readme_path, "text/plain"))

        zip_path = package_dir / f"{root_folder}.zip"
        zip_folders = {
            "captions_srt": "captions",
            "captions_vtt": "captions",
            "youtube_title": "publishing",
            "youtube_description": "publishing",
            "youtube_hashtags": "publishing",
            "youtube_tags": "publishing",
            "tiktok_caption": "publishing",
            "instagram_caption": "publishing",
            "instagram_alt_text": "publishing",
            "publishing_draft": "publishing",
            "music_attribution": "publishing",
            "thumbnail": "assets",
            "production_summary": "metadata",
            "delivery_qc": "metadata",
        }
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for asset in assets:
                folder = zip_folders.get(asset.key, "")
                relative = f"{folder}/{asset.filename}" if folder else asset.filename
                archive.write(files_dir / asset.filename, arcname=f"{root_folder}/{relative}")

        zip_asset = DeliveryPackageAsset(
            key="package_zip",
            label="Delivery package ZIP",
            kind=DeliveryPackageAssetKind.ZIP,
            filename=zip_path.name,
            mime_type="application/zip",
            size_bytes=zip_path.stat().st_size,
            asset_url=f"/api/v1/youtube/delivery-packages/{package_id}/download",
        )

        package = DeliveryPackage(
            package_id=package_id,
            assembly_job_id=audio_job.assembly_job_id,
            audio_job_id=audio_job.job_id,
            audio_version=audio_job.version_number,
            package_version=package_version,
            qc_report_id=qc.report_id,
            generated_at=datetime.now(timezone.utc),
            working_title=audio_job.result.working_title,
            source_visual_asset_id=qc.source_visual_asset_id,
            delivery_asset_id=qc.delivery_asset_id,
            root_folder_name=root_folder,
            publishing_draft_id=publishing_draft.draft_id if publishing_draft else None,
            publishing_draft_version=publishing_draft.version_number if publishing_draft else None,
            zip_asset=zip_asset,
            assets=assets,
            methodology_notice=(
                "M2C.5 creates a new versioned delivery package that preserves the QC-verified master and adds creator-approved publishing copy. Package generation never regenerates visual or audio media."
                if publishing_draft else
                "M2C.4 packages the already-approved, QC-verified delivery master and companion publishing assets without regenerating visual or audio media."
            ),
        )
        delivery_package_store.save(package)
        return package
    except Exception:
        # Do not leave a half-generated package looking valid.
        if package_dir.exists() and not (package_dir / "package.json").exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        raise
