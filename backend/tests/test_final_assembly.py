from datetime import datetime, timezone
from pathlib import Path

from app.models.final_assembly import FinalAssemblyJob, FinalAssemblyJobStage
from app.services.final_assembly_job_service import FinalAssemblyJobStore, _concat_segments, _timestamp, _write_srt


class Shot:
    def __init__(self, duration_seconds, voiceover_or_dialogue="", on_screen_text=""):
        self.duration_seconds = duration_seconds
        self.voiceover_or_dialogue = voiceover_or_dialogue
        self.on_screen_text = on_screen_text


def test_timestamp_format():
    assert _timestamp(0) == "00:00:00,000"
    assert _timestamp(65.432) == "00:01:05,432"


def test_write_srt_uses_voiceover_then_on_screen_text(tmp_path: Path):
    path = tmp_path / "captions.srt"
    shots = [
        Shot(3.5, "Hello there", "Ignored because voiceover exists"),
        Shot(4.0, "", "Second caption"),
    ]
    assert _write_srt(path, shots)
    text = path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:03,500" in text
    assert "Hello there" in text
    assert "00:00:03,500 --> 00:00:07,500" in text
    assert "Second caption" in text


def test_latest_final_assembly_for_media_job_survives_store_restart(tmp_path):
    store = FinalAssemblyJobStore(str(tmp_path))
    now = datetime.now(timezone.utc)
    first = FinalAssemblyJob(
        job_id="assembly_first", media_job_id="media_1", production_brief_job_id="prod_1", channel_id="UCtest",
        stage=FinalAssemblyJobStage.QUEUED, message="first", created_at=now, updated_at=now,
    )
    store.save(first)
    second = FinalAssemblyJob(
        job_id="assembly_second", media_job_id="media_1", production_brief_job_id="prod_1", channel_id="UCtest",
        stage=FinalAssemblyJobStage.COMPLETED, message="second", created_at=now, updated_at=now,
    )
    store.save(second)

    restarted = FinalAssemblyJobStore(str(tmp_path))
    latest = restarted.latest_for_media_job("media_1")
    assert latest is not None
    assert latest.job_id == "assembly_second"


def test_concat_manifest_uses_paths_relative_to_manifest_directory(tmp_path, monkeypatch):
    work_dir = tmp_path / ".reviveai_checkpoints" / "final_assembly" / "assembly_test" / "work"
    work_dir.mkdir(parents=True)
    segment_1 = work_dir / "segment-01.mp4"
    segment_2 = work_dir / "segment-02.mp4"
    segment_1.write_bytes(b"one")
    segment_2.write_bytes(b"two")
    destination = work_dir.parent / "assets" / "final.mp4"
    destination.parent.mkdir(parents=True)

    captured = {}

    def fake_run(command):
        captured["command"] = command

    monkeypatch.setattr("app.services.final_assembly_job_service._run", fake_run)
    _concat_segments("ffmpeg", [segment_1, segment_2], destination, work_dir)

    manifest = (work_dir / "concat.txt").read_text(encoding="utf-8")
    assert manifest == "file 'segment-01.mp4'\nfile 'segment-02.mp4'\n"
    assert str((work_dir / "concat.txt").resolve()) in captured["command"]
    assert str(destination.resolve()) in captured["command"]
