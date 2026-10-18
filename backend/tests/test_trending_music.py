import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.models.audio_finishing import AudioMixOptions, MusicSource
from app.services.audio_finishing_job_service import _ffmpeg_executable, _prepare_trending_music_bed
from app.services.trending_music_service import TrendingMusicCatalog, TrendingMusicCatalogError


def _settings(tmp_path: Path):
    library = tmp_path / "music_library"
    library.mkdir()
    return SimpleNamespace(
        audio_trending_music_catalog_path=str(library / "trending_music_catalog.json"),
        audio_trending_music_library_dir=str(library),
    )


def _write_tone(path: Path, duration: float = 0.8):
    ffmpeg = _ffmpeg_executable()
    import subprocess
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={duration}:sample_rate=44100",
            "-c:a",
            "pcm_s16le",
            str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_trending_music_requires_track_selection():
    with pytest.raises(ValueError):
        AudioMixOptions(music_source=MusicSource.TRENDING_LICENSED, trending_track_id=None)

    options = AudioMixOptions(
        music_source=MusicSource.TRENDING_LICENSED,
        trending_track_id="track-1",
    )
    assert options.trending_track_id == "track-1"


def test_trending_catalog_marks_rights_cleared_local_track_ready(tmp_path: Path):
    settings = _settings(tmp_path)
    library = Path(settings.audio_trending_music_library_dir)
    tracks = library / "tracks"
    tracks.mkdir()
    audio = tracks / "track.wav"
    _write_tone(audio)
    Path(settings.audio_trending_music_catalog_path).write_text(
        json.dumps(
            {
                "updated_at": "2026-09-23T00:00:00Z",
                "tracks": [
                    {
                        "track_id": "track-1",
                        "title": "Licensed trend",
                        "artist": "Test artist",
                        "provider": "Test provider",
                        "platform": "TIKTOK",
                        "region": "PH",
                        "trend_rank": 4,
                        "render_mode": "EMBEDDED",
                        "local_file": "tracks/track.wav",
                        "license": {
                            "commercial_use_allowed": True,
                            "reference": "LIC-123",
                            "expires_at": "2027-09-23T00:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = TrendingMusicCatalog()
    response = catalog.list(settings)
    assert len(response.tracks) == 1
    assert response.tracks[0].render_ready is True
    assert response.tracks[0].usage_status == "READY"
    assert response.tracks[0].license_reference == "LIC-123"

    resolved = catalog.resolve("track-1", settings)
    assert resolved.local_path == audio.resolve()


def test_platform_only_track_is_discoverable_but_not_embeddable(tmp_path: Path):
    settings = _settings(tmp_path)
    Path(settings.audio_trending_music_catalog_path).write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "track_id": "platform-1",
                        "title": "Platform sound",
                        "platform": "TIKTOK",
                        "render_mode": "PLATFORM_ONLY",
                        "license": {"commercial_use_allowed": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    catalog = TrendingMusicCatalog()
    response = catalog.list(settings)
    assert response.tracks[0].usage_status == "PLATFORM_ONLY"
    assert response.tracks[0].render_ready is False
    with pytest.raises(TrendingMusicCatalogError):
        catalog.resolve("platform-1", settings)


def test_trending_catalog_rejects_path_escape(tmp_path: Path):
    settings = _settings(tmp_path)
    Path(settings.audio_trending_music_catalog_path).write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "track_id": "escape",
                        "title": "Unsafe",
                        "render_mode": "EMBEDDED",
                        "local_file": "../outside.mp3",
                        "license": {"commercial_use_allowed": True},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TrendingMusicCatalogError):
        TrendingMusicCatalog().list(settings)


def test_trending_music_bed_loops_and_normalizes_to_requested_duration(tmp_path: Path):
    source = tmp_path / "source.wav"
    output = tmp_path / "prepared.wav"
    _write_tone(source, duration=0.35)
    _prepare_trending_music_bed(_ffmpeg_executable(), source, output, 1.2)
    assert output.exists()
    assert output.stat().st_size > source.stat().st_size
