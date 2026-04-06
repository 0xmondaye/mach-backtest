"""FOMC / CPI / NFP blackout calendar."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class NewsEvent:
    """A scheduled macro event."""

    time_utc: datetime
    name: str
    high_impact: bool


# ---------------------------------------------------------------------------
# Hardcoded FOMC dates (announcement at 19:00 UTC)
# ---------------------------------------------------------------------------
FOMC_DATES: dict[int, list[str]] = {
    2023: [
        "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
        "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    ],
    2024: [
        "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
        "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    ],
    2025: [
        "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
        "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    ],
    2026: [
        "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
        "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
    ],
    2027: [
        "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09",
        "2027-07-28", "2027-09-15", "2027-10-27", "2027-12-08",
    ],
}
FOMC_HOUR, FOMC_MIN = 19, 0

# ---------------------------------------------------------------------------
# Hardcoded CPI dates (released at 13:30 UTC)
# ---------------------------------------------------------------------------
CPI_DATES: dict[int, list[str]] = {
    2023: [
        "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12",
        "2023-05-10", "2023-06-13", "2023-07-12", "2023-08-10",
        "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
    ],
    2024: [
        "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10",
        "2024-05-15", "2024-06-12", "2024-07-11", "2024-08-14",
        "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    ],
    2025: [
        "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10",
        "2025-05-13", "2025-06-11", "2025-07-15", "2025-08-12",
        "2025-09-11", "2025-10-14", "2025-11-12", "2025-12-10",
    ],
}
CPI_HOUR, CPI_MIN = 13, 30


def _first_friday(year: int, month: int) -> int:
    """Return day of the first Friday in a given month."""
    cal = calendar.monthcalendar(year, month)
    # Friday is index 4 in the week row
    for week in cal:
        if week[4] != 0:
            return week[4]
    return 1  # fallback


def _build_nfp_dates(year: int) -> list[str]:
    """Generate NFP dates (first Friday of each month) for a year."""
    dates = []
    for month in range(1, 13):
        day = _first_friday(year, month)
        dates.append(f"{year}-{month:02d}-{day:02d}")
    return dates


def _parse_date_with_time(date_str: str, hour: int, minute: int) -> datetime:
    """Parse 'YYYY-MM-DD' + hour/min into UTC datetime."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.replace(hour=hour, minute=minute, tzinfo=timezone.utc)


def build_events(start_year: int = 2023, end_year: int = 2027) -> list[NewsEvent]:
    """Build full list of news events for the date range."""
    events: list[NewsEvent] = []

    for year in range(start_year, end_year + 1):
        # FOMC
        for date_str in FOMC_DATES.get(year, []):
            events.append(
                NewsEvent(
                    time_utc=_parse_date_with_time(date_str, FOMC_HOUR, FOMC_MIN),
                    name="FOMC Rate Decision",
                    high_impact=True,
                )
            )

        # CPI
        for date_str in CPI_DATES.get(year, []):
            events.append(
                NewsEvent(
                    time_utc=_parse_date_with_time(date_str, CPI_HOUR, CPI_MIN),
                    name="US CPI",
                    high_impact=True,
                )
            )

        # NFP
        for date_str in _build_nfp_dates(year):
            events.append(
                NewsEvent(
                    time_utc=_parse_date_with_time(date_str, 13, 30),
                    name="Non-Farm Payrolls",
                    high_impact=True,
                )
            )

    events.sort(key=lambda e: e.time_utc)
    return events


class NewsFilter:
    """Check if current time is in a news blackout window."""

    def __init__(self, config: dict) -> None:
        filters = config.get("filters", {})
        self.enabled = filters.get("news_filter_enabled", True)
        self.mins_before = filters.get("news_mins_before", 15)
        self.mins_after = filters.get("news_mins_after", 15)
        self.close_positions = filters.get("news_close_positions", True)
        self.high_only = filters.get("news_high_impact_only", True)

        # Build events covering backtest + live range
        all_events = build_events(2023, 2027)
        if self.high_only:
            all_events = [e for e in all_events if e.high_impact]
        self.events = all_events

    def is_blackout(self, utc_now: datetime) -> tuple[bool, str]:
        """Check if utc_now falls within any blackout window.

        Returns (in_blackout, event_name).
        """
        if not self.enabled:
            return False, ""

        before = timedelta(minutes=self.mins_before)
        after = timedelta(minutes=self.mins_after)

        for event in self.events:
            if event.time_utc - before <= utc_now <= event.time_utc + after:
                return True, event.name

        return False, ""

    def get_next_event(self, utc_now: datetime) -> NewsEvent | None:
        """Return the next upcoming event, or None."""
        for event in self.events:
            if event.time_utc > utc_now:
                return event
        return None
