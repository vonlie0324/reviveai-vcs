import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.audio_finishing import (
    TrendingMusicRenderMode,
    TrendingMusicTrack,
    YouTubeAudioLibraryLicenseType,
    YouTubeAudioLibraryTrack,
)
from app.models.final_assembly import FinalAssemblyReviewStatus
from app.models.music_match import MusicMatchContext, MusicMatchPacing, MusicMatchResult
from app.services import music_match_service as svc


def _settings(tmp_path):
    return SimpleNamespace(
        content_dna_checkpoint_dir=str(tmp_path),
        google_cloud_project="",
        google_cloud_location="global",
        gemini_model="gemini-test",
        content_dna_retry_attempts=1,
    )


def _assembly_and_production(*, audio_direction="calm reflective gentle underscore", tone=None, narrative_arc="gentle intimate close"):
    timeline = [
        SimpleNamespace(output_duration_seconds=3.0, voiceover_or_dialogue="Welcome aboard"),
        SimpleNamespace(output_duration_seconds=3.0, voiceover_or_dialogue="First class service"),
        SimpleNamespace(output_duration_seconds=3.0, voiceover_or_dialogue="Fresh orange juice"),
        SimpleNamespace(output_duration_seconds=3.0, voiceover_or_dialogue="Thank you"),
    ]
    assembly = SimpleNamespace(
        job_id="assembly_1",
        production_brief_job_id="brief_1",
        result=SimpleNamespace(
            review_status=FinalAssemblyReviewStatus.APPROVED,
            total_duration_seconds=15.0,
            timeline=timeline,
        ),
    )
    production = SimpleNamespace(
        job_id="brief_1",
        channel_id="channel_test",
        result=SimpleNamespace(
            creative_direction=SimpleNamespace(
                working_title="Pawshionista Airways",
                tone=tone or ["calm", "gentle", "wholesome"],
                narrative_arc=narrative_arc,
            ),
            publishing=SimpleNamespace(audio_direction=audio_direction),
        )
    )
    return assembly, production


def test_music_match_uses_active_speech_time_instead_of_full_shot_duration(tmp_path, monkeypatch):
    assembly, production = _assembly_and_production()
    monkeypatch.setattr(svc.final_assembly_job_store, "get", lambda _job_id: assembly)
    monkeypatch.setattr(svc.production_brief_job_store, "get", lambda _job_id: production)
    saved_track = YouTubeAudioLibraryTrack(
        track_id="yt-reflective", title="Quiet Reflection", artist="Artist",
        genre="Ambient", mood="calm, reflective, gentle", duration_seconds=120,
        license_type=YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY,
        attribution_required=False, imported_at=datetime.now(timezone.utc),
        filename="reflective.mp3", render_ready=True, preview_available=True,
    )
    monkeypatch.setattr(svc.youtube_audio_library, "list", lambda _settings: SimpleNamespace(tracks=[saved_track]))

    service = svc.MusicMatchService(_settings(tmp_path))
    result = asyncio.run(service.generate("assembly_1"))

    assert result.context.narration_density == 0.304
    assert result.context.narration_seconds == 4.562
    assert result.context.narration_density < 1.0
    assert result.context.pacing == MusicMatchPacing.BALANCED
    assert result.model == "deterministic-fallback"
    assert result.recommendations[0].candidate_key == "youtube:yt-reflective"
    assert result.recommendations[0].score >= result.recommendations[-1].score
    assert all("performance" not in item.fit_summary.lower() for item in result.recommendations)


def test_music_match_only_includes_render_ready_external_tracks(tmp_path, monkeypatch):
    assembly, production = _assembly_and_production(audio_direction="warm hopeful uplifting")
    monkeypatch.setattr(svc.final_assembly_job_store, "get", lambda _job_id: assembly)
    monkeypatch.setattr(svc.production_brief_job_store, "get", lambda _job_id: production)

    youtube_tracks = [
        YouTubeAudioLibraryTrack(
            track_id="yt-ready", title="Warm Morning", artist="Artist", genre="Acoustic", mood="warm, hopeful",
            duration_seconds=120, license_type=YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY,
            attribution_required=False, imported_at=datetime.now(timezone.utc), filename="ready.mp3",
            render_ready=True, preview_available=True,
        ),
        YouTubeAudioLibraryTrack(
            track_id="yt-missing", title="Missing File", imported_at=datetime.now(timezone.utc), filename="missing.mp3",
            render_ready=False, preview_available=False,
        ),
    ]
    trending_tracks = [
        TrendingMusicTrack(
            track_id="trend-ready", title="Licensed Hope", artist="Artist", provider="Provider", platform="TIKTOK",
            region="PH", genre="Pop", moods=["hopeful", "warm"], render_mode=TrendingMusicRenderMode.EMBEDDED,
            commercial_use_allowed=True, render_ready=True, preview_available=True, usage_status="READY",
        ),
        TrendingMusicTrack(
            track_id="trend-platform", title="Platform Only", platform="TIKTOK", region="PH",
            render_mode=TrendingMusicRenderMode.PLATFORM_ONLY, commercial_use_allowed=True,
            render_ready=False, preview_available=False, usage_status="PLATFORM_ONLY",
        ),
    ]
    monkeypatch.setattr(svc.youtube_audio_library, "list", lambda _settings: SimpleNamespace(tracks=youtube_tracks))
    monkeypatch.setattr(svc.trending_music_catalog, "list", lambda _settings: SimpleNamespace(tracks=trending_tracks))

    result = asyncio.run(svc.MusicMatchService(_settings(tmp_path)).generate("assembly_1"))
    keys = {item.candidate_key for item in result.recommendations}

    assert "youtube:yt-missing" not in keys
    assert "trend:trend-platform" not in keys
    assert result.evaluated_candidates == 1  # Saved soundtracks are the only eligible source.
    assert any(item.candidate_key == "youtube:yt-ready" for item in result.recommendations)
    assert not any(item.candidate_key.startswith("trend:") for item in result.recommendations)


def test_music_match_store_round_trip(tmp_path):
    store = svc.MusicMatchStore(str(tmp_path))
    result = MusicMatchResult(
        assembly_job_id="assembly_99",
        production_brief_job_id="brief_99",
        generated_at=datetime.now(timezone.utc),
        model="deterministic-fallback",
        context=MusicMatchContext(
            working_title="Test",
            tone=["warm"],
            total_duration_seconds=15,
            narration_seconds=6,
            narration_density=0.4,
            shot_count=4,
            average_shot_seconds=3.75,
            pacing=MusicMatchPacing.BALANCED,
        ),
        evaluated_candidates=0,
        recommendations=[],
    )
    store.save(result)
    loaded = store.get_latest("assembly_99")
    assert loaded is not None
    assert loaded.assembly_job_id == "assembly_99"
    assert loaded.context.tone == ["warm"]
