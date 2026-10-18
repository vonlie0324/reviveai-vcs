from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.core.config import Settings
from app.core.tenant import tenant_namespace


SERVICE_DIRS = (
    "channel_analysis",
    "content_dna_jobs",
    "recovery_jobs",
    "production_history",
    "media_studio",
    "final_assembly",
    "audio_finishing",
    "delivery_qc",
    "delivery_packages",
    "publishing_assistant",
    "music_match",
)


@dataclass(frozen=True)
class LegacyAdoptionInventory:
    item_count: int
    production_count: int
    production_titles: tuple[str, ...]
    already_adopted: bool


@dataclass(frozen=True)
class LegacyAdoptionResult:
    copied: int
    skipped: int
    production_count: int
    production_titles: tuple[str, ...]


class LegacyWorkspaceAdoptionService:
    """One-time copy of unscoped pre-M2D.2.1 files into one authorized tenant.

    This service intentionally never decides *who* is allowed to adopt the files.
    Authorization is enforced by the authenticated API route. It also never deletes
    legacy data; the old layout remains available as a rollback copy.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.checkpoint_root = Path(settings.content_dna_checkpoint_dir).resolve()

    def _safe_children(self, root: Path) -> Iterable[Path]:
        if not root.exists() or not root.is_dir():
            return ()
        return tuple(path for path in root.iterdir() if path.name != "tenants" and not path.is_symlink())

    def _legacy_productions(self) -> list[Path]:
        root = self.checkpoint_root / "production_history"
        return sorted(path for path in self._safe_children(root) if path.is_file() and path.name.startswith("production_") and path.suffix == ".json")

    @staticmethod
    def _production_title(path: Path) -> str | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result, dict):
                creative = result.get("creative_direction")
                if isinstance(creative, dict) and isinstance(creative.get("working_title"), str):
                    title = creative["working_title"].strip()
                    if title:
                        return title
            snapshot = payload.get("source_snapshot") if isinstance(payload, dict) else None
            recommendation = snapshot.get("recommendation") if isinstance(snapshot, dict) else None
            if isinstance(recommendation, dict) and isinstance(recommendation.get("title"), str):
                title = recommendation["title"].strip()
                if title:
                    return title
        except Exception:
            return None
        return None

    def _adoption_marker(self, logical_tenant: str) -> Path:
        namespace = tenant_namespace(logical_tenant)
        return self.checkpoint_root / "tenants" / namespace / "legacy_adoption.json"

    def inventory(self, logical_tenant: str) -> LegacyAdoptionInventory:
        item_count = 0
        for service in SERVICE_DIRS:
            item_count += len(tuple(self._safe_children(self.checkpoint_root / service)))

        for feature in ("production_briefs", "audio_music_previews"):
            item_count += len(tuple(self._safe_children(self.checkpoint_root / feature)))

        item_count += len(tuple(path for path in self.checkpoint_root.glob("*.json") if path.is_file() and not path.is_symlink()))

        catalog = Path(self.settings.audio_youtube_library_catalog_path).resolve()
        if catalog.exists() and catalog.is_file() and not catalog.is_symlink():
            item_count += 1

        legacy_tracks = Path(self.settings.audio_youtube_library_dir).resolve() / "tracks"
        if legacy_tracks.exists() and legacy_tracks.is_dir():
            item_count += len(tuple(path for path in legacy_tracks.iterdir() if path.name != ".gitkeep" and not path.is_symlink()))

        production_paths = self._legacy_productions()
        titles = tuple(dict.fromkeys(filter(None, (self._production_title(path) for path in production_paths))))
        return LegacyAdoptionInventory(
            item_count=item_count,
            production_count=len(production_paths),
            production_titles=titles,
            already_adopted=self._adoption_marker(logical_tenant).exists(),
        )

    @staticmethod
    def _copy_entry(source: Path, destination: Path) -> tuple[int, int]:
        if destination.exists():
            return (0, 1)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        return (1, 0)

    def adopt(self, logical_tenant: str) -> LegacyAdoptionResult:
        namespace = tenant_namespace(logical_tenant)
        copied = 0
        skipped = 0
        production_paths = self._legacy_productions()
        titles = tuple(dict.fromkeys(filter(None, (self._production_title(path) for path in production_paths))))

        # Service-specific stores: <service>/tenants/<namespace>/...
        for service in SERVICE_DIRS:
            service_root = self.checkpoint_root / service
            target_root = service_root / "tenants" / namespace
            for source in self._safe_children(service_root):
                c, s = self._copy_entry(source, target_root / source.name)
                copied += c
                skipped += s

        # Shared checkpoint-root features: <checkpoint>/tenants/<namespace>/<feature>/...
        scoped_root = self.checkpoint_root / "tenants" / namespace
        for feature in ("production_briefs", "audio_music_previews"):
            source_root = self.checkpoint_root / feature
            for source in self._safe_children(source_root):
                c, s = self._copy_entry(source, scoped_root / feature / source.name)
                copied += c
                skipped += s

        # Old Content DNA cache JSON files stored directly at checkpoint root.
        for source in self.checkpoint_root.glob("*.json"):
            if not source.is_file() or source.is_symlink():
                continue
            c, s = self._copy_entry(source, scoped_root / "content_dna_cache" / source.name)
            copied += c
            skipped += s

        # Creator-imported YouTube Audio Library catalog and audio tracks.
        catalog = Path(self.settings.audio_youtube_library_catalog_path).resolve()
        if catalog.exists() and catalog.is_file() and not catalog.is_symlink():
            destination = catalog.parent / "tenants" / namespace / catalog.name
            c, s = self._copy_entry(catalog, destination)
            copied += c
            skipped += s

        audio_root = Path(self.settings.audio_youtube_library_dir).resolve()
        legacy_tracks = audio_root / "tracks"
        if legacy_tracks.exists() and legacy_tracks.is_dir():
            destination_root = audio_root / "tenants" / namespace / "tracks"
            for source in legacy_tracks.iterdir():
                if source.name == ".gitkeep" or source.is_symlink():
                    continue
                c, s = self._copy_entry(source, destination_root / source.name)
                copied += c
                skipped += s

        marker = self._adoption_marker(logical_tenant)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "adopted_at": datetime.now(timezone.utc).isoformat(),
                    "copied": copied,
                    "skipped": skipped,
                    "production_count": len(production_paths),
                    "production_titles": list(titles),
                    "legacy_sources_preserved": True,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        return LegacyAdoptionResult(
            copied=copied,
            skipped=skipped,
            production_count=len(production_paths),
            production_titles=titles,
        )
