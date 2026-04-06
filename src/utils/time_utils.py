"""UTC time helpers and session window checks."""

from __future__ import annotations

from datetime import datetime, time, timezone

import pandas as pd


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def parse_time_str(t: str) -> time:
    """Parse 'HH:MM' string to time object."""
    parts = t.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def is_within_window(now: datetime, start_str: str, end_str: str) -> bool:
    """Check if *now* is within [start, end) UTC window (same day)."""
    t = now.time().replace(tzinfo=None)
    start = parse_time_str(start_str)
    end = parse_time_str(end_str)
    if start < end:
        return start <= t < end
    # Wraps midnight
    return t >= start or t < end


def is_time_reached(now: datetime, time_str: str) -> bool:
    """Check if current HH:MM matches time_str exactly."""
    t = now.time()
    target = parse_time_str(time_str)
    return t.hour == target.hour and t.minute == target.minute


def ts_to_utc(ts: int | float) -> pd.Timestamp:
    """Convert Unix milliseconds to pandas UTC Timestamp."""
    return pd.Timestamp(ts, unit="ms", tz="UTC")


def date_to_unix_ms(date_str: str) -> int:
    """Convert 'YYYY-MM-DD' to Unix milliseconds."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def day_of_week_name(dt: datetime) -> str:
    """Return lowercase day name: 'monday', 'tuesday', ..."""
    return dt.strftime("%A").lower()


def is_trading_day_allowed(now: datetime, filters: dict) -> bool:
    """Check if today is an allowed trading day per config filters."""
    day_name = day_of_week_name(now)
    return filters.get(f"trade_{day_name}", True)


def is_same_utc_day(a: datetime, b: datetime) -> bool:
    """Check if two datetimes fall on the same UTC date."""
    return a.date() == b.date()
