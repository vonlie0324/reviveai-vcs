from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.recovery import EvidenceStrength, NextContentRecommendation, RecoveryJobStage, RecoveryResult
from app.services import revival_program_service as svc


def _recommendation(rank: int, strength: EvidenceStrength, lane: str):
    return NextContentRecommendation(
        rank=rank,
        recommendation_id=f"rec_{rank}",
        title=f"Idea {rank}",
        concept=f"Concept {rank}",
        hook=f"Hook {rank}",
        format="Short-form vertical",
        why_this_fits=f"Evidence-linked reason {rank}",
        evidence_strength=strength,
        novelty_label="Adjacent",
        novelty_score=0.65,
        strategy_lanes=[lane],
    )


def _recovery_job():
    recommendations = [
        _recommendation(1, EvidenceStrength.STRONG, "Character-led service roleplay"),
        _recommendation(2, EvidenceStrength.STRONG, "Character-led service roleplay"),
        _recommendation(3, EvidenceStrength.SUPPORTED, "Miniature luxury experiences"),
        _recommendation(4, EvidenceStrength.SUPPORTED, "Miniature luxury experiences"),
        _recommendation(5, EvidenceStrength.SUPPORTED, "Retro roleplay"),
        _recommendation(6, EvidenceStrength.EXPLORATORY, "Retro roleplay"),
        _recommendation(7, EvidenceStrength.EXPLORATORY, "Novel experiments"),
        _recommendation(8, EvidenceStrength.EXPLORATORY, "Novel experiments"),
    ]
    return SimpleNamespace(
        job_id="recovery_1",
        analysis_job_id="analysis_1",
        stage=RecoveryJobStage.COMPLETED,
        result=RecoveryResult(
            generated_at=datetime.now(timezone.utc),
            model="gemini-test",
            gemini_calls=1,
            recommendations=recommendations,
        ),
    )


def _isolated_store(tmp_path, monkeypatch):
    """Keep test programs local to tmp_path and away from real Firestore.

    A reused recovery ID must never load a saved program from another run,
    nor write test fixtures to a connected project.
    """
    store = svc.RevivalProgramStore(str(tmp_path))
    monkeypatch.setattr(store._cloud, "load", lambda _job_id: None)
    monkeypatch.setattr(store._cloud, "save", lambda _job_id, _payload: None)
    return store


def test_revival_program_builds_four_week_slate_without_performance_prediction(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    monkeypatch.setattr(svc.recovery_job_store, "get", lambda _job_id: _recovery_job())
    monkeypatch.setattr(
        svc.job_store,
        "get",
        lambda _job_id: SimpleNamespace(result=SimpleNamespace(channel=SimpleNamespace(channel_id="channel_1", title="Pawshionista"))),
    )

    program = store.create_for_recovery("recovery_1")

    assert program.duration_days == 30
    assert program.cadence_per_week == 2  # eight ideas over four weeks, without historical cadence
    assert program.recommended_cadence_per_week == 2
    assert program.target_posts == 8
    assert len(program.weekly_slate) == 8
    # Eight ideas at two posts/week fill all four weeks.
    assert {slot.week for slot in program.weekly_slate} == {1, 2, 3, 4}
    assert all(1 <= slot.week <= 4 for slot in program.weekly_slate)
    assert program.ideas[0].lane.value == "CORE"
    assert program.ideas[-1].lane.value == "EXPERIMENT"
    assert all("virality" not in idea.why_now.lower() for idea in program.ideas)
    assert "not a prediction" in program.guidance.lower()


def test_revival_program_round_trip_is_idempotent(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    monkeypatch.setattr(svc.recovery_job_store, "get", lambda _job_id: _recovery_job())
    monkeypatch.setattr(
        svc.job_store,
        "get",
        lambda _job_id: SimpleNamespace(result=SimpleNamespace(channel=SimpleNamespace(channel_id="channel_1", title="Pawshionista"))),
    )
    first = store.create_for_recovery("recovery_1")
    second = store.create_for_recovery("recovery_1")
    loaded = store.get_for_recovery("recovery_1")
    assert first.program_id == second.program_id == loaded.program_id
    assert [item.recommendation_id for item in loaded.ideas] == [f"rec_{i}" for i in range(1, 9)]


def test_revival_program_daily_sprint_is_creator_selectable_and_warns_about_backlog(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    recovery = _recovery_job()
    analysis = SimpleNamespace(
        result=SimpleNamespace(
            channel=SimpleNamespace(channel_id="channel_1", title="Pawshionista"),
            videos=[],
            metrics=SimpleNamespace(cadence=SimpleNamespace(active_days_per_30_days=4.0)),
        )
    )
    monkeypatch.setattr(svc.recovery_job_store, "get", lambda _job_id: recovery)
    monkeypatch.setattr(svc.job_store, "get", lambda _job_id: analysis)

    store.create_for_recovery("recovery_1")
    program = store.update_cadence("recovery_1", svc.RevivalCadenceIntensity.DAILY_SPRINT)

    assert program.cadence_per_week == 7
    assert program.cadence_intensity.value == "DAILY_SPRINT"
    assert program.suggested_days == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert len(program.weekly_slate) == 8
    assert program.backlog_weeks_supported < 2
    assert program.backlog_capacity_warning is not None
    assert "exhaust" in program.backlog_capacity_warning.lower()


def test_revival_program_uses_historical_weekdays_without_claiming_best_days(tmp_path, monkeypatch):
    store = _isolated_store(tmp_path, monkeypatch)
    recovery = _recovery_job()
    # 12 dated uploads with a strong Mon/Wed/Fri historical pattern.
    dates = [
        datetime(2026, 8, 3, tzinfo=timezone.utc),   # Mon
        datetime(2026, 8, 5, tzinfo=timezone.utc),   # Wed
        datetime(2026, 8, 7, tzinfo=timezone.utc),   # Fri
        datetime(2026, 8, 10, tzinfo=timezone.utc),
        datetime(2026, 8, 12, tzinfo=timezone.utc),
        datetime(2026, 8, 14, tzinfo=timezone.utc),
        datetime(2026, 8, 17, tzinfo=timezone.utc),
        datetime(2026, 8, 19, tzinfo=timezone.utc),
        datetime(2026, 8, 21, tzinfo=timezone.utc),
        datetime(2026, 8, 24, tzinfo=timezone.utc),
        datetime(2026, 8, 26, tzinfo=timezone.utc),
        datetime(2026, 8, 28, tzinfo=timezone.utc),
    ]
    analysis = SimpleNamespace(
        result=SimpleNamespace(
            channel=SimpleNamespace(channel_id="channel_1", title="Pawshionista"),
            videos=[SimpleNamespace(published_at=value) for value in dates],
            metrics=SimpleNamespace(cadence=SimpleNamespace(active_days_per_30_days=12.0)),
        )
    )
    monkeypatch.setattr(svc.recovery_job_store, "get", lambda _job_id: recovery)
    monkeypatch.setattr(svc.job_store, "get", lambda _job_id: analysis)

    program = store.create_for_recovery("recovery_1")
    program = store.update_cadence("recovery_1", svc.RevivalCadenceIntensity.BALANCED)

    assert program.schedule_basis == "historical_activity_with_spacing"
    assert len(program.suggested_days) == 3
    assert "best" not in program.schedule_rationale.lower()
    assert "historically active" in program.schedule_rationale.lower()
    assert sum(item.upload_count for item in program.weekday_activity) == len(dates)
