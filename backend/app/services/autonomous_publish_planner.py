from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import log1p
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import Settings
from app.models.youtube_publishing import YouTubePublication, YouTubePerformanceSnapshot, YouTubePublishStatus
from app.services.youtube_performance_service import release_anchor


@dataclass(frozen=True)
class PublishPlan:
    publish_at: datetime
    reason: str
    evidence_count: int


def _parse_hours(raw: str) -> list[int]:
    out: list[int] = []
    for token in str(raw or "").split(","):
        try:
            hour = int(token.strip())
        except ValueError:
            continue
        if 0 <= hour <= 23 and hour not in out:
            out.append(hour)
    return out or [12, 18, 20]


def _resolve_publish_timezone(name: str):
    """Resolve configured IANA timezone with a safe Philippines fallback.

    Windows Python installations do not ship the IANA timezone database by
    default. The `tzdata` package is still recommended and should be pinned in
    requirements.txt, but ReviveAI must not halt autonomous publishing solely
    because the runtime cannot resolve Asia/Manila. The Philippines is UTC+08:00
    year-round, so that one configured timezone has a deterministic fixed-offset
    fallback. Other timezone names remain fail-closed.
    """
    zone_name = str(name or "Asia/Manila").strip() or "Asia/Manila"
    try:
        return ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        if zone_name == "Asia/Manila":
            return timezone(timedelta(hours=8), name="PHT")
        raise RuntimeError(
            f"Timezone data is unavailable for {zone_name!r}. Install the Python 'tzdata' package or use a runtime with the IANA timezone database installed."
        ) from exc


def _snapshot_score(s: YouTubePerformanceSnapshot) -> float:
    if not s.learning_ready:
        return 0.0
    views = max(1, int(s.views or 0))
    analytics_views = max(1, int(s.analytics_views if s.analytics_views is not None else views))
    # Public engagement and processed analytics can cover different windows.
    engagement_rate = (int(s.likes or 0) + int(s.comments or 0)) / views + int(s.shares or 0) / analytics_views
    subscriber_rate = max(0, int(s.subscribers_gained or 0) - int(s.subscribers_lost or 0)) / analytics_views
    retention = max(0.0, min(1.0, float(s.average_percentage_viewed or 0) / 100.0))
    reach = min(1.0, log1p(views) / 10.0)
    return (
        retention * 0.40
        + min(1.0, engagement_rate * 20.0) * 0.25
        + min(1.0, subscriber_rate * 100.0) * 0.25
        + reach * 0.10
    )


class AutonomousPublishPlanner:
    """Select a future YouTube public time using ReviveAI's own observed evidence.

    This is intentionally a conservative optimizer, not a claim that any hour will
    increase views or subscribers. It learns from already-published ReviveAI videos
    when enough observations exist and otherwise falls back to configured creator
    windows. The upload itself happens immediately; only public release is scheduled.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def choose(
        self,
        *,
        publications: list[YouTubePublication],
        latest_snapshots: dict[str, YouTubePerformanceSnapshot | None],
        now_utc: datetime | None = None,
        channel_id: str | None = None,
    ) -> PublishPlan:
        now_utc = now_utc or datetime.now(timezone.utc)
        tz = _resolve_publish_timezone(self.settings.autopilot_publish_timezone)
        now_local = now_utc.astimezone(tz)
        daily_mode = bool(getattr(self.settings, "autopilot_daily_publishing_enabled", True))
        candidate_hours = (
            [int(getattr(self.settings, "autopilot_daily_publish_hour_local", 12))]
            if daily_mode
            else _parse_hours(self.settings.autopilot_publish_candidate_hours_local)
        )
        min_time = now_local + timedelta(minutes=int(self.settings.autopilot_publish_min_lead_minutes))

        # Learn which configured hour has produced stronger retention/engagement/
        # subscriber conversion. Nearest configured hour is used so sparse historical
        # data can still inform the planner without inventing minute-level precision.
        bucket_scores: dict[int, list[float]] = {h: [] for h in candidate_hours}
        evidence_count = 0
        for pub in publications:
            anchor = release_anchor(pub) or pub.published_at or pub.publish_at
            snap = latest_snapshots.get(pub.publication_id)
            if not anchor or not snap or not snap.learning_ready or (snap.views or 0) <= 0:
                continue
            local_hour = anchor.astimezone(tz).hour
            nearest = min(candidate_hours, key=lambda h: min((h - local_hour) % 24, (local_hour - h) % 24))
            bucket_scores[nearest].append(_snapshot_score(snap))
            evidence_count += 1

        ranked_hours = list(candidate_hours)
        if evidence_count >= 3 and not daily_mode:
            ranked_hours.sort(
                key=lambda h: (sum(bucket_scores[h]) / len(bucket_scores[h])) if bucket_scores[h] else -1.0,
                reverse=True,
            )

        # Only active public/scheduled publications reserve release slots.
        # A failed or superseded upload must not postpone subsequent videos.
        reservations: list[tuple[datetime, YouTubePublication]] = []
        for pub in publications:
            if pub.status not in {YouTubePublishStatus.PUBLISHED, YouTubePublishStatus.SCHEDULED}:
                continue
            if pub.superseded_by_publication_id:
                continue
            anchor = (
                (release_anchor(pub) or pub.public_release_at or pub.published_at or pub.publish_at)
                if pub.status == YouTubePublishStatus.PUBLISHED
                else (pub.publish_at or pub.public_confirmed_at or pub.published_at)
            )
            if anchor is None:
                continue
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=timezone.utc)
            reservations.append((anchor.astimezone(tz), pub))

        spacing_hours = max(1, int(self.settings.autopilot_publish_min_spacing_hours))
        if channel_id:
            from app.services.channel_autonomy_policy import channel_policy_store
            spacing_hours = max(spacing_hours, channel_policy_store.get(channel_id).publish_interval_hours)
        if daily_mode:
            spacing_hours = max(24, spacing_hours)
        spacing = timedelta(hours=spacing_hours)
        max_per_day = 1 if daily_mode else int(self.settings.autopilot_publish_max_per_day)

        # Rather than shifting once after the latest anchor (which unnecessarily
        # skips valid earlier slots), evaluate each configured slot against every
        # reserved publication. Include the conflict in the persisted explanation.
        conflicts: list[str] = []
        for day_offset in range(0, 15):
            day = (min_time + timedelta(days=day_offset)).date()
            same_day = [(anchor, pub) for anchor, pub in reservations if anchor.date() == day]
            if len(same_day) >= max_per_day:
                blocker = min(same_day, key=lambda pair: pair[0])
                conflicts.append(
                    f"{day.isoformat()} has {len(same_day)} reserved release(s), including "
                    f"{blocker[1].publication_id} at {blocker[0].strftime('%I:%M %p')}"
                )
                continue
            for hour in ranked_hours:
                candidate = datetime(day.year, day.month, day.day, hour, 0, tzinfo=tz)
                if candidate < min_time:
                    continue
                blocking = [
                    (anchor, pub) for anchor, pub in reservations
                    if abs(candidate.astimezone(timezone.utc) - anchor.astimezone(timezone.utc)) < spacing
                ]
                if blocking:
                    anchor, pub = min(blocking, key=lambda pair: abs(candidate - pair[0]))
                    conflicts.append(
                        f"{candidate.strftime('%Y-%m-%d %I:%M %p')} conflicts with "
                        f"{pub.publication_id} ({pub.status.value}) at "
                        f"{anchor.strftime('%Y-%m-%d %I:%M %p')} under {spacing_hours}h minimum spacing"
                    )
                    continue
                if evidence_count >= 3 and not daily_mode and bucket_scores.get(hour):
                    mean = sum(bucket_scores[hour]) / len(bucket_scores[hour])
                    reason = (
                        f"Scheduled for {candidate.strftime('%A %I:%M %p')} {self.settings.autopilot_publish_timezone} "
                        f"using {evidence_count} ReviveAI performance observation(s); strongest measured "
                        f"retention, engagement and subscriber score ({mean:.3f})."
                    )
                else:
                    reason = (
                        f"Scheduled for {candidate.strftime('%A %I:%M %p')} {self.settings.autopilot_publish_timezone} "
                        f"using the configured {'daily control slot' if daily_mode else 'fallback publishing window'}."
                    )
                if conflicts:
                    # The reason is persisted with the publication and its final-approval event.
                    reason += " Earlier slots unavailable: " + "; ".join(conflicts[-5:]) + "."
                else:
                    reason += " This was the earliest eligible release slot."
                return PublishPlan(candidate.astimezone(timezone.utc), reason, evidence_count)

        raise RuntimeError(
            "No safe YouTube publishing slot found within the next 15 days; "
            "review existing reservations and the configured spacing policy."
        )
