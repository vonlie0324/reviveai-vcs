"""Strict API response decoding shared by capture and regression tests.

No missing value is coerced to zero. Analytics dates use YouTube's Pacific
calendar; returned daily aggregates are not exact elapsed-hour measurements.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from app.models.youtube_publishing import YouTubePublication


def release_anchor(publication: YouTubePublication) -> datetime | None:
    value = publication.public_release_at or publication.public_confirmed_at
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def resolve_release_time(publication: YouTubePublication, snippet: dict, observed_at: datetime) -> tuple[datetime, str]:
    """Called only after the requested video's channel and public status match.

    YouTube's publishedAt takes precedence over the planned schedule. Missing or
    invalid provider metadata falls back to an explicitly labelled approximation.
    """
    try:
        reported = datetime.fromisoformat(str(snippet.get("publishedAt") or "").replace("Z", "+00:00"))
        if reported.tzinfo is not None and reported <= observed_at:
            return reported.astimezone(timezone.utc), "YOUTUBE"
    except (TypeError, ValueError, OverflowError):
        pass
    if publication.public_release_at and publication.public_release_time_source == "YOUTUBE":
        return release_anchor(publication), "YOUTUBE"
    confirmed = publication.public_confirmed_at or observed_at
    if confirmed.tzinfo is None:
        confirmed = confirmed.replace(tzinfo=timezone.utc)
    scheduled = publication.publish_at
    if scheduled is not None:
        scheduled = scheduled.replace(tzinfo=timezone.utc) if scheduled.tzinfo is None else scheduled
        if scheduled <= confirmed and scheduled <= observed_at:
            return scheduled.astimezone(timezone.utc), "SCHEDULE_ESTIMATE"
    return confirmed.astimezone(timezone.utc), "CONFIRMATION"

ANALYTICS_FIELDS = {
    "views": ("analytics_views", int),
    "estimatedMinutesWatched": ("estimated_minutes_watched", float),
    "averageViewDuration": ("average_view_duration_seconds", float),
    "averageViewPercentage": ("average_percentage_viewed", float),
    "shares": ("shares", int),
    "subscribersGained": ("subscribers_gained", int),
    "subscribersLost": ("subscribers_lost", int),
}


def _number(value, cast):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        if not isfinite(number) or number < 0:
            return None
        if cast is int and not number.is_integer():
            return None
        return cast(value)
    except (TypeError, ValueError, OverflowError):
        return None


def analytics_dates(anchor: datetime, captured_at: datetime) -> tuple[str, str]:
    pacific = ZoneInfo("America/Los_Angeles")
    return anchor.astimezone(pacific).date().isoformat(), captured_at.astimezone(pacific).date().isoformat()


def decode_statistics(payload: dict, video_id: str, channel_id: str | None):
    items = payload.get("items") or []
    video = next((x for x in items if isinstance(x, dict) and x.get("id") == video_id), None)
    if video is None:
        raise ValueError("YouTube Data API did not return the requested video.")
    owner = (video.get("snippet") or {}).get("channelId")
    if not channel_id or owner != channel_id:
        raise ValueError("Video channel does not match the connected YouTube channel.")
    stats = video.get("statistics") or {}
    values = {name: _number(stats.get(key), int) for name, key in (
        ("views", "viewCount"), ("likes", "likeCount"), ("comments", "commentCount"))}
    # Hidden/disabled likes or comments may be absent. A valid viewCount is
    # sufficient for cadence readiness; the omitted counters remain unknown.
    return values, "READY" if values["views"] is not None else "PENDING"


def decode_analytics(payload: dict):
    empty = {field: None for field, _cast in ANALYTICS_FIELDS.values()}
    rows = payload.get("rows") or []
    if not rows:
        return empty, "PENDING"
    if len(rows) != 1 or not isinstance(rows[0], list):
        raise ValueError("Expected one aggregate YouTube Analytics row.")
    headers = payload.get("columnHeaders") or []
    names = [x.get("name") if isinstance(x, dict) else None for x in headers]
    if len(names) != len(rows[0]) or len(set(names)) != len(names):
        raise ValueError("YouTube Analytics headers do not match the returned row.")
    by_name = dict(zip(names, rows[0]))
    values = {field: _number(by_name.get(name), cast) for name, (field, cast) in ANALYTICS_FIELDS.items()}
    if not any(x is not None for x in values.values()):
        return values, "PENDING"
    return values, "READY" if all(x is not None for x in values.values()) else "PARTIAL"

CHECKPOINT_HOURS = {"EARLY": 0, "1H": 1, "6H": 6, "24H": 24, "72H": 72, "7D": 168, "28D": 672}


def select_primary_learning_snapshot(snapshots, primary_checkpoint: str = "24H"):
    """Return the best apples-to-apples snapshot for autonomous decisions.

    Prefer a fully learning-ready snapshot at the configured primary checkpoint.
    Before it exists, fall back to the most mature learning-ready snapshot not newer
    than the primary checkpoint. Later 72H/7D/28D checkpoints are retained for
    longitudinal reporting but do not silently replace the primary decision cohort.
    """
    if not snapshots:
        return None
    primary = str(primary_checkpoint or "24H").upper()
    primary_hours = CHECKPOINT_HOURS.get(primary, 24)
    ordered = sorted(
        snapshots,
        key=lambda item: (CHECKPOINT_HOURS.get(str(item.checkpoint).upper(), -1), item.observed_at),
    )
    exact_ready = [
        item for item in ordered
        if str(item.checkpoint).upper() == primary and item.learning_ready
    ]
    if exact_ready:
        return exact_ready[-1]
    eligible_ready = [
        item for item in ordered
        if CHECKPOINT_HOURS.get(str(item.checkpoint).upper(), -1) <= primary_hours and item.learning_ready
    ]
    if eligible_ready:
        return eligible_ready[-1]
    exact = [item for item in ordered if str(item.checkpoint).upper() == primary]
    if exact:
        return exact[-1]
    eligible = [
        item for item in ordered
        if CHECKPOINT_HOURS.get(str(item.checkpoint).upper(), -1) <= primary_hours
    ]
    return eligible[-1] if eligible else ordered[-1]


def performance_signal(snapshot) -> dict | None:
    """Build a comparable signal from metrics ReviveAI already captures.

    CTR/impressions are intentionally excluded because the current capture contract
    does not collect them reliably for every publication type. This score therefore
    uses view velocity, retention, engagement, and net-subscriber conversion only.
    """
    if snapshot is None or not snapshot.statistics_ready or snapshot.views is None:
        return None
    views = max(1, int(snapshot.views or 0))
    analytics_views = max(1, int(snapshot.analytics_views if snapshot.analytics_views is not None else views))
    retention = None if snapshot.average_percentage_viewed is None else max(0.0, min(150.0, float(snapshot.average_percentage_viewed)))
    engagement = None
    if snapshot.likes is not None or snapshot.comments is not None or snapshot.shares is not None:
        engagement = ((snapshot.likes or 0) + (snapshot.comments or 0) + (snapshot.shares or 0)) / views * 100.0
    net_subs = None
    sub_conversion = None
    if snapshot.subscribers_gained is not None and snapshot.subscribers_lost is not None:
        net_subs = int(snapshot.subscribers_gained) - int(snapshot.subscribers_lost)
        sub_conversion = net_subs / analytics_views * 1000.0
    return {
        "checkpoint": snapshot.checkpoint,
        "views": int(snapshot.views),
        "retention_percent": retention,
        "engagement_percent": engagement,
        "net_subscribers": net_subs,
        "net_subscribers_per_1k_views": sub_conversion,
        "statistics_ready": snapshot.statistics_ready,
        "learning_ready": snapshot.learning_ready,
    }
