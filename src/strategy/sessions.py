"""Session window definitions and range builder."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from src.utils.time_utils import is_within_window


@dataclass
class SessionRange:
    """Tracks price range for a single trading session."""

    name: str
    range_start: str  # "HH:MM"
    range_end: str    # "HH:MM"
    enabled: bool = True

    high: float = field(default=-math.inf)
    low: float = field(default=math.inf)
    range_building: bool = False
    range_complete: bool = False
    orders_placed: bool = False
    buy_filled: bool = False
    sell_filled: bool = False
    buy_level: float = 0.0
    sell_level: float = 0.0

    def reset(self) -> None:
        """Reset for a new day."""
        self.high = -math.inf
        self.low = math.inf
        self.range_building = False
        self.range_complete = False
        self.orders_placed = False
        self.buy_filled = False
        self.sell_filled = False
        self.buy_level = 0.0
        self.sell_level = 0.0

    def update(self, candle_high: float, candle_low: float, now: datetime) -> bool:
        """Update session range with candle data.

        Returns True if the range just completed (transition from building -> complete).
        """
        in_window = is_within_window(now, self.range_start, self.range_end)

        # Phase 1: Building the range
        if in_window and not self.range_complete:
            self.range_building = True
            if candle_high > self.high:
                self.high = candle_high
            if candle_low < self.low:
                self.low = candle_low
            return False

        # Phase 2: Window just closed -> range complete
        if not in_window and self.range_building and not self.range_complete:
            self.range_building = False
            self.range_complete = True
            return True

        return False

    def is_valid(self) -> bool:
        """Check if range has valid high/low data."""
        return self.high > -math.inf and self.low < math.inf and self.high != self.low


def build_sessions(config: dict) -> dict[str, SessionRange]:
    """Create session range objects from config."""
    sessions_cfg = config.get("sessions", {})
    result = {}

    for name, cfg in sessions_cfg.items():
        result[name] = SessionRange(
            name=name,
            range_start=cfg["range_start"],
            range_end=cfg["range_end"],
            enabled=cfg.get("enabled", True),
        )

    return result


def reset_all_sessions(sessions: dict[str, SessionRange]) -> None:
    """Reset all sessions for a new UTC day."""
    for sr in sessions.values():
        sr.reset()
