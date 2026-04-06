"""Trade dataclass and state machine."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Trade:
    """Represents a completed or open trade."""

    trade_id: str
    asset: str
    session: str       # 'tokyo' | 'london' | 'new_york' | 'daily'
    direction: str     # 'long' | 'short'
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    sl: float = 0.0
    tp: float = 0.0
    lot_size: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""  # 'sl' | 'tp' | 'trailing_sl' | 'eod_cancel' | 'news'
    builder_fee_usd: float = 0.0
    breakeven_applied: bool = False

    @property
    def is_open(self) -> bool:
        return self.exit_time is None

    # Cost fields
    fee_usd: float = 0.0
    slippage_usd: float = 0.0
    funding_usd: float = 0.0
    gross_pnl_usd: float = 0.0

    def close(
        self,
        exit_time: pd.Timestamp,
        exit_price: float,
        reason: str,
        costs: dict | None = None,
    ) -> None:
        """Close the trade and compute PnL after fees, slippage, and funding."""
        self.exit_time = exit_time
        self.exit_price = exit_price
        self.exit_reason = reason

        if self.direction == "long":
            self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        else:
            self.pnl_pct = (self.entry_price - exit_price) / self.entry_price

        notional = self.lot_size * self.entry_price
        self.gross_pnl_usd = notional * self.pnl_pct

        if costs:
            # Exchange fee: both entry and exit (round trip)
            fee_bps = costs.get("exchange_fee_bps", 0)
            self.fee_usd = notional * (fee_bps / 10_000) * 2  # entry + exit

            # Slippage: both entry and exit
            slip_bps = costs.get("slippage_bps", 0)
            self.slippage_usd = notional * (slip_bps / 10_000) * 2

            # Builder fee: both sides
            builder_bps = costs.get("builder_fee_bps", 0)
            self.builder_fee_usd = notional * (builder_bps / 10_000) * 2

            # Funding: proportional to hold time in hours
            funding_bps = costs.get("funding_rate_bps", 0)
            if self.entry_time and exit_time:
                hold_hours = (exit_time - self.entry_time).total_seconds() / 3600
                self.funding_usd = notional * (funding_bps / 10_000) * hold_hours
        else:
            self.fee_usd = 0.0
            self.slippage_usd = 0.0
            self.builder_fee_usd = 0.0
            self.funding_usd = 0.0

        total_costs = self.fee_usd + self.slippage_usd + self.builder_fee_usd + self.funding_usd
        self.pnl_usd = self.gross_pnl_usd - total_costs

    def update_trailing_stop(self, current_price: float, config: dict) -> None:
        """Update trailing stop if conditions are met."""
        mgmt = config["management"]
        if not mgmt["trailing_stop_enabled"]:
            return

        start_pct = mgmt["trailing_start_pct"] / 100
        dist_pct = mgmt["trailing_distance_pct"] / 100
        step_pct = mgmt.get("trailing_step_pct", 0) / 100

        if self.direction == "long":
            threshold = self.entry_price * (1 + start_pct)
            if current_price >= threshold:
                new_sl = current_price * (1 - dist_pct)
                if step_pct > 0 and (new_sl - self.sl) < self.entry_price * step_pct:
                    return
                if new_sl > self.sl:
                    self.sl = new_sl
        else:
            threshold = self.entry_price * (1 - start_pct)
            if current_price <= threshold:
                new_sl = current_price * (1 + dist_pct)
                if step_pct > 0 and (self.sl - new_sl) < self.entry_price * step_pct:
                    return
                if new_sl < self.sl or self.sl == 0:
                    self.sl = new_sl

    def update_breakeven(self, current_price: float, config: dict) -> None:
        """Move SL to breakeven if conditions are met."""
        mgmt = config["management"]
        if not mgmt["breakeven_enabled"] or self.breakeven_applied:
            return

        be_pct = mgmt["breakeven_trigger_pct"] / 100

        if self.direction == "long":
            if current_price >= self.entry_price * (1 + be_pct):
                self.sl = self.entry_price
                self.breakeven_applied = True
        else:
            if current_price <= self.entry_price * (1 - be_pct):
                self.sl = self.entry_price
                self.breakeven_applied = True
