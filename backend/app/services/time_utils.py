from __future__ import annotations

from datetime import datetime, timezone


def utc_calendar_day_gap(earlier: datetime, later: datetime) -> int:
    """Return non-negative calendar-day distance after normalizing both datetimes to UTC.

    ReviveAI uses calendar days for user-facing inactivity, rather than elapsed
    24-hour blocks, so every surface reports the same value around day boundaries.
    """
    earlier_utc = earlier.astimezone(timezone.utc)
    later_utc = later.astimezone(timezone.utc)
    return max(0, (later_utc.date() - earlier_utc.date()).days)
