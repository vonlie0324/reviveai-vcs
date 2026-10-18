import pytest
from fastapi import HTTPException

from app.api.routes.media_studio import _require_video_config
from app.core.config import Settings


def test_veo31_requires_us_central1_endpoint():
    settings = Settings(
        google_cloud_project="ai-projects-250716",
        video_generation_model="veo-3.1-generate-001",
        video_generation_location="asia-east1",
        video_output_gcs_uri="gs://reviveai/videos",
    )
    with pytest.raises(HTTPException) as exc_info:
        _require_video_config(settings)
    assert exc_info.value.status_code == 503
    assert "us-central1" in str(exc_info.value.detail)
    assert "bucket location is a separate setting" in str(exc_info.value.detail)


def test_veo31_valid_config_passes_preflight():
    settings = Settings(
        google_cloud_project="ai-projects-250716",
        video_generation_model="veo-3.1-generate-001",
        video_generation_location="us-central1",
        video_output_gcs_uri="gs://reviveai/videos",
    )
    _require_video_config(settings)
