"""Time helpers for rule enforcement."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def day_start_for(now: datetime, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(tz)
    midnight = datetime.combine(local.date(), time.min, tzinfo=tz)
    return midnight


def needs_day_reset(now: datetime, day_start_time: datetime, timezone: str) -> bool:
    return day_start_for(now, timezone) > day_start_time.astimezone(ZoneInfo(timezone))


def trading_day_for(timestamp: datetime, timezone: str) -> date:
    tz = ZoneInfo(timezone)
    if timestamp.tzinfo is None:
        return timestamp.date()
    return timestamp.astimezone(tz).date()


def next_midnight(now: datetime, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(tz)
    next_day = local.date() + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=tz)


def minutes_until_midnight(now: datetime, timezone: str) -> int:
    midnight = next_midnight(now, timezone)
    delta = midnight - now.astimezone(ZoneInfo(timezone))
    return max(0, int(delta.total_seconds() // 60))


def in_midnight_window(now: datetime, timezone: str, window_minutes: int) -> bool:
    if window_minutes <= 0:
        return False
    return minutes_until_midnight(now, timezone) <= window_minutes
