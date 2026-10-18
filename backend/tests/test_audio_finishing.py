from pathlib import Path

from types import SimpleNamespace

import pytest

from app.models.audio_finishing import AudioFinishingJobStage, AudioMixOptions, BackgroundMusicPreset
from app.models.final_assembly import FinalAssemblyJobStage, FinalAssemblyReviewStatus
from app.services.audio_finishing_job_service import (
    AudioFinishingJobStore,
    build_music_preview,
    _ambience_profile,
    _ffmpeg_executable,
    _generate_ambience,
    _generate_music_bed,
    _make_silence,
    _mix_audio_buses,
    _resolve_music_preset,
    _mix_layers,
    _voice_text_for_shot,
    final_assembly_job_store,
    production_brief_job_store,
)


class TimelineItem:
    def __init__(self, duration, voice="", text=""):
        self.output_duration_seconds = duration
        self.voiceover_or_dialogue = voice
        self.on_screen_text = text


def test_ambience_profile_from_audio_direction():
    assert _ambience_profile("Subtle airplane cabin hum and seatbelt chime") == "CABIN"
    assert _ambience_profile("Warm bakery room tone") == "KITCHEN"
    assert _ambience_profile("Festive wedding party") == "CELEBRATION"
    assert _ambience_profile("Quiet room") == "ROOM"


def test_voice_text_prefers_short_dialogue_and_rejects_long_copy():
    assert _voice_text_for_shot(TimelineItem(3.0, "Welcome aboard!", "Hello")) == "Welcome aboard!"
    assert _voice_text_for_shot(TimelineItem(2.0, "This sentence is far too long for such a short shot and should not be read", "First class only")) == "First class only"




def test_background_music_auto_match_and_explicit_choice():
    assert _resolve_music_preset(BackgroundMusicPreset.AUTO, "Warm hopeful lift") == BackgroundMusicPreset.WARM_INSPIRATIONAL
    assert _resolve_music_preset(BackgroundMusicPreset.AUTO, "Modern rhythmic pulse") == BackgroundMusicPreset.MODERN_PULSE
    assert _resolve_music_preset(BackgroundMusicPreset.AUTO, "Quiet reflective close") == BackgroundMusicPreset.REFLECTIVE
    assert _resolve_music_preset(BackgroundMusicPreset.AUTO, "Festive upbeat celebration") == BackgroundMusicPreset.BRIGHT_UPBEAT
    assert _resolve_music_preset(BackgroundMusicPreset.AUTO, "Sparse film underscore") == BackgroundMusicPreset.CINEMATIC_AMBIENT
    assert _resolve_music_preset(BackgroundMusicPreset.REFLECTIVE, "upbeat") == BackgroundMusicPreset.REFLECTIVE


def test_each_background_music_preset_renders(tmp_path: Path):
    ffmpeg = _ffmpeg_executable()
    for preset in (
        BackgroundMusicPreset.CINEMATIC_AMBIENT,
        BackgroundMusicPreset.WARM_INSPIRATIONAL,
        BackgroundMusicPreset.MODERN_PULSE,
        BackgroundMusicPreset.REFLECTIVE,
        BackgroundMusicPreset.BRIGHT_UPBEAT,
    ):
        output = tmp_path / f"{preset.value.lower()}.wav"
        _generate_music_bed(ffmpeg, output, 0.8, preset)
        assert output.exists() and output.stat().st_size > 1000



def test_background_music_preview_uses_same_generator_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assembly = SimpleNamespace(
        stage=FinalAssemblyJobStage.DELIVERED,
        result=SimpleNamespace(review_status=FinalAssemblyReviewStatus.APPROVED),
        production_brief_job_id="brief_preview",
    )
    production = SimpleNamespace(
        result=SimpleNamespace(
            publishing=SimpleNamespace(audio_direction="Warm hopeful inspirational lift")
        )
    )
    monkeypatch.setattr(final_assembly_job_store, "get", lambda _: assembly)
    monkeypatch.setattr(production_brief_job_store, "get", lambda _: production)
    settings = SimpleNamespace(content_dna_checkpoint_dir=str(tmp_path))

    first_path, first_effective = build_music_preview(
        "assembly_preview", BackgroundMusicPreset.AUTO, settings, duration_seconds=3.0
    )
    first_mtime = first_path.stat().st_mtime_ns
    second_path, second_effective = build_music_preview(
        "assembly_preview", BackgroundMusicPreset.AUTO, settings, duration_seconds=3.0
    )

    assert first_effective == BackgroundMusicPreset.WARM_INSPIRATIONAL
    assert second_effective == first_effective
    assert second_path == first_path
    assert second_path.exists() and second_path.stat().st_size > 1000
    assert second_path.stat().st_mtime_ns == first_mtime

def test_procedural_audio_layers_render(tmp_path: Path):
    ffmpeg = _ffmpeg_executable()
    music = tmp_path / "music.wav"
    ambience = tmp_path / "ambience.wav"
    mix = tmp_path / "mix.m4a"
    _generate_music_bed(ffmpeg, music, 1.0)
    _generate_ambience(ffmpeg, ambience, 1.0, "CABIN")
    _mix_layers(ffmpeg, [(music, 0.5), (ambience, 0.7)], mix, 1.0, -16.0)
    assert music.exists() and music.stat().st_size > 1000
    assert ambience.exists() and ambience.stat().st_size > 1000
    assert mix.exists() and mix.stat().st_size > 1000


def test_ducking_mix_and_silent_fallback_render(tmp_path: Path):
    ffmpeg = _ffmpeg_executable()
    music = tmp_path / "music.wav"
    voice = tmp_path / "voice.wav"
    ducked = tmp_path / "ducked.m4a"
    silent = tmp_path / "silent.m4a"
    _generate_music_bed(ffmpeg, music, 1.0)
    _make_silence(ffmpeg, voice, 1.0)
    options = AudioMixOptions(
        voice_volume=1.0,
        music_volume=0.65,
        ambience_volume=0.45,
        duck_music_during_voiceover=True,
    )
    _mix_audio_buses(ffmpeg, ducked, 1.0, -16.0, options, music_path=music, voice_path=voice)
    _mix_audio_buses(ffmpeg, silent, 1.0, -16.0, options)
    assert ducked.exists() and ducked.stat().st_size > 1000
    assert silent.exists() and silent.stat().st_size > 1000


def test_audio_versions_increment_without_overwriting_previous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    assembly = SimpleNamespace(
        stage=FinalAssemblyJobStage.DELIVERED,
        result=SimpleNamespace(
            review_status=FinalAssemblyReviewStatus.APPROVED,
            final_video=SimpleNamespace(asset_id="visual_master_1"),
        ),
        production_brief_job_id="brief_1",
        media_job_id="media_1",
        channel_id="channel_1",
    )
    monkeypatch.setattr(final_assembly_job_store, "get", lambda _: assembly)
    store = AudioFinishingJobStore(str(tmp_path))
    # Isolate version history from Firestore and other tests. This test verifies
    # local version semantics, not the cloud repository integration.
    monkeypatch.setattr(store._cloud, "stream", lambda: iter(()))
    monkeypatch.setattr(store._cloud, "load", lambda _id: None)
    monkeypatch.setattr(store._cloud, "save", lambda _id, _payload: None)

    first = store.create("assembly_1", AudioMixOptions())
    assert first.version_number == 1
    assert first.based_on_job_id is None

    first.stage = AudioFinishingJobStage.COMPLETED
    store.save(first)
    second = store.create("assembly_1", AudioMixOptions(music_volume=0.7))

    assert second.version_number == 2
    assert second.based_on_job_id == first.job_id
    assert store.get(first.job_id).options.music_volume == 0.55
    assert store.get(second.job_id).options.music_volume == 0.7
