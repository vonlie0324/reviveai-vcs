from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app.core.config import Settings
from app.models.audio_finishing import (
    TrendingMusicCatalogResponse,
    TrendingMusicRenderMode,
    TrendingMusicTrack,
)


class TrendingMusicCatalogError(RuntimeError):
    pass


class TrendingMusicTrackNotFoundError(KeyError):
    pass


@dataclass(frozen=True)
class ResolvedTrendingTrack:
    public: TrendingMusicTrack
    local_path: Optional[Path]


_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus"}


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise TrendingMusicCatalogError(f"Invalid license date: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)



def _optional_int(value: Any, label: str) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise TrendingMusicCatalogError(f"Invalid {label}: {value}") from exc


def _optional_float(value: Any, label: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise TrendingMusicCatalogError(f"Invalid {label}: {value}") from exc

def _normalise_strings(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, Iterable):
        return []
    output: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return output


class TrendingMusicCatalog:
    """Read a rights-aware local catalog of externally licensed trending tracks.

    ReviveAI deliberately does not scrape or download social-platform audio. To make a
    track renderable, an operator places a licensed audio file under the configured
    library root and references it from the catalog JSON. PLATFORM_ONLY entries can
    still appear for discovery but cannot be embedded into the delivery master.
    """

    def _catalog_path(self, settings: Settings) -> Path:
        return Path(settings.audio_trending_music_catalog_path).expanduser()

    def _library_root(self, settings: Settings) -> Path:
        root = Path(settings.audio_trending_music_library_dir).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _read_document(self, settings: Settings) -> tuple[Optional[datetime], list[dict[str, Any]]]:
        path = self._catalog_path(settings)
        if not path.exists():
            return None, []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise TrendingMusicCatalogError(f"Could not read trending music catalog: {exc}") from exc

        if isinstance(raw, list):
            return None, [item for item in raw if isinstance(item, dict)]
        if not isinstance(raw, dict):
            raise TrendingMusicCatalogError("Trending music catalog must be a JSON object or array.")

        tracks = raw.get("tracks", [])
        if not isinstance(tracks, list):
            raise TrendingMusicCatalogError("Trending music catalog 'tracks' must be an array.")
        return _parse_datetime(raw.get("updated_at")), [item for item in tracks if isinstance(item, dict)]

    def _safe_local_path(self, settings: Settings, local_file: Any) -> Optional[Path]:
        if not local_file:
            return None
        root = self._library_root(settings)
        candidate = (root / str(local_file)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise TrendingMusicCatalogError("Trending track path escapes the configured music library.") from exc
        if candidate.suffix.lower() not in _AUDIO_EXTENSIONS:
            raise TrendingMusicCatalogError(f"Unsupported trending audio format: {candidate.suffix or 'unknown'}")
        return candidate

    def _resolve_item(self, raw: dict[str, Any], settings: Settings) -> ResolvedTrendingTrack:
        track_id = str(raw.get("track_id") or raw.get("id") or "").strip()
        title = str(raw.get("title") or "").strip()
        if not track_id or not title:
            raise TrendingMusicCatalogError("Every trending music entry needs track_id and title.")

        license_raw = raw.get("license") if isinstance(raw.get("license"), dict) else {}
        render_mode_text = str(raw.get("render_mode") or "EMBEDDED").upper().strip()
        try:
            render_mode = TrendingMusicRenderMode(render_mode_text)
        except ValueError as exc:
            raise TrendingMusicCatalogError(f"Invalid render_mode for track {track_id}: {render_mode_text}") from exc

        commercial_allowed = bool(
            raw.get("commercial_use_allowed", license_raw.get("commercial_use_allowed", False))
        )
        expires_at = _parse_datetime(raw.get("license_expires_at") or license_raw.get("expires_at"))
        expired = bool(expires_at and expires_at <= datetime.now(timezone.utc))
        platform = str(raw.get("platform") or "").strip().upper()
        region = str(raw.get("region") or "GLOBAL").strip().upper()
        allowed_platforms = [item.upper() for item in _normalise_strings(raw.get("allowed_platforms") or license_raw.get("allowed_platforms"))]
        allowed_regions = [item.upper() for item in _normalise_strings(raw.get("allowed_regions") or license_raw.get("allowed_regions"))]
        platform_scope_ok = not allowed_platforms or not platform or platform in allowed_platforms
        region_scope_ok = not allowed_regions or region in allowed_regions or "GLOBAL" in allowed_regions
        scope_ok = platform_scope_ok and region_scope_ok
        local_path = self._safe_local_path(settings, raw.get("local_file"))
        file_ready = bool(local_path and local_path.is_file() and local_path.stat().st_size > 0)
        render_ready = bool(
            render_mode == TrendingMusicRenderMode.EMBEDDED
            and commercial_allowed
            and not expired
            and scope_ok
            and file_ready
        )

        if expired:
            usage_status = "LICENSE_EXPIRED"
        elif not commercial_allowed:
            usage_status = "RIGHTS_NOT_CONFIRMED"
        elif not scope_ok:
            usage_status = "RIGHTS_SCOPE_MISMATCH"
        elif render_mode == TrendingMusicRenderMode.PLATFORM_ONLY:
            usage_status = "PLATFORM_ONLY"
        elif not file_ready:
            usage_status = "LICENSED_FILE_MISSING"
        else:
            usage_status = "READY"

        public = TrendingMusicTrack(
            track_id=track_id,
            title=title,
            artist=str(raw.get("artist") or "").strip(),
            provider=str(raw.get("provider") or "").strip(),
            platform=platform,
            region=region,
            trend_rank=_optional_int(raw.get("trend_rank"), f"trend_rank for {track_id}"),
            trend_label=str(raw.get("trend_label") or "").strip(),
            genre=str(raw.get("genre") or "").strip(),
            moods=_normalise_strings(raw.get("moods")),
            duration_seconds=_optional_float(raw.get("duration_seconds"), f"duration_seconds for {track_id}"),
            render_mode=render_mode,
            commercial_use_allowed=commercial_allowed,
            allowed_platforms=allowed_platforms,
            allowed_regions=allowed_regions,
            license_reference=str(raw.get("license_reference") or license_raw.get("reference") or "").strip() or None,
            license_expires_at=expires_at,
            source_url=str(raw.get("source_url") or "").strip() or None,
            render_ready=render_ready,
            preview_available=render_ready,
            usage_status=usage_status,
            is_demo=bool(raw.get("is_demo", False)),
        )
        return ResolvedTrendingTrack(public=public, local_path=local_path if file_ready else None)

    def list(self, settings: Settings) -> TrendingMusicCatalogResponse:
        updated_at, raw_tracks = self._read_document(settings)
        tracks: list[TrendingMusicTrack] = []
        seen: set[str] = set()
        for raw in raw_tracks:
            resolved = self._resolve_item(raw, settings)
            if resolved.public.track_id in seen:
                raise TrendingMusicCatalogError(f"Duplicate trending track id: {resolved.public.track_id}")
            seen.add(resolved.public.track_id)
            tracks.append(resolved.public)
        tracks.sort(key=lambda item: (item.trend_rank is None, item.trend_rank or 10**9, item.title.lower()))
        return TrendingMusicCatalogResponse(catalog_updated_at=updated_at, tracks=tracks)

    def resolve(self, track_id: str, settings: Settings, *, require_render_ready: bool = True) -> ResolvedTrendingTrack:
        _, raw_tracks = self._read_document(settings)
        for raw in raw_tracks:
            candidate_id = str(raw.get("track_id") or raw.get("id") or "").strip()
            if candidate_id != track_id:
                continue
            resolved = self._resolve_item(raw, settings)
            if require_render_ready and not resolved.public.render_ready:
                raise TrendingMusicCatalogError(
                    f"'{resolved.public.title}' cannot be embedded: {resolved.public.usage_status.replace('_', ' ').lower()}."
                )
            return resolved
        raise TrendingMusicTrackNotFoundError(track_id)

    def preview_path(self, track_id: str, settings: Settings) -> tuple[Path, str]:
        resolved = self.resolve(track_id, settings, require_render_ready=True)
        if not resolved.local_path:
            raise TrendingMusicCatalogError("The licensed preview file is unavailable.")
        mime = mimetypes.guess_type(resolved.local_path.name)[0] or "application/octet-stream"
        return resolved.local_path, mime


trending_music_catalog = TrendingMusicCatalog()
