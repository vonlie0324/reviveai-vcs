"""Read-only configuration preflight for autonomous production.

This deliberately does not create assets, reserve money, or probe paid providers.
"""
from __future__ import annotations

import math
import os
from typing import Any

from app.core.config import get_settings


_RESERVATIONS = (
    "REVIVEAI_GEMINI_BRIEF_RESERVATION_USD",
    "REVIVEAI_GEMINI_REVIEW_RESERVATION_USD",
    "REVIVEAI_IMAGE_GENERATION_RESERVATION_USD",
)


def production_readiness() -> dict[str, Any]:
    settings = get_settings()
    checks: list[dict[str, str | bool]] = []

    def add(key: str, ok: bool, problem: str) -> None:
        checks.append({"key": key, "ready": ok, "message": "Configured" if ok else problem})

    for key in _RESERVATIONS:
        raw = os.environ.get(key, "").strip()
        try:
            value = float(raw)
            valid = math.isfinite(value) and value > 0
        except (ValueError, OverflowError):
            valid = False
        add(key, valid, f"Set {key} to a positive finite USD reservation in the backend process environment")

    add("GOOGLE_CLOUD_PROJECT", bool(settings.google_cloud_project.strip()), "Configure GOOGLE_CLOUD_PROJECT")
    add("GEMINI_MODEL", bool(settings.gemini_model.strip()), "Configure GEMINI_MODEL")
    add("IMAGE_GENERATION_MODEL", bool(settings.image_generation_model.strip()) and settings.image_generation_model != "gemini-2.5-flash-image", "Configure a supported IMAGE_GENERATION_MODEL")
    add("VIDEO_GENERATION_MODEL", bool(settings.video_generation_model.strip()), "Configure VIDEO_GENERATION_MODEL")
    add("VIDEO_OUTPUT_GCS_URI", bool(settings.video_output_gcs_uri.strip().startswith("gs://")), "Configure VIDEO_OUTPUT_GCS_URI to a GCS prefix")
    add("AUTOPILOT_BACKEND_SUPERVISOR_ENABLED", bool(settings.autopilot_backend_supervisor_enabled), "Enable the backend Autopilot supervisor")
    if settings.autopilot_autonomous_publish_enabled:
        add("YOUTUBE_OAUTH_CLIENT_ID", bool(settings.youtube_oauth_client_id.strip()), "Configure YOUTUBE_OAUTH_CLIENT_ID")
        add("YOUTUBE_OAUTH_CLIENT_SECRET", bool(settings.youtube_oauth_client_secret.strip()), "Configure YOUTUBE_OAUTH_CLIENT_SECRET")
        add("YOUTUBE_OAUTH_TOKEN_ENCRYPTION_KEY", bool(settings.youtube_oauth_token_encryption_key.strip()), "Configure YOUTUBE_OAUTH_TOKEN_ENCRYPTION_KEY")

    return {
        "ready": all(bool(item["ready"]) for item in checks),
        "checks": checks,
        "note": "Configuration-only check. Does not validate remaining funds, provider quotas, connected YouTube channel, or successful publication.",
    }
