"""Regression tests use real services, mocked HTTP, and in-memory repositories.

No Google credentials, Firestore writes, uploads, or production jobs are used.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.models.youtube_publishing import YouTubeConnection, YouTubePerformanceSnapshot, YouTubePublication
from app.services import youtube_publishing_service as capture
from app.services.autonomous_publish_planner import AutonomousPublishPlanner
from app.services.autopilot_supervisor_service import AutopilotSupervisorService
from app.services.revival_learning_service import (
    BootstrapRequest, LearningWorkspace, PerformanceObservation, RevivalLearningStore, SeriesEntry,
)
from app.services.youtube_performance_service import (
    ANALYTICS_FIELDS, analytics_dates, decode_analytics, decode_statistics,
    release_anchor, resolve_release_time,
)

UTC = timezone.utc
NOW = datetime(2026, 10, 4, 8, tzinfo=UTC)


class MemoryRepository:
    def __init__(self):
        self.rows = {}
    def save(self, key, payload):
        self.rows[key] = payload
    def load(self, key):
        return self.rows.get(key)
    def stream(self):
        return iter(self.rows.items())


def analytics_payload(values=None):
    names = list(ANALYTICS_FIELDS)
    values = values if values is not None else [1000, 100, 20, 90, 4, 2, 0]
    return {"columnHeaders": [{"name": n} for n in names], "rows": [values]}


def video_payload(views="1153", **stats):
    return {"items": [{"id": "video-1", "snippet": {"channelId": "channel-1"},
                       "statistics": {"viewCount": views, "likeCount": "37", "commentCount": "0", **stats}}]}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "now", lambda: NOW)
    settings = SimpleNamespace(content_dna_checkpoint_dir=str(tmp_path), youtube_request_timeout_seconds=10,
                               autopilot_task_analytics_grace_seconds=60, autopilot_event_driven_enabled=True)
    service = capture.YouTubePublishingService(settings)
    service._snapshots = MemoryRepository()
    service._publications = MemoryRepository()
    pub = YouTubePublication(publication_id="pub-1", package_id="package-1", publishing_draft_id="draft-1",
                             recommendation_id="idea-1", program_id="program-1", youtube_video_id="video-1",
                             status="PUBLISHED", privacy_status="public", public_confirmed_at=NOW-timedelta(hours=25))
    pub.public_release_at = pub.public_confirmed_at
    pub.public_release_time_source = "YOUTUBE"
    pub.release_clock_version = 2
    monkeypatch.setattr(service, "get", lambda pid: pub)
    monkeypatch.setattr(service, "list", lambda: [pub])
    monkeypatch.setattr(service, "connection", lambda: YouTubeConnection(connected=True, channel_id="channel-1"))
    monkeypatch.setattr(service, "_authorization_reconnect_required", lambda: False)
    monkeypatch.setattr(service, "_wake_learning_supervisor", lambda pub, snap: None)
    async def access_token(*, return_marker=False):
        return ("test-token", "test-marker") if return_marker else "test-token"
    monkeypatch.setattr(service, "_access_token", access_token)
    learning = RevivalLearningStore(str(tmp_path))
    learning._cloud = MemoryRepository()
    learning.bootstrap(BootstrapRequest(recovery_job_id="recovery-1", program_id="program-1", channel_id="channel-1",
                                       ideas=[{"recommendation_id": "idea-1", "title": "Test series"}]))
    monkeypatch.setattr(capture, "revival_learning_store", learning)
    events, queued = [], []
    monkeypatch.setattr(capture, "autonomous_activity_store", SimpleNamespace(append=lambda **kw: events.append(kw)))
    monkeypatch.setattr(capture, "youtube_autonomy_queue", SimpleNamespace(sync=lambda **kw: queued.append(kw)))
    responses = {"statistics": (200, video_payload()), "analytics": (200, {"columnHeaders": [], "rows": []})}
    def handler(request):
        api = "analytics" if "youtubeanalytics" in str(request.url) else "statistics"
        status, body = responses[api]
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, json=body)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(capture.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    return SimpleNamespace(service=service, pub=pub, learning=learning, responses=responses, events=events, queued=queued)


def refresh(rig, checkpoint=None):
    return asyncio.run(rig.service.refresh_analytics("pub-1", checkpoint=checkpoint))


def test_empty_analytics_preserves_current_counters_and_pending_learning(rig):
    snap = refresh(rig)
    assert snap.views == 1153 and snap.likes == 37 and snap.comments == 0
    assert snap.statistics_ready and snap.analytics_status == "PENDING"
    assert snap.average_percentage_viewed is None and snap.shares is None
    assert snap.learning_synced and snap.next_retry_at > NOW
    workspace = rig.learning.get("program-1")
    assert not workspace.observations[0].decision_ready
    assert workspace.series_registry[0].decision == "OBSERVE"
    assert rig.events[-1]["action"] == "ANALYTICS_PENDING"
    assert rig.events[-1]["status"] != "SUCCESS"
    assert rig.queued[-1]["next_run_seconds"] == 3600


def test_retry_replaces_pending_snapshot_and_upserts_learning(rig, monkeypatch):
    first = refresh(rig)
    assert rig.service.due_checkpoint(rig.pub) is None
    monkeypatch.setattr(capture, "now", lambda: NOW+timedelta(hours=1))
    assert rig.service.due_checkpoint(rig.pub) == "24H"
    rig.responses["analytics"] = (200, analytics_payload())
    second = refresh(rig, "24H")
    assert second.learning_ready and second.next_retry_at is None
    assert second.observed_at == first.observed_at
    assert second.statistics_observed_at == NOW+timedelta(hours=1)
    assert len(rig.service.snapshots("pub-1")) == 1
    workspace = rig.learning.get("program-1")
    assert len(workspace.observations) == 1 and workspace.observations[0].decision_ready
    assert workspace.observations[0].analytics_views == 1000
    assert rig.events[-1]["status"] == "SUCCESS"


def test_actual_zero_row_is_valid_and_distinct_from_empty_response(rig):
    rig.responses["statistics"] = (200, video_payload("0", likeCount="0"))
    rig.responses["analytics"] = (200, analytics_payload([0]*7))
    snap = refresh(rig)
    assert snap.views == 0 and snap.average_percentage_viewed == 0
    assert snap.learning_ready and snap.analytics_status == "READY"
    assert rig.learning.get("program-1").series_registry[0].decision == "PAUSE"


@pytest.mark.parametrize("metric", ["likeCount", "commentCount"])
def test_missing_optional_public_counter_is_not_zero(metric):
    body = video_payload()
    del body["items"][0]["statistics"][metric]
    values, status = decode_statistics(body, "video-1", "channel-1")
    assert status == "READY"
    assert values["likes" if metric == "likeCount" else "comments"] is None


@pytest.mark.parametrize("body", [{"items": []}, {"items": [{"id": "wrong"}]}])
def test_missing_video_never_produces_zero(body):
    with pytest.raises(ValueError):
        decode_statistics(body, "video-1", "channel-1")


def test_wrong_channel_blocks_learning_even_when_analytics_returns_rows(rig):
    body = video_payload()
    body["items"][0]["snippet"]["channelId"] = "wrong-channel"
    rig.responses["statistics"] = (200, body)
    rig.responses["analytics"] = (200, analytics_payload())
    snap = refresh(rig)
    assert snap.views is None and snap.statistics_status == "ERROR"
    assert snap.analytics_status == "ERROR" and not snap.learning_ready


@pytest.mark.parametrize("api", ["statistics", "analytics"])
def test_http_failure_does_not_mask_other_api_or_generate_zero(rig, api):
    rig.responses["analytics"] = (200, analytics_payload())
    rig.responses[api] = (403, {"error": {"errors": [{"reason": "forbidden"}]}})
    snap = refresh(rig)
    if api == "analytics":
        assert snap.views == 1153 and snap.statistics_ready and snap.analytics_status == "ERROR"
        assert snap.average_percentage_viewed is None
    else:
        assert snap.views is None and not snap.statistics_ready
    assert snap.next_retry_at is not None


def test_network_error_is_recorded_without_secrets(rig):
    rig.responses["analytics"] = (200, httpx.ConnectError("private request token should not be logged"))
    snap = refresh(rig)
    assert snap.statistics_ready and snap.analytics_status == "ERROR"
    assert "private request token" not in snap.analytics_error


def test_headers_are_mapped_by_name_and_partial_row_is_pending():
    body = analytics_payload()
    body["columnHeaders"].reverse()
    body["rows"][0].reverse()
    values, status = decode_analytics(body)
    assert status == "READY" and values["average_percentage_viewed"] == 90
    body["rows"][0][0] = None
    values, status = decode_analytics(body)
    assert status == "PARTIAL" and values["subscribers_lost"] is None


@pytest.mark.parametrize("value", [None, "NaN", -1, True, "bad"])
def test_invalid_values_stay_unknown(value):
    values, status = decode_analytics(analytics_payload([value]*7))
    assert status == "PENDING" and all(x is None for x in values.values())


def test_pacific_date_boundary_and_daylight_saving():
    assert analytics_dates(datetime(2026,10,2,1,tzinfo=UTC), NOW) == ("2026-10-01", "2026-10-04")
    assert analytics_dates(datetime(2026,1,2,7,30,tzinfo=UTC), datetime(2026,1,2,8,tzinfo=UTC)) == ("2026-01-01", "2026-01-02")


def test_legacy_snapshot_is_quarantined_and_retried(rig):
    raw = {"checkpoint": "24H", "observed_at": (NOW-timedelta(hours=1)).isoformat(), "age_hours":24,
           "views":0, "likes":0, "comments":0, "average_percentage_viewed":0,
           "estimated_minutes_watched":0, "average_view_duration_seconds":0,
           "shares":0, "subscribers_gained":0, "subscribers_lost":0}
    rig.service._snapshots.save("pub-1:24H", {"publication_id":"pub-1", "snapshot":raw})
    snap = rig.service.latest_snapshot("pub-1")
    assert not snap.statistics_ready and snap.views is None
    assert rig.service.due_checkpoint(rig.pub) == "24H"
    repaired = refresh(rig, "24H")
    assert repaired.views == 1153 and repaired.statistics_is_late
    assert repaired.observed_at == datetime.fromisoformat(raw["observed_at"])


def test_legacy_learning_zeros_do_not_keep_pause_decision(rig):
    raw = rig.learning._cloud.load("program-1")
    raw["observations"] = [{"recommendation_id":"idea-1", "views":0, "average_percentage_viewed":0,
                            "average_view_duration_seconds":0, "likes":0, "comments":0,
                            "shares":0, "subscribers_gained":0, "subscribers_lost":0}]
    raw["series_registry"][0]["decision"] = "PAUSE"
    raw["next_wave_recommendation_ids"] = ["idea-1"]
    rig.learning._cloud.save("program-1", raw)
    workspace = rig.learning.get("program-1")
    assert not workspace.observations[0].decision_ready
    assert workspace.series_registry[0].decision == "OBSERVE"
    assert workspace.next_wave_recommendation_ids == []


def test_higher_checkpoint_wins_over_historical_repair(rig, monkeypatch):
    refresh(rig)
    monkeypatch.setattr(capture, "now", lambda: NOW+timedelta(hours=50))
    rig.responses["analytics"] = (200, analytics_payload())
    rig.responses["statistics"] = (200, video_payload("2000"))
    refresh(rig, "72H")
    rig.responses["statistics"] = (200, video_payload("2200"))
    refresh(rig, "24H")
    # The 72H historical snapshot remains available, but the configured
    # primary learning cohort (24H) is authoritative for decision-making.
    assert any(snap.checkpoint == "72H" and snap.views == 2000
               for snap in rig.service.snapshots("pub-1"))
    obs = rig.learning.get("program-1").observations[0]
    assert obs.checkpoint == "24H" and obs.views == 2200


def test_firestore_snapshot_takes_precedence_over_stale_local_mirror(rig):
    snap = refresh(rig)
    raw = snap.model_dump(mode="json")
    raw["views"] = 4000
    rig.service._snapshots.save("pub-1:24H", {"publication_id":"pub-1", "snapshot":raw})
    assert rig.service.latest_snapshot("pub-1").views == 4000


def test_learning_readiness_uses_verified_statistics(rig, monkeypatch):
    supervisor = AutopilotSupervisorService.__new__(AutopilotSupervisorService)
    import app.services.autopilot_supervisor_service as mod
    monkeypatch.setattr(mod, "youtube_publishing_service", rig.service)
    assert not supervisor._learning_checkpoint_ready(rig.pub, "24H")
    refresh(rig)
    assert supervisor._learning_checkpoint_ready(rig.pub, "24H")
    assert not supervisor._learning_checkpoint_ready(rig.pub, "72H")


def test_publish_planner_excludes_pending_and_legacy_metrics(rig):
    snap = refresh(rig)
    settings = SimpleNamespace(autopilot_publish_timezone="Asia/Manila", autopilot_publish_candidate_hours_local="12,18,20",
                               autopilot_publish_min_lead_minutes=30, autopilot_publish_min_spacing_hours=24, autopilot_publish_max_per_day=1,
                               autopilot_daily_publishing_enabled=False)
    planner = AutonomousPublishPlanner(settings)
    plan = planner.choose(publications=[rig.pub], latest_snapshots={"pub-1":snap}, now_utc=NOW)
    assert plan.evidence_count == 0
    rig.responses["analytics"] = (200, analytics_payload())
    snap = refresh(rig)
    plan = planner.choose(publications=[rig.pub], latest_snapshots={"pub-1":snap}, now_utc=NOW)
    assert plan.evidence_count == 1


def test_transient_failure_preserves_previously_verified_values(rig):
    rig.responses["analytics"] = (200, analytics_payload())
    first = refresh(rig)
    rig.responses["analytics"] = (503, {"error": {"errors":[{"reason":"backendError"}]}})
    snap = refresh(rig)
    assert snap.average_percentage_viewed == first.average_percentage_viewed
    assert snap.analytics_status == "READY" and snap.analytics_error
    assert snap.next_retry_at is not None


def test_empty_report_after_ready_preserves_last_verified_evidence(rig):
    rig.responses["analytics"] = (200, analytics_payload())
    refresh(rig)
    rig.responses["analytics"] = (200, {"rows":[]})
    snap = refresh(rig)
    assert snap.average_percentage_viewed == 90 and snap.analytics_status == "READY"
    assert snap.analytics_error and snap.next_retry_at is not None


def test_learning_write_failure_keeps_snapshot_retryable(rig, monkeypatch):
    rig.responses["analytics"] = (200, analytics_payload())
    def fail(*args, **kw):
        raise RuntimeError("simulated persistence outage")
    monkeypatch.setattr(rig.learning, "add_observation", fail)
    with pytest.raises(RuntimeError):
        refresh(rig)
    snap = rig.service.latest_snapshot("pub-1")
    assert not snap.learning_synced and snap.next_retry_at is not None
    assert rig.service._next_analytics_delay(rig.pub) == 3600


def test_legacy_older_than_35_days_gets_repair_window(rig):
    rig.pub.public_confirmed_at = NOW-timedelta(days=60)
    rig.pub.public_release_at = rig.pub.public_confirmed_at
    rig.service._snapshots.save("pub-1:28D", {"publication_id":"pub-1", "snapshot":{
        "checkpoint":"28D", "observed_at":(NOW-timedelta(days=32)).isoformat(), "views":0}})
    assert rig.service.due_checkpoint(rig.pub) == "28D"
    snap = refresh(rig, "28D")
    assert snap.retry_deadline_at == NOW+timedelta(days=7)


def test_completed_28d_stops_and_pending_28d_retries_with_backoff(rig):
    rig.pub.public_confirmed_at = NOW-timedelta(days=29)
    rig.pub.public_release_at = rig.pub.public_confirmed_at
    snap = refresh(rig)
    assert snap.checkpoint == "28D" and rig.service._next_analytics_delay(rig.pub) == 3600
    rig.responses["analytics"] = (200, analytics_payload())
    refresh(rig)
    assert rig.service._next_analytics_delay(rig.pub) is None


def test_worker_reconciles_pending_same_checkpoint(rig, monkeypatch):
    refresh(rig)
    monkeypatch.setattr(capture, "now", lambda: NOW+timedelta(hours=1))
    rig.responses["analytics"] = (200, analytics_payload())
    active, delay = asyncio.run(rig.service.autonomy_tick())
    assert active and delay > 3600
    assert rig.service.latest_snapshot("pub-1").learning_ready


@pytest.mark.parametrize("extra", [{}, {"performance_evidence_version": 2}])
def test_queue_upgrade_wakes_old_inactive_tenant_once(monkeypatch, extra):
    from app.services import youtube_autonomy_queue as module
    namespace = "a" * 32
    data = {"active":False, "next_run_at":NOW+timedelta(days=1), **extra}
    class Ref:
        def get(self):
            return SimpleNamespace(exists=True, to_dict=lambda:dict(data))
        def set(self, values, **kw):
            data.update(values)
    ref = Ref()
    publication = SimpleNamespace(reference=SimpleNamespace(parent=SimpleNamespace(parent=SimpleNamespace(id=namespace))))
    client = SimpleNamespace(collection_group=lambda name:SimpleNamespace(stream=lambda:iter([publication])))
    monkeypatch.setattr(module, "get_runtime_firestore_client", lambda:client)
    queue = module.YouTubeAutonomyQueue()
    monkeypatch.setattr(queue, "_collection", lambda:SimpleNamespace(document=lambda ns:ref))
    queue.bootstrap()
    assert data["active"] and data["performance_evidence_version"] == 2
    assert data["publication_clock_version"] == 2
    data.update(active=False, next_run_at=NOW+timedelta(days=1))
    queue.bootstrap()
    assert not data["active"] and data["next_run_at"] == NOW+timedelta(days=1)


def test_pending_retry_deadline_eventually_stops_background_polling(rig, monkeypatch):
    snap = refresh(rig)
    monkeypatch.setattr(capture, "now", lambda:snap.retry_deadline_at+timedelta(days=1))
    # Once the final due checkpoint has been captured, its expired retry window
    # cannot keep scheduling background tasks indefinitely.
    snap.checkpoint = "28D"
    rig.service._snapshots.rows.clear()
    rig.service._save_snapshot("pub-1", snap)
    assert rig.service._next_analytics_delay(rig.pub) is None


def test_missing_workspace_learning_sync_is_retryable(rig, monkeypatch):
    rig.responses["analytics"] = (200, analytics_payload())
    def missing(*args, **kw):
        raise KeyError("program-1")
    monkeypatch.setattr(rig.learning, "add_observation", missing)
    snap = refresh(rig)
    assert snap.learning_ready and not snap.learning_synced
    assert rig.service._next_analytics_delay(rig.pub) == 3600


def test_first_manual_capture_of_older_checkpoint_does_not_repeat_forever(rig, monkeypatch):
    monkeypatch.setattr(capture, "now", lambda:NOW+timedelta(hours=50))
    rig.responses["analytics"] = (200, analytics_payload())
    refresh(rig, "72H")
    old = refresh(rig, "24H")
    assert old.learning_synced and old.next_retry_at is None
    assert rig.service.latest_snapshot("pub-1").checkpoint == "72H"


def test_mature_first_capture_gets_bounded_reconciliation_window(rig):
    rig.pub.public_confirmed_at = NOW-timedelta(days=60)
    rig.pub.public_release_at = rig.pub.public_confirmed_at
    snap = refresh(rig)
    assert snap.checkpoint == "28D"
    assert snap.retry_deadline_at == NOW+timedelta(days=7)
    assert rig.service._next_analytics_delay(rig.pub) == 3600


def old_release(rig, reported_at="2026-10-03T04:00:00Z", privacy="public"):
    # Exact persisted timing discrepancy from the deployment response.
    rig.pub.publish_at = datetime(2026, 10, 3, 4, tzinfo=UTC)
    rig.pub.public_confirmed_at = datetime(2026, 10, 4, 6, 40, 11, 931558, tzinfo=UTC)
    rig.pub.published_at = rig.pub.public_confirmed_at
    rig.pub.public_release_at = None
    rig.pub.public_release_time_source = None
    rig.pub.release_clock_version = 1
    body = video_payload("10")
    body["items"][0]["status"] = {"privacyStatus": privacy, "uploadStatus": "processed"}
    body["items"][0]["snippet"]["publishedAt"] = reported_at
    rig.responses["statistics"] = (200, body)
    rig.service._save_snapshot("pub-1", YouTubePerformanceSnapshot(
        checkpoint="1H", observed_at=datetime(2026, 10, 4, 7, 45, tzinfo=UTC), age_hours=1.1,
        views=10, evidence_version=2, statistics_status="READY", analytics_status="PENDING",
        learning_synced=True, next_retry_at=NOW+timedelta(hours=2),
    ))
    return rig.pub.public_confirmed_at


def test_manual_refresh_repairs_deployed_clock_and_collects_due_24h(rig):
    confirmation = old_release(rig)
    snap = refresh(rig)
    assert rig.pub.public_confirmed_at == confirmation
    assert rig.pub.public_release_at == rig.pub.publish_at
    assert rig.pub.published_at == rig.pub.publish_at
    assert rig.pub.public_release_time_source == "YOUTUBE" and rig.pub.release_clock_version == 2
    assert snap.checkpoint == "24H" and snap.age_hours == 28
    assert snap.public_release_at == rig.pub.publish_at and snap.statistics_ready
    assert snap.analytics_status == "PENDING" and snap.average_percentage_viewed is None
    assert snap.analytics_start_date == "2026-10-02"  # Pacific calendar, not the late verification date.
    assert snap.statistics_is_late
    assert rig.events[0]["action"] == "RELEASE_CLOCK_REPAIRED"
    assert len(rig.service.snapshots("pub-1")) == 2
    assert rig.service._publications.load("pub-1")["release_clock_version"] == 2


def test_worker_migrates_already_published_row_before_selecting_checkpoint(rig):
    confirmation = old_release(rig)
    active, delay = asyncio.run(rig.service.autonomy_tick())
    assert active and delay == 3600
    assert rig.service.latest_snapshot("pub-1").checkpoint == "24H"
    assert rig.pub.public_confirmed_at == confirmation
    assert rig.pub.public_release_at == rig.pub.publish_at


def test_reported_actual_release_takes_precedence_over_planned_schedule(rig):
    old_release(rig, reported_at="2026-10-04T06:30:00Z")
    snap = refresh(rig)
    assert rig.pub.public_release_at == datetime(2026, 10, 4, 6, 30, tzinfo=UTC)
    assert snap.checkpoint == "1H" and rig.service.due_checkpoint(rig.pub) is None


@pytest.mark.parametrize("reported_at", [None, "invalid", "2026-10-05T04:00:00Z", "2026-10-03T04:00:00"])
def test_missing_invalid_or_future_release_metadata_uses_labelled_schedule_estimate(rig, reported_at):
    old_release(rig, reported_at=reported_at)
    snap = refresh(rig)
    assert rig.pub.public_release_at == rig.pub.publish_at
    assert rig.pub.public_release_time_source == "SCHEDULE_ESTIMATE"
    assert snap.checkpoint == "24H"


def test_unscheduled_release_without_metadata_uses_original_verification(rig):
    confirmation = old_release(rig, reported_at=None)
    rig.pub.publish_at = None
    pub = asyncio.run(rig.service.reconcile_remote_status("pub-1"))
    assert pub.public_release_at == confirmation and pub.public_release_time_source == "CONFIRMATION"


def test_previously_verified_youtube_release_is_kept_if_metadata_disappears(rig):
    rig.pub.publish_at = NOW-timedelta(hours=50)
    anchor, source = resolve_release_time(rig.pub, {}, NOW)
    assert anchor == rig.pub.public_release_at and source == "YOUTUBE"


@pytest.mark.parametrize("failure", ["private", "wrong_channel", "wrong_video", "provider_error"])
def test_clock_repair_does_not_trust_private_or_unrelated_video(rig, failure):
    confirmation = old_release(rig)
    body = rig.responses["statistics"][1]
    if failure == "private":
        body["items"][0]["status"]["privacyStatus"] = "private"
    elif failure == "wrong_channel":
        body["items"][0]["snippet"]["channelId"] = "another-channel"
    elif failure == "wrong_video":
        body["items"][0]["id"] = "another-video"
    else:
        rig.responses["statistics"] = (503, {"error":{}})
    with pytest.raises(capture.YouTubePublishingError):
        refresh(rig)
    assert rig.pub.public_confirmed_at == confirmation and rig.pub.public_release_at is None
    assert rig.service.latest_snapshot("pub-1").checkpoint == "1H"


def test_clock_migration_is_idempotent_and_keeps_original_capture_time(rig):
    old_release(rig)
    first = refresh(rig)
    refreshed = refresh(rig)
    assert refreshed.observed_at == first.observed_at
    assert sum(event["action"] == "RELEASE_CLOCK_REPAIRED" for event in rig.events) == 1
    assert len(rig.service.snapshots("pub-1")) == 2


def test_repaired_clock_does_not_retain_ready_analytics_from_a_different_window(rig):
    old_release(rig)
    snap = rig.service.snapshots("pub-1")[0]
    snap.analytics_status = "READY"
    snap.average_percentage_viewed = 55.4
    snap.analytics_start_date = "2026-10-03"
    snap.analytics_end_date = "2026-10-04"
    rig.service._save_snapshot("pub-1", snap)
    repaired = refresh(rig, "1H")
    assert repaired.analytics_start_date == "2026-10-02"
    assert repaired.analytics_status == "PENDING" and repaired.average_percentage_viewed is None
    assert repaired.age_hours == 27.8 and repaired.observed_at == snap.observed_at


def test_supervisor_uses_release_clock_for_readiness_and_maximum_wait(rig, monkeypatch):
    old_release(rig)
    refresh(rig)
    supervisor = AutopilotSupervisorService.__new__(AutopilotSupervisorService)
    supervisor.settings = SimpleNamespace(autopilot_next_production_max_wait_hours=24)
    import app.services.autopilot_supervisor_service as module
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(module, "datetime", FrozenDatetime)
    monkeypatch.setattr(module, "youtube_publishing_service", rig.service)
    assert supervisor._learning_checkpoint_ready(rig.pub, "24H")
    assert supervisor._learning_wait_timed_out(SimpleNamespace(session=SimpleNamespace(learningWaitStartedAt=None)), rig.pub)


def test_supervisor_does_not_accept_checkpoint_captured_before_elapsed_requirement(rig, monkeypatch):
    rig.service._save_snapshot("pub-1", YouTubePerformanceSnapshot(
        checkpoint="24H", observed_at=rig.pub.public_release_at+timedelta(hours=1),
        evidence_version=2, statistics_status="READY", views=10,
    ))
    supervisor = AutopilotSupervisorService.__new__(AutopilotSupervisorService)
    import app.services.autopilot_supervisor_service as module
    monkeypatch.setattr(module, "youtube_publishing_service", rig.service)
    assert not supervisor._learning_checkpoint_ready(rig.pub, "24H")


@pytest.mark.parametrize("internal", [False, True])
def test_verified_statistics_wake_matching_supervisor_even_inside_youtube_task(rig, monkeypatch, internal):
    from app.core.task_execution import in_internal_task, internal_task_context
    from app.services import autopilot_state_service as state_module
    from app.services import autopilot_supervisor_queue as queue_module
    old_release(rig)
    snap = refresh(rig)
    calls = []
    session = SimpleNamespace(status="WAITING_FOR_LEARNING", executionOwner="BACKEND", currentPublicationId="pub-1",
                              currentRecommendationId="idea-1", learningCheckpointRequired="24H")
    monkeypatch.setattr(state_module.autopilot_state_store, "get", lambda:SimpleNamespace(revision=7, session=session))
    monkeypatch.setattr(queue_module.autopilot_supervisor_queue, "sync", lambda **kw:calls.append(("sync", in_internal_task(), kw)))
    monkeypatch.setattr(queue_module.autopilot_supervisor_queue, "defer", lambda *args, **kw:calls.append(("defer", args, kw)))
    def wake():
        capture.YouTubePublishingService._wake_learning_supervisor(rig.service, rig.pub, snap)
    if internal:
        with internal_task_context():
            wake()
    else:
        wake()
    assert calls[0][0] == "sync" and calls[0][1] is True
    assert calls[1][0] == "defer" and calls[1][1][1] == 30
    assert calls[1][2]["reason"] == "verified-learning-checkpoint"
    assert not in_internal_task()


@pytest.mark.parametrize("mismatch", ["other_publication", "paused", "frontend_owner", "early_checkpoint", "unknown_statistics"])
def test_supervisor_wake_respects_session_and_required_evidence(rig, monkeypatch, mismatch):
    from app.services import autopilot_state_service as state_module
    from app.services import autopilot_supervisor_queue as queue_module
    snap = refresh(rig)
    session = SimpleNamespace(status="WAITING_FOR_LEARNING", executionOwner="BACKEND", currentPublicationId="pub-1",
                              currentRecommendationId="idea-1", learningCheckpointRequired="24H")
    if mismatch == "other_publication":
        session.currentPublicationId = "other-publication"
    elif mismatch == "paused":
        session.status = "PAUSED"
    elif mismatch == "frontend_owner":
        session.executionOwner = "FRONTEND"
    elif mismatch == "early_checkpoint":
        snap.checkpoint = "EARLY"
    else:
        snap.statistics_status = "PENDING"
    monkeypatch.setattr(state_module.autopilot_state_store, "get", lambda:SimpleNamespace(revision=7, session=session))
    calls = []
    monkeypatch.setattr(queue_module.autopilot_supervisor_queue, "sync", lambda **kw:calls.append(kw))
    monkeypatch.setattr(queue_module.autopilot_supervisor_queue, "defer", lambda *args, **kw:calls.append(kw))
    capture.YouTubePublishingService._wake_learning_supervisor(rig.service, rig.pub, snap)
    assert calls == []


def test_repair_cli_verifies_old_clock_and_also_captures_mature_checkpoint(rig, monkeypatch, capsys):
    from app.tools import reconcile_youtube_performance as tool
    old_release(rig)
    monkeypatch.setattr(tool, "youtube_publishing_service", rig.service)
    args = SimpleNamespace(tenant_id="test-only-uid", tenant_namespace=None, publication_id="pub-1", apply=True)
    assert asyncio.run(tool.reconcile(args)) == 0
    assert rig.service.latest_snapshot("pub-1").checkpoint == "24H"
    assert "release-clock verification: 1" in capsys.readouterr().out


def test_planner_spacing_uses_actual_release_instead_of_old_schedule_or_confirmation(rig):
    rig.pub.public_release_at = NOW-timedelta(hours=1)
    rig.pub.publish_at = NOW-timedelta(hours=49)
    rig.pub.public_confirmed_at = NOW
    settings = SimpleNamespace(autopilot_publish_timezone="Asia/Manila", autopilot_publish_candidate_hours_local="12,18,20",
                               autopilot_publish_min_lead_minutes=30, autopilot_publish_min_spacing_hours=24, autopilot_publish_max_per_day=1,
                               autopilot_daily_publishing_enabled=False)
    plan = AutonomousPublishPlanner(settings).choose(publications=[rig.pub],latest_snapshots={},now_utc=NOW)
    assert plan.publish_at >= rig.pub.public_release_at+timedelta(hours=24)
    assert plan.publish_at == datetime(2026, 10, 5, 10, tzinfo=UTC)


def test_supervisor_next_wake_uses_corrected_release_even_before_checkpoint_capture(rig, monkeypatch):
    old_release(rig)
    asyncio.run(rig.service.reconcile_remote_status("pub-1"))
    supervisor = AutopilotSupervisorService.__new__(AutopilotSupervisorService)
    supervisor.settings = SimpleNamespace(autopilot_task_active_interval_seconds=30,autopilot_task_public_probe_grace_seconds=60,
        autopilot_continuous_learning_checkpoint="24H",autopilot_continuous_learning_max_wait_hours=48,autopilot_task_analytics_grace_seconds=60,
        autopilot_next_production_checkpoint="24H",autopilot_next_production_max_wait_hours=48)
    import app.services.autopilot_supervisor_service as module
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW
    monkeypatch.setattr(module, "datetime", FrozenDatetime)
    monkeypatch.setattr(module, "youtube_publishing_service", rig.service)
    session = SimpleNamespace(status="WAITING_FOR_LEARNING",currentPublicationId="pub-1",currentRecommendationId="idea-1",learningCheckpointRequired="24H")
    assert supervisor.next_wake_delay(SimpleNamespace(session=session)) == 120
