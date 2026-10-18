from __future__ import annotations

import json
from pathlib import Path

from app.api.routes.auth import _legacy_adoption_allowed
from app.core.config import Settings
from app.core.tenant import tenant_namespace
from app.services.legacy_adoption_service import LegacyWorkspaceAdoptionService


def _settings(tmp_path: Path, **overrides):
    values = {
        "_env_file": None,
        "content_dna_checkpoint_dir": str(tmp_path / "checkpoints"),
        "audio_youtube_library_catalog_path": str(tmp_path / "music" / "catalog.json"),
        "audio_youtube_library_dir": str(tmp_path / "music" / "youtube"),
    }
    values.update(overrides)
    return Settings(**values)


def _write_legacy_production(root: Path, job_id: str = "production_old") -> Path:
    target = root / "production_history" / f"{job_id}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "job_id": job_id,
                "result": {"creative_direction": {"working_title": "Chinggay's Retro Cabin Crew Service"}},
            }
        ),
        encoding="utf-8",
    )
    return target


def test_legacy_adoption_requires_explicit_server_allowlist(tmp_path):
    settings = _settings(tmp_path)
    claims = {"uid": "owner-uid", "email": "owner@example.com", "email_verified": True}
    assert _legacy_adoption_allowed(claims, settings) is False

    settings = _settings(tmp_path, legacy_adoption_allowed_uids=["owner-uid"])
    assert _legacy_adoption_allowed(claims, settings) is True


def test_verified_email_can_be_allowlisted_but_unverified_email_cannot(tmp_path):
    settings = _settings(tmp_path, legacy_adoption_allowed_emails=["Owner@Example.com"])
    assert _legacy_adoption_allowed(
        {"uid": "x", "email": "owner@example.com", "email_verified": True}, settings
    ) is True
    assert _legacy_adoption_allowed(
        {"uid": "x", "email": "owner@example.com", "email_verified": False}, settings
    ) is False


def test_legacy_workspace_is_copied_into_only_target_tenant(tmp_path):
    settings = _settings(tmp_path)
    root = Path(settings.content_dna_checkpoint_dir)
    legacy = _write_legacy_production(root)
    service = LegacyWorkspaceAdoptionService(settings)

    inventory = service.inventory("user:owner-a")
    assert inventory.production_count == 1
    assert "Chinggay's Retro Cabin Crew Service" in inventory.production_titles

    result = service.adopt("user:owner-a")
    assert result.copied >= 1
    namespace_a = tenant_namespace("user:owner-a")
    namespace_b = tenant_namespace("user:owner-b")
    copied = root / "production_history" / "tenants" / namespace_a / legacy.name
    other = root / "production_history" / "tenants" / namespace_b / legacy.name
    assert copied.exists()
    assert not other.exists()
    # Rollback source is deliberately preserved.
    assert legacy.exists()


def test_legacy_adoption_is_idempotent(tmp_path):
    settings = _settings(tmp_path)
    root = Path(settings.content_dna_checkpoint_dir)
    _write_legacy_production(root)
    service = LegacyWorkspaceAdoptionService(settings)

    first = service.adopt("user:owner")
    second = service.adopt("user:owner")
    assert first.copied >= 1
    assert second.copied == 0
    assert second.skipped >= 1
    assert service.inventory("user:owner").already_adopted is True
