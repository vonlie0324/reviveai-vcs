"""Static regression checks for all fidelity review call sites."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "app"

def test_every_fidelity_call_propagates_channel_identity():
    service = (ROOT / "services" / "media_studio_job_service.py").read_text()
    assert service.count("service.review_keyframe_fidelity(") == 3
    for fragment in service.split("service.review_keyframe_fidelity(")[1:]:
        assert "channel_id=job.channel_id" in fragment.split(")", 1)[0]

def test_fidelity_review_reserves_per_attempt_and_checks_allocation():
    source = (ROOT / "services" / "media_generation_service.py").read_text()
    assert "gemini_fidelity_" in source
    assert "ensure_production_budget(" in source
    assert "Fidelity review provider outcome uncertain" in source
    assert "gemini-2.5-flash-image retired" in source

def test_new_image_model_default():
    config = (ROOT / "core" / "config.py").read_text()
    assert 'image_generation_model: str = "gemini-3.1-flash-image"' in config
