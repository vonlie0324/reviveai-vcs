from datetime import datetime, timezone
from pathlib import Path
import subprocess
import zipfile

import pytest

from app.core.config import Settings
from app.models.audio_finishing import (
    AudioFinishingJob,
    AudioFinishingJobStage,
    AudioFinishingResult,
    AudioFinishingReviewStatus,
    AudioLayerSummary,
    AudioMixOptions,
    BackgroundMusicPreset,
    MusicSource,
)
from app.models.delivery_qc import DeliveryQcOverallStatus, DeliveryQcReport
from app.models.final_assembly import AssemblyAsset, AssemblyAssetKind
from app.models.production_brief import PublishingPackage
from app.services import delivery_package_service as svc


def _make_master(path: Path, *, duration: float = 1.2) -> None:
    ffmpeg = svc._ffmpeg_executable()
    result = subprocess.run(
        [
            ffmpeg, "-y",
            "-f", "lavfi", "-i", f"color=c=0x203040:s=720x1280:r=30:d={duration}",
            "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=44100:duration={duration}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _audio_job(master: Path, subtitles: Path) -> AudioFinishingJob:
    now = datetime.now(timezone.utc)
    delivery = AssemblyAsset(
        asset_id="delivery_1",
        kind=AssemblyAssetKind.FINAL_VIDEO,
        created_at=now,
        filename=master.name,
        mime_type="video/mp4",
        asset_url="/master.mp4",
    )
    subtitle_asset = AssemblyAsset(
        asset_id="subs_1",
        kind=AssemblyAssetKind.SUBTITLES,
        created_at=now,
        filename=subtitles.name,
        mime_type="application/x-subrip",
        asset_url="/captions.srt",
    )
    publishing = PublishingPackage(
        youtube_title="Test Short",
        description="A delivery-ready test description.",
        social_caption="Test caption",
        hashtags=["#reviveai"],
        thumbnail_concept="Hero frame",
        audio_direction="Warm and clear",
        accessibility_alt_text="A simple test frame.",
        review_notes=[],
    )
    result = AudioFinishingResult(
        assembly_job_id="assembly_1",
        production_brief_job_id="brief_1",
        media_job_id="media_1",
        working_title="Pawshionista Airways",
        rendered_at=now,
        total_duration_seconds=1.2,
        delivery_video=delivery,
        subtitles=subtitle_asset,
        publishing=publishing,
        options=AudioMixOptions(music_enabled=False, voiceover_enabled=False, ambience_sfx_enabled=True),
        layers=[AudioLayerSummary(key="ambience", label="Ambience + SFX", enabled=True, generated=True, detail="Test ambience")],
        effective_music_preset=BackgroundMusicPreset.CINEMATIC_AMBIENT,
        effective_music_source=MusicSource.REVIVEAI,
        review_status=AudioFinishingReviewStatus.APPROVED,
        reviewed_at=now,
    )
    return AudioFinishingJob(
        job_id="audio_1",
        assembly_job_id="assembly_1",
        production_brief_job_id="brief_1",
        media_job_id="media_1",
        channel_id="channel_1",
        version_number=10,
        stage=AudioFinishingJobStage.DELIVERED,
        message="approved",
        created_at=now,
        updated_at=now,
        options=result.options,
        detail={"source_visual_asset_id": "visual_1", "visual_master_preserved": True},
        result=result,
    )


def _qc(status: DeliveryQcOverallStatus = DeliveryQcOverallStatus.READY) -> DeliveryQcReport:
    now = datetime.now(timezone.utc)
    return DeliveryQcReport(
        report_id="qc_1",
        audio_job_id="audio_1",
        assembly_job_id="assembly_1",
        audio_version=10,
        generated_at=now,
        overall_status=status,
        ready_for_delivery=status != DeliveryQcOverallStatus.BLOCKED,
        pass_count=17 if status == DeliveryQcOverallStatus.READY else 16,
        warn_count=0 if status == DeliveryQcOverallStatus.READY else 1,
        fail_count=0,
        source_visual_asset_id="visual_1",
        delivery_asset_id="delivery_1",
        checks=[],
        metrics={
            "container": {"width": 720, "height": 1280, "fps": 30.0},
            "loudness": {"integrated_lufs": -15.8, "true_peak_dbfs": -1.4},
        },
    )


def test_delivery_package_builds_versioned_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = tmp_path / "master.mp4"
    subtitles = tmp_path / "captions.srt"
    _make_master(master)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,200\nWelcome aboard\n", encoding="utf-8")
    audio_job = _audio_job(master, subtitles)
    report = _qc()

    store = svc.DeliveryPackageStore(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "delivery_package_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: audio_job)
    monkeypatch.setattr(
        svc.audio_finishing_job_store,
        "asset_path",
        lambda _job_id, asset_id: (master, "video/mp4") if asset_id == "delivery_1" else (subtitles, "application/x-subrip"),
    )
    monkeypatch.setattr(svc.delivery_qc_store, "get", lambda _job_id: report)

    package = svc.create_delivery_package("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))

    assert package.audio_version == 10
    assert package.package_version == 1
    assert package.qc_report_id == "qc_1"
    assert package.zip_asset.size_bytes > 0
    assert {asset.key for asset in package.assets} >= {
        "master_video", "captions_srt", "captions_vtt", "thumbnail", "youtube_description",
        "music_attribution", "production_summary", "delivery_qc", "readme",
    }

    zip_path, _, _ = store.asset_path(package.package_id, "package_zip")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    assert any(name.endswith("-master-v10.mp4") for name in names)
    assert any("/captions/captions.vtt" in name for name in names)
    assert any("/metadata/delivery-qc.json" in name for name in names)
    assert any("/publishing/youtube-description.txt" in name for name in names)


def test_delivery_package_is_idempotent_for_same_qc_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = tmp_path / "master.mp4"
    subtitles = tmp_path / "captions.srt"
    _make_master(master)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,200\nHello\n", encoding="utf-8")
    audio_job = _audio_job(master, subtitles)
    report = _qc()
    store = svc.DeliveryPackageStore(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "delivery_package_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: audio_job)
    monkeypatch.setattr(svc.audio_finishing_job_store, "asset_path", lambda _job_id, asset_id: (master, "video/mp4") if asset_id == "delivery_1" else (subtitles, "application/x-subrip"))
    monkeypatch.setattr(svc.delivery_qc_store, "get", lambda _job_id: report)

    first = svc.create_delivery_package("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))
    second = svc.create_delivery_package("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))

    assert second.package_id == first.package_id
    assert second.package_version == first.package_version


def test_delivery_package_requires_ready_qc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    master = tmp_path / "master.mp4"
    subtitles = tmp_path / "captions.srt"
    _make_master(master)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,200\nHello\n", encoding="utf-8")
    audio_job = _audio_job(master, subtitles)
    store = svc.DeliveryPackageStore(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "delivery_package_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: audio_job)
    monkeypatch.setattr(svc.delivery_qc_store, "get", lambda _job_id: _qc(DeliveryQcOverallStatus.REVIEW))

    with pytest.raises(svc.DeliveryPackageError, match="READY"):
        svc.create_delivery_package("audio_1", Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints")))


def test_delivery_package_creates_new_version_with_approved_publishing_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.models.publishing_assistant import (
        InstagramPublishingCopy,
        PublishingDraft,
        PublishingDraftContent,
        PublishingDraftStatus,
        TikTokPublishingCopy,
        YouTubePublishingCopy,
    )

    master = tmp_path / "master.mp4"
    subtitles = tmp_path / "captions.srt"
    _make_master(master)
    subtitles.write_text("1\n00:00:00,000 --> 00:00:01,200\nHello\n", encoding="utf-8")
    audio_job = _audio_job(master, subtitles)
    report = _qc()
    store = svc.DeliveryPackageStore(str(tmp_path / "checkpoints"))
    monkeypatch.setattr(svc, "delivery_package_store", store)
    monkeypatch.setattr(svc.audio_finishing_job_store, "get", lambda _job_id: audio_job)
    monkeypatch.setattr(svc.audio_finishing_job_store, "asset_path", lambda _job_id, asset_id: (master, "video/mp4") if asset_id == "delivery_1" else (subtitles, "application/x-subrip"))
    monkeypatch.setattr(svc.delivery_qc_store, "get", lambda _job_id: report)
    settings = Settings(content_dna_checkpoint_dir=str(tmp_path / "checkpoints"))

    base = svc.create_delivery_package("audio_1", settings)
    now = datetime.now(timezone.utc)
    draft = PublishingDraft(
        draft_id="publishing_1",
        assembly_job_id="assembly_1",
        audio_job_id="audio_1",
        audio_version=10,
        source_package_id=base.package_id,
        source_package_version=base.package_version,
        qc_report_id="qc_1",
        version_number=1,
        generated_at=now,
        updated_at=now,
        model="gemini-test",
        status=PublishingDraftStatus.APPROVED,
        approved_at=now,
        content=PublishingDraftContent(
            youtube=YouTubePublishingCopy(title="Creator YouTube title", description="Creator description", hashtags=["#Pets"], tags=["pets"], thumbnail_text_suggestions=["Boarding now"]),
            tiktok=TikTokPublishingCopy(hook="POV", caption="TikTok caption", hashtags=["#PetTok"], cta="Follow for more"),
            instagram=InstagramPublishingCopy(caption_short="Short", caption_long="Instagram caption", hashtags=["#PetReels"], alt_text="A dog flight attendant.", cta="Save this"),
        ),
    )

    enriched = svc.create_delivery_package("audio_1", settings, draft)
    assert enriched.package_version == 2
    assert enriched.publishing_draft_id == draft.draft_id
    assert enriched.publishing_draft_version == 1
    keys = {asset.key for asset in enriched.assets}
    assert {"youtube_title", "youtube_hashtags", "tiktok_caption", "instagram_caption", "instagram_alt_text", "publishing_draft"} <= keys

    zip_path, _, _ = store.asset_path(enriched.package_id, "package_zip")
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        title_name = next(name for name in names if name.endswith("/publishing/youtube-title.txt"))
        assert archive.read(title_name).decode("utf-8").strip() == "Creator YouTube title"
