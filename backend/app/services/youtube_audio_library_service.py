from __future__ import annotations

import json
import logging
import mimetypes
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

from app.core.config import Settings, get_settings
from app.core.tenant import tenant_namespace, tenant_scoped_root
from app.models.audio_finishing import (
    YouTubeAudioLibraryCatalogResponse,
    YouTubeAudioLibraryLicenseType,
    YouTubeAudioLibraryTrack,
)
from app.services.soundtrack_service_factory import (
    create_cloud_storage_service,
    create_soundtrack_repository,
)

logger = logging.getLogger(__name__)


class YouTubeAudioLibraryError(RuntimeError):
    pass


class YouTubeAudioLibraryTrackNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ResolvedYouTubeAudioLibraryTrack:
    public: YouTubeAudioLibraryTrack
    local_path: Optional[Path] = None
    storage_path: Optional[str] = None


_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


class YouTubeAudioLibrary:
    """Durable creator-managed soundtrack library.

    Metadata is stored in tenant-scoped Firestore and audio binaries are stored in
    Google Cloud Storage. Local files are only temporary validation/render caches;
    Cloud Run filesystem lifetime is never treated as durable state.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        settings = get_settings()
        self.firestore_repository = create_soundtrack_repository()
        self.cloud_storage = create_cloud_storage_service(settings.soundtrack_output_gcs_uri)
        self._legacy_migration_checked: set[str] = set()

    # -------------------------------------------------------------------------
    # Legacy-local helpers. These are retained only for one-time migration of a
    # workstation/local deployment that still has the old JSON + audio files.
    # They are NOT used as the runtime source of truth.
    # -------------------------------------------------------------------------
    def _catalog_path(self, settings: Settings) -> Path:
        path = Path(settings.audio_youtube_library_catalog_path).expanduser()
        scoped_parent = tenant_scoped_root(path.parent)
        return scoped_parent / path.name

    def _root(self, settings: Settings) -> Path:
        base = Path(settings.audio_youtube_library_dir).expanduser().resolve()
        root = tenant_scoped_root(base)
        (root / "tracks").mkdir(parents=True, exist_ok=True)
        return root

    def _read_legacy_document(self, settings: Settings) -> dict[str, Any]:
        path = self._catalog_path(settings)
        if not path.exists():
            return {"updated_at": None, "tracks": []}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise YouTubeAudioLibraryError(f"Could not read legacy YouTube Audio Library catalog: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("tracks", []), list):
            raise YouTubeAudioLibraryError("Legacy YouTube Audio Library catalog must contain a tracks array.")
        return raw

    # -------------------------------------------------------------------------
    # Audio validation / metadata
    # -------------------------------------------------------------------------
    def _probe_audio_duration(self, path: Path) -> Optional[float]:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
        try:
            result = subprocess.run(
                [ffmpeg, "-hide_banner", "-i", str(path.resolve())],
                capture_output=True,
                text=True,
                timeout=12,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        text = result.stderr or result.stdout or ""
        match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return round(duration, 3) if duration > 0 else None

    def _validate_audio_file(self, path: Path) -> None:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise YouTubeAudioLibraryError("Audio import validation requires imageio-ffmpeg.") from exc
        try:
            result = subprocess.run(
                [
                    ffmpeg,
                    "-v",
                    "error",
                    "-i",
                    str(path.resolve()),
                    "-t",
                    "5",
                    "-map",
                    "0:a:0",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=25,
            )
        except subprocess.TimeoutExpired as exc:
            raise YouTubeAudioLibraryError("The uploaded audio file could not be validated in time.") from exc
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "invalid or unreadable audio")[-700:].strip()
            raise YouTubeAudioLibraryError(f"The uploaded file is not readable audio. {detail}")

    @staticmethod
    def _as_datetime(value: Any, *, field_name: str, track_id: str) -> datetime:
        if isinstance(value, datetime):
            result = value
        else:
            try:
                result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception as exc:
                raise YouTubeAudioLibraryError(f"Invalid {field_name} for {track_id or 'track'}.") from exc
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result

    def _public_from_cloud(self, raw: dict[str, Any]) -> YouTubeAudioLibraryTrack:
        track_id = str(raw.get("track_id") or "").strip()
        try:
            license_type = YouTubeAudioLibraryLicenseType(
                str(raw.get("license_type") or YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY.value)
            )
        except ValueError as exc:
            raise YouTubeAudioLibraryError(f"Invalid YouTube Audio Library license type for {track_id or 'track'}.") from exc

        imported_at = self._as_datetime(
            raw.get("imported_at") or raw.get("created_at"),
            field_name="imported_at",
            track_id=track_id,
        )
        filename = str(raw.get("filename") or "").strip()
        storage_path = str(raw.get("storage_path") or "").strip()

        return YouTubeAudioLibraryTrack(
            track_id=track_id,
            title=str(raw.get("title") or "").strip(),
            artist=str(raw.get("artist") or "").strip(),
            genre=str(raw.get("genre") or "").strip(),
            mood=str(raw.get("mood") or "").strip(),
            duration_seconds=(float(raw["duration_seconds"]) if raw.get("duration_seconds") is not None else None),
            license_type=license_type,
            attribution_required=bool(raw.get("attribution_required", False)),
            attribution_text=str(raw.get("attribution_text") or "").strip() or None,
            source_url=str(raw.get("source_url") or "").strip() or None,
            imported_at=imported_at,
            filename=filename,
            mime_type=str(raw.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"),
            render_ready=bool(storage_path),
            preview_available=bool(storage_path),
        )

    # -------------------------------------------------------------------------
    # Durable catalog operations
    # -------------------------------------------------------------------------
    def _storage_path(self, track_id: str, suffix: str) -> str:
        # tenant namespace is included even though the configured GCS URI already
        # has a soundtrack prefix. This prevents cross-tenant object collisions.
        return self.cloud_storage.build_path(
            f"tenants/{tenant_namespace()}/{track_id}{suffix}"
        )

    def _cache_path(self, track_id: str, filename: str) -> Path:
        suffix = Path(filename).suffix.lower()
        cache_root = Path("/tmp/reviveai_soundtrack_cache") / tenant_namespace()
        cache_root.mkdir(parents=True, exist_ok=True)
        return cache_root / f"{track_id}{suffix}"

    def _migrate_legacy_local_catalog_once(self, settings: Settings) -> None:
        namespace = tenant_namespace()
        if namespace in self._legacy_migration_checked:
            return

        with self._lock:
            if namespace in self._legacy_migration_checked:
                return
            self._legacy_migration_checked.add(namespace)

            catalog_path = self._catalog_path(settings)
            if not catalog_path.exists():
                return

            try:
                document = self._read_legacy_document(settings)
                root = self._root(settings) / "tracks"
                migrated = 0
                for raw in document.get("tracks", []):
                    if not isinstance(raw, dict):
                        continue
                    track_id = str(raw.get("track_id") or "").strip()
                    filename = str(raw.get("filename") or "").strip()
                    if not track_id or not filename or self.firestore_repository.get(track_id):
                        continue
                    local_path = (root / filename).resolve()
                    try:
                        local_path.relative_to(root.resolve())
                    except ValueError:
                        continue
                    if not local_path.is_file() or local_path.stat().st_size <= 0:
                        continue

                    suffix = local_path.suffix.lower()
                    storage_path = self._storage_path(track_id, suffix)
                    self.cloud_storage.upload_file(
                        local_path,
                        storage_path,
                        content_type=str(raw.get("mime_type") or mimetypes.guess_type(filename)[0] or "application/octet-stream"),
                    )
                    metadata = dict(raw)
                    metadata["storage_path"] = storage_path
                    metadata["source"] = "YOUTUBE_AUDIO_LIBRARY"
                    self.firestore_repository.create(track_id, metadata)
                    migrated += 1
                if migrated:
                    logger.info("Migrated %s legacy soundtrack(s) to Firestore/GCS", migrated)
            except Exception:
                # Migration is best-effort only. Never make the durable catalog
                # unavailable because an obsolete local JSON file is malformed.
                logger.exception("Legacy soundtrack migration failed; cloud catalog remains authoritative")

    def list(self, settings: Settings) -> YouTubeAudioLibraryCatalogResponse:
        self._migrate_legacy_local_catalog_once(settings)
        try:
            documents = self.firestore_repository.list()
            tracks = [self._public_from_cloud(raw) for raw in documents if isinstance(raw, dict)]
        except YouTubeAudioLibraryError:
            raise
        except Exception as exc:
            raise YouTubeAudioLibraryError(f"Could not load the cloud soundtrack catalog: {exc}") from exc

        tracks = [track for track in tracks if track.track_id and track.title]
        tracks.sort(key=lambda item: item.imported_at, reverse=True)
        return YouTubeAudioLibraryCatalogResponse(tracks=tracks)

    def resolve(self, track_id: str, settings: Settings) -> ResolvedYouTubeAudioLibraryTrack:
        self._migrate_legacy_local_catalog_once(settings)
        try:
            raw = self.firestore_repository.get(track_id)
        except Exception as exc:
            raise YouTubeAudioLibraryError(f"Could not read soundtrack metadata: {exc}") from exc
        if not raw:
            raise YouTubeAudioLibraryTrackNotFoundError(track_id)

        public = self._public_from_cloud(raw)
        storage_path = str(raw.get("storage_path") or "").strip()
        if not storage_path:
            raise YouTubeAudioLibraryError(f"'{public.title}' is missing its Cloud Storage object reference.")

        local_path = self._cache_path(track_id, public.filename)
        try:
            # A cache hit avoids repeatedly downloading the same track during a
            # single warm Cloud Run instance. GCS/Firestore remain authoritative.
            if not local_path.is_file() or local_path.stat().st_size <= 0:
                self.cloud_storage.download_file(storage_path, local_path)
        except Exception as exc:
            local_path.unlink(missing_ok=True)
            raise YouTubeAudioLibraryError(f"'{public.title}' audio file could not be restored from Cloud Storage: {exc}") from exc

        if not local_path.is_file() or local_path.stat().st_size <= 0:
            raise YouTubeAudioLibraryError(f"'{public.title}' audio file is unavailable.")

        return ResolvedYouTubeAudioLibraryTrack(
            public=public,
            local_path=local_path,
            storage_path=storage_path,
        )

    def preview_path(self, track_id: str, settings: Settings) -> tuple[Path, str]:
        resolved = self.resolve(track_id, settings)
        if resolved.local_path is None:
            raise YouTubeAudioLibraryError("Soundtrack preview is unavailable.")
        return resolved.local_path, resolved.public.mime_type

    def import_track(
        self,
        settings: Settings,
        *,
        file_bytes: bytes,
        original_filename: str,
        title: str,
        artist: str,
        genre: str = "",
        mood: str = "",
        license_type: YouTubeAudioLibraryLicenseType,
        attribution_required: bool,
        attribution_text: Optional[str],
        source_url: Optional[str],
    ) -> YouTubeAudioLibraryTrack:
        title = title.strip()
        artist = artist.strip()
        genre = genre.strip()
        mood = mood.strip()
        attribution_text = (attribution_text or "").strip() or None
        source_url = (source_url or "").strip() or None
        if not title:
            raise YouTubeAudioLibraryError("Track title is required.")
        if not file_bytes:
            raise YouTubeAudioLibraryError("Choose an audio file downloaded from YouTube Audio Library.")

        max_bytes = settings.audio_youtube_library_max_upload_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            raise YouTubeAudioLibraryError(
                f"Audio file exceeds the {settings.audio_youtube_library_max_upload_mb} MB import limit."
            )

        suffix = Path(original_filename or "").suffix.lower()
        if suffix not in _AUDIO_EXTENSIONS:
            raise YouTubeAudioLibraryError(
                f"Unsupported audio format: {suffix or 'unknown'}. Use MP3, WAV, M4A, AAC, FLAC, OGG, or OPUS."
            )

        if license_type == YouTubeAudioLibraryLicenseType.CREATIVE_COMMONS:
            attribution_required = True
        if attribution_required and not attribution_text:
            raise YouTubeAudioLibraryError("Attribution text is required for this track license.")

        track_id = f"ytlib_{uuid4().hex}"
        stored_filename = f"{track_id}{suffix}"
        mime_type = mimetypes.guess_type(original_filename)[0] or "application/octet-stream"
        imported_at = datetime.now(timezone.utc)
        storage_path = self._storage_path(track_id, suffix)

        # Validate using a temporary file because ffmpeg expects a filesystem path.
        temp_path: Optional[Path] = None
        uploaded = False
        try:
            with NamedTemporaryFile(prefix=f"{track_id}_", suffix=suffix, delete=False) as handle:
                handle.write(file_bytes)
                temp_path = Path(handle.name)

            self._validate_audio_file(temp_path)
            duration_seconds = self._probe_audio_duration(temp_path)
            self.cloud_storage.upload_file(temp_path, storage_path, content_type=mime_type)
            uploaded = True

            raw = {
                "track_id": track_id,
                "title": title,
                "artist": artist,
                "genre": genre,
                "mood": mood,
                "license_type": license_type.value,
                "attribution_required": attribution_required,
                "attribution_text": attribution_text,
                "source_url": source_url,
                "imported_at": imported_at,
                "filename": stored_filename,
                "mime_type": mime_type,
                "duration_seconds": duration_seconds,
                "storage_path": storage_path,
                "source": "YOUTUBE_AUDIO_LIBRARY",
            }
            self.firestore_repository.create(track_id, raw)
            return self._public_from_cloud(raw)
        except YouTubeAudioLibraryError:
            if uploaded:
                try:
                    self.cloud_storage.delete(storage_path)
                except Exception:
                    logger.exception("Could not roll back soundtrack object %s", storage_path)
            raise
        except Exception as exc:
            if uploaded:
                try:
                    self.cloud_storage.delete(storage_path)
                except Exception:
                    logger.exception("Could not roll back soundtrack object %s", storage_path)
            raise YouTubeAudioLibraryError(f"Soundtrack could not be saved durably: {exc}") from exc
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def delete(self, track_id: str, settings: Settings) -> None:
        del settings  # retained for API compatibility
        try:
            raw = self.firestore_repository.get(track_id)
        except Exception as exc:
            raise YouTubeAudioLibraryError(f"Could not read soundtrack metadata: {exc}") from exc
        if not raw:
            raise YouTubeAudioLibraryTrackNotFoundError(track_id)

        storage_path = str(raw.get("storage_path") or "").strip()
        try:
            if storage_path:
                self.cloud_storage.delete(storage_path)
            self.firestore_repository.delete(track_id)
            cache_path = self._cache_path(track_id, str(raw.get("filename") or track_id))
            cache_path.unlink(missing_ok=True)
        except Exception as exc:
            raise YouTubeAudioLibraryError(f"Soundtrack could not be removed: {exc}") from exc

    # Compatibility methods used by the partially introduced cloud adapters.
    def list_cloud_tracks(self, channel_id=None):
        tracks = self.firestore_repository.list(channel_id=channel_id)
        return [self.firestore_repository.with_preview_url(track, self.cloud_storage) for track in tracks]

    def import_track_to_cloud(self, local_path: Path, metadata: dict, track_id: Optional[str] = None):
        track_id = track_id or f"ytlib_{uuid4().hex}"
        storage_path = self._storage_path(track_id, local_path.suffix.lower())
        self.cloud_storage.upload_file(
            local_path,
            storage_path,
            content_type=str(metadata.get("mime_type") or mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"),
        )
        return self.firestore_repository.create(
            track_id,
            {**metadata, "track_id": track_id, "storage_path": storage_path, "source": "YOUTUBE_AUDIO_LIBRARY"},
        )

    def get_cloud_track(self, track_id: str):
        return self.firestore_repository.get(track_id)

    def resolve_cloud_track(self, track_id: str):
        track = self.get_cloud_track(track_id)
        if not track:
            raise YouTubeAudioLibraryTrackNotFoundError(track_id)
        return self.firestore_repository.with_preview_url(track, self.cloud_storage)

    def list_tracks(self, channel_id=None):
        return self.list_cloud_tracks(channel_id=channel_id)

    def delete_cloud_track(self, track_id: str):
        track = self.firestore_repository.get(track_id)
        if not track:
            raise YouTubeAudioLibraryTrackNotFoundError(track_id)
        storage_path = str(track.get("storage_path") or "").strip()
        if storage_path:
            self.cloud_storage.delete(storage_path)
        self.firestore_repository.delete(track_id)

    def get_catalog_source(self):
        return "firestore_gcs"

    def is_local_catalog_enabled(self):
        return False


youtube_audio_library = YouTubeAudioLibrary()
YouTubeAudioLibraryService = YouTubeAudioLibrary
