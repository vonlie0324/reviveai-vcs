from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

from app.core.config import Settings
from app.models.audio_finishing import (
    AudioFinishingJobStage,
    AudioFinishingReviewStatus,
    AudioMixOptions,
    MusicSource,
)
from app.models.final_assembly import FinalAssemblyReviewStatus
from app.services import delivery_qc_service as qc


def _make_master(path: Path, *, duration: float = 1.5) -> None:
    ffmpeg = qc._ffmpeg_executable()
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=30:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration}",
            "-filter:a", "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-shortest", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _fake_jobs(master: Path, *, source_visual_id: str = "visual_1"):
    delivery_asset = SimpleNamespace(asset_id="delivery_1")
    mix_asset = SimpleNamespace(asset_id="mix_1")
    audio_result = SimpleNamespace(
        review_status=AudioFinishingReviewStatus.APPROVED,
        total_duration_seconds=1.5,
        delivery_video=delivery_asset,
        audio_mix=mix_asset,
        subtitles=None,
        options=AudioMixOptions(music_enabled=False, voiceover_enabled=False, ambience_sfx_enabled=True),
        layers=[],
        voiceover_cues=[],
        effective_music_source=MusicSource.REVIVEAI,
        selected_youtube_audio_library_track=None,
        selected_trending_track=None,
        publishing=SimpleNamespace(description=""),
        warnings=[],
    )
    audio_job = SimpleNamespace(
        job_id="audio_1",
        assembly_job_id="assembly_1",
        version_number=3,
        stage=AudioFinishingJobStage.DELIVERED,
        result=audio_result,
        detail={"source_visual_asset_id": source_visual_id, "visual_master_preserved": True},
    )
    assembly_result = SimpleNamespace(
        review_status=FinalAssemblyReviewStatus.APPROVED,
        final_video=SimpleNamespace(asset_id="visual_1"),
        subtitles=None,
        captions_burned_in=True,
    )
    assembly_job = SimpleNamespace(result=assembly_result, detail={"approval_actor": "creator"})
    return audio_job, assembly_job


def test_media_probe_and_loudness_analysis(tmp_path: Path):
    master = tmp_path / "master.mp4"
    _make_master(master)
    ffmpeg = qc._ffmpeg_executable()

    probe = qc._parse_probe(ffmpeg, master)
    loudness = qc._analyze_loudness(ffmpeg, master, -16.0)
    decode_ok, decode_error = qc._decode_check(ffmpeg, master)

    assert probe["width"] == 720
    assert probe["height"] == 1280
    assert probe["video_codec"] == "h264"
    assert probe["audio_codec"] == "aac"
    assert probe["duration_seconds"] == pytest.approx(1.5, abs=0.05)
    assert loudness["integrated_lufs"] == pytest.approx(-16.0, abs=1.5)
    assert decode_ok is True
    assert decode_error == ""


def test_delivery_qc_ready_for_clean_approved_master(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = tmp_path / "master.mp4"
    _make_master(master)
    audio_job, assembly_job = _fake_jobs(master)

    monkeypatch.setattr(qc.audio_finishing_job_store, "get", lambda _: audio_job)
    monkeypatch.setattr(qc.audio_finishing_job_store, "asset_path", lambda _job, _asset: (master, "video/mp4"))
    monkeypatch.setattr(qc.final_assembly_job_store, "get", lambda _: assembly_job)
    monkeypatch.setattr(qc.delivery_qc_store, "save", lambda _report: None)

    report = qc.run_delivery_qc("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path)))

    assert report.overall_status.value == "READY"
    assert report.ready_for_delivery is True
    assert report.fail_count == 0
    assert any(item.key == "visual_master_lineage" and item.status.value == "PASS" for item in report.checks)
    assert any(item.key == "loudness" and item.status.value == "PASS" for item in report.checks)


def test_delivery_qc_blocks_when_visual_lineage_does_not_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = tmp_path / "master.mp4"
    _make_master(master)
    audio_job, assembly_job = _fake_jobs(master, source_visual_id="wrong_visual")

    monkeypatch.setattr(qc.audio_finishing_job_store, "get", lambda _: audio_job)
    monkeypatch.setattr(qc.audio_finishing_job_store, "asset_path", lambda _job, _asset: (master, "video/mp4"))
    monkeypatch.setattr(qc.final_assembly_job_store, "get", lambda _: assembly_job)
    monkeypatch.setattr(qc.delivery_qc_store, "save", lambda _report: None)

    report = qc.run_delivery_qc("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path)))

    assert report.overall_status.value == "BLOCKED"
    assert report.ready_for_delivery is False
    assert any(item.key == "visual_master_lineage" and item.status.value == "FAIL" for item in report.checks)
