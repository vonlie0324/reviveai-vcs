from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models.audio_finishing import (
    AudioMixOptions,
    MusicSource,
    YouTubeAudioLibraryLicenseType,
)
from app.services.youtube_audio_library_service import (
    YouTubeAudioLibrary,
    YouTubeAudioLibraryError,
    YouTubeAudioLibraryTrackNotFoundError,
)



@pytest.fixture(autouse=True)
def isolated_soundtrack_cloud(monkeypatch, tmp_path):
    """Never contact the configured live Firestore/GCS from catalog unit tests."""
    from app.services import youtube_audio_library_service as module
    from app.api.routes import audio_finishing as routes

    class MemoryRepository:
        def __init__(self):
            self.rows = {}

        def create(self, track_id, payload):
            self.rows[track_id] = dict(payload)
            return dict(payload)

        def get(self, track_id):
            row = self.rows.get(track_id)
            return dict(row) if row is not None else None

        def list(self, channel_id=None):
            rows = list(self.rows.values())
            if channel_id:
                rows = [r for r in rows if r.get("channel_id") == channel_id]
            return [dict(r) for r in rows]

        def delete(self, track_id):
            self.rows.pop(track_id, None)

    class MemoryStorage:
        def __init__(self):
            self.objects = {}

        def build_path(self, filename):
            # Mirrors CloudStorageService.build_path without touching GCS.
            return f"soundtracks/{filename}".strip("/")

        def upload_file(self, source_path, storage_path, **kwargs):
            self.objects[storage_path] = Path(source_path).read_bytes()
            return storage_path

        def download_file(self, storage_path, destination_path):
            data = self.objects[storage_path]
            destination = Path(destination_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return destination

        def delete(self, storage_path):
            self.objects.pop(storage_path, None)

    repo = MemoryRepository()
    storage = MemoryStorage()
    monkeypatch.setattr(module, "create_soundtrack_repository", lambda: repo)
    monkeypatch.setattr(module, "create_cloud_storage_service", lambda _uri: storage)
    # API endpoints use an existing module-level singleton; isolate it too.
    existing = routes.youtube_audio_library
    monkeypatch.setattr(existing, "firestore_repository", repo)
    monkeypatch.setattr(existing, "cloud_storage", storage)
    monkeypatch.setattr(existing, "_legacy_migration_checked", set())
    monkeypatch.setattr(module.YouTubeAudioLibrary, "_cache_path", lambda self, track_id, filename: tmp_path / "cache" / f"{track_id}{Path(filename).suffix}")

def _wav_bytes(seconds: float = 0.05) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * int(8000 * seconds))
    return buffer.getvalue()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        audio_youtube_library_catalog_path=str(tmp_path / "catalog.json"),
        audio_youtube_library_dir=str(tmp_path / "library"),
        audio_youtube_library_max_upload_mb=5,
    )


def test_import_list_resolve_preview_and_delete(tmp_path: Path):
    service = YouTubeAudioLibrary()
    settings = _settings(tmp_path)
    track = service.import_track(
        settings,
        file_bytes=_wav_bytes(),
        original_filename="quiet-day.wav",
        title="Quiet Day",
        artist="Example Artist",
        genre="Cinematic",
        mood="Reflective",
        license_type=YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY,
        attribution_required=False,
        attribution_text=None,
        source_url=None,
    )

    assert track.track_id.startswith("ytlib_")
    assert track.render_ready is True
    assert track.genre == "Cinematic"
    assert track.mood == "Reflective"
    assert track.duration_seconds is not None and track.duration_seconds > 0
    catalog = service.list(settings)
    assert [item.track_id for item in catalog.tracks] == [track.track_id]

    resolved = service.resolve(track.track_id, settings)
    assert resolved.local_path.exists()
    preview_path, preview_mime = service.preview_path(track.track_id, settings)
    assert preview_path == resolved.local_path
    assert preview_mime in {"audio/wav", "audio/x-wav"}

    service.delete(track.track_id, settings)
    assert service.list(settings).tracks == []
    assert not resolved.local_path.exists()
    with pytest.raises(YouTubeAudioLibraryTrackNotFoundError):
        service.resolve(track.track_id, settings)


def test_creative_commons_import_requires_attribution(tmp_path: Path):
    service = YouTubeAudioLibrary()
    settings = _settings(tmp_path)

    with pytest.raises(YouTubeAudioLibraryError, match="Attribution text is required"):
        service.import_track(
            settings,
            file_bytes=_wav_bytes(),
            original_filename="cc.wav",
            title="CC Track",
            artist="Artist",
            license_type=YouTubeAudioLibraryLicenseType.CREATIVE_COMMONS,
            attribution_required=False,
            attribution_text=None,
            source_url=None,
        )

    track = service.import_track(
        settings,
        file_bytes=_wav_bytes(),
        original_filename="cc.wav",
        title="CC Track",
        artist="Artist",
        license_type=YouTubeAudioLibraryLicenseType.CREATIVE_COMMONS,
        attribution_required=False,
        attribution_text="CC BY attribution supplied by YouTube Audio Library",
        source_url="https://studio.youtube.com/",
    )
    assert track.attribution_required is True
    assert track.attribution_text


def test_import_rejects_unsupported_file_format(tmp_path: Path):
    service = YouTubeAudioLibrary()
    settings = _settings(tmp_path)
    with pytest.raises(YouTubeAudioLibraryError, match="Unsupported audio format"):
        service.import_track(
            settings,
            file_bytes=b"not audio",
            original_filename="track.exe",
            title="Bad Track",
            artist="",
            license_type=YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY,
            attribution_required=False,
            attribution_text=None,
            source_url=None,
        )


def test_audio_mix_options_allow_saved_soundtrack_auto_selection():
    # A missing explicit track ID is intentional: the render service may
    # auto-select a render-ready track from the creator's Saved soundtracks.
    automatic = AudioMixOptions(music_source=MusicSource.YOUTUBE_AUDIO_LIBRARY)
    assert automatic.youtube_audio_library_track_id is None

    explicit = AudioMixOptions(
        music_source=MusicSource.YOUTUBE_AUDIO_LIBRARY,
        youtube_audio_library_track_id="ytlib_example",
    )
    assert explicit.youtube_audio_library_track_id == "ytlib_example"


def test_youtube_audio_library_import_api(tmp_path: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.routes.audio_finishing import router
    from app.core.config import get_settings

    settings = _settings(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_settings] = lambda: settings
    client = TestClient(app)

    response = client.post(
        "/api/v1/youtube/music-catalog/youtube-audio-library/import",
        data={
            "title": "API Track",
            "artist": "API Artist",
            "genre": "Ambient",
            "mood": "Calm",
            "license_type": "YOUTUBE_AUDIO_LIBRARY",
            "attribution_required": "false",
            "attribution_text": "",
            "source_url": "",
            "confirm_rights": "true",
        },
        files={"file": ("api-track.wav", _wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 201
    body = response.json()
    track_id = body["track_id"]
    assert body["genre"] == "Ambient"
    assert body["mood"] == "Calm"
    assert body["duration_seconds"] is not None

    catalog = client.get("/api/v1/youtube/music-catalog/youtube-audio-library")
    assert catalog.status_code == 200
    assert catalog.json()["tracks"][0]["track_id"] == track_id

    preview = client.get(f"/api/v1/youtube/music-catalog/youtube-audio-library/{track_id}/preview")
    assert preview.status_code == 200
    assert preview.content.startswith(b"RIFF")


def test_import_rejects_corrupt_audio_even_with_supported_extension(tmp_path: Path):
    service = YouTubeAudioLibrary()
    settings = _settings(tmp_path)
    with pytest.raises(YouTubeAudioLibraryError, match="not readable audio"):
        service.import_track(
            settings,
            file_bytes=b"this is not a wav file",
            original_filename="broken.wav",
            title="Broken",
            artist="",
            license_type=YouTubeAudioLibraryLicenseType.YOUTUBE_AUDIO_LIBRARY,
            attribution_required=False,
            attribution_text=None,
            source_url=None,
        )
