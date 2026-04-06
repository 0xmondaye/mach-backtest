"""Core backtesting simulation loop."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

import pandas as pd

from src.backtest.metrics import (
    AssetMetrics,
    BacktestResult,
    compute_asset_metrics,
    compute_combined,
)
from src.backtest.trade import Trade
from src.strategy.news_filter import NewsFilter
from src.strategy.sessions import SessionRange, build_sessions, reset_all_sessions
from src.strategy.signals import (
    PendingOrder,
    calculate_lot_size,
    calculate_sl_tp,
    compute_daily_levels,
    compute_levels,
)
from src.utils.time_utils import is_time_reached, is_trading_day_allowed, is_within_window

logger = logging.getLogger("breakout")


@dataclass
class DailyState:
    """Tracks daily-mode state."""

    prev_high: float = 0.0
    prev_low: float = 0.0
    orders_placed: bool = False
    buy_tapped: bool = False
    sell_tapped: bool = False
    buy_level: float = 0.0
    sell_level: float = 0.0


@dataclass
class BacktestState:
    """Full state for one asset during backtest."""

    asset: str
    balance: float
    day_start_balance: float = 0.0
    current_date: str = ""
    sessions: dict[str, SessionRange] = field(default_factory=dict)
    daily: DailyState = field(default_factory=DailyState)
    pending_orders: list[PendingOrder] = field(default_factory=list)
    open_positions: list[Trade] = field(default_factory=list)
    closed_trades: list[Trade] = field(default_factory=list)
    drawdown_triggered: bool = False
    in_blackout: bool = False
    blackout_high: float = 0.0
    blackout_low: float = float("inf")


def run_backtest_single_asset(
    df: pd.DataFrame,
    asset: str,
    config: dict,
) -> list[Trade]:
    """Run backtest on a single asset's candle data.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume]
        asset: e.g. 'BTC'
        config: full config dict

    Returns:
        List of all closed Trade objects.
    """
    initial_capital = config["backtest"]["initial_capital"]
    mode = config.get("mode", "SESSION").upper()
    costs = config.get("costs", {})
    news_filter = NewsFilter(config)

    state = BacktestState(
        asset=asset,
        balance=initial_capital,
        sessions=build_sessions(config),
    )

    for idx in range(len(df)):
        candle = df.iloc[idx]
        ts: pd.Timestamp = candle["timestamp"]
        now = ts.to_pydatetime()
        date_str = now.strftime("%Y-%m-%d")

        # --- New UTC day ---
        if date_str != state.current_date:
            _new_day(state, candle, date_str, df, idx)

        # --- Daily drawdown check ---
        if _check_drawdown(state, config):
            _manage_positions(state, candle, config)
            continue

        # --- Day-of-week filter ---
        if not is_trading_day_allowed(now, config.get("filters", {})):
            _manage_positions(state, candle, config)
            continue

        # --- News blackout ---
        in_blackout, event_name = news_filter.is_blackout(now)
        if in_blackout and not state.in_blackout:
            _enter_blackout(state, candle, news_filter, config)
        if state.in_blackout:
            if in_blackout:
                _track_blackout(state, candle)
                _manage_positions(state, candle, config)
                continue
            else:
                _exit_blackout(state, candle, config, mode)

        # --- Delete unfilled orders at end of day ---
        delete_time = config["orders"].get("delete_orders_utc", "23:00")
        if is_time_reached(now, delete_time):
            state.pending_orders.clear()

        # --- Daily mode ---
        if mode in ("DAILY", "BOTH"):
            _process_daily(state, now, candle, config)

        # --- Session mode ---
        if mode in ("SESSION", "BOTH"):
            _process_sessions(state, now, candle, config)

        # --- Check pending order fills ---
        _check_fills(state, candle, config)

        # --- Manage open positions ---
        _manage_positions(state, candle, config)

    # Close any remaining open positions at last candle
    if state.open_positions:
        last = df.iloc[-1]
        for pos in list(state.open_positions):
            pos.close(last["timestamp"], last["close"], "eod_cancel", costs)
            state.closed_trades.append(pos)
        state.open_positions.clear()

    return state.closed_trades


def _new_day(
    state: BacktestState,
    candle: pd.Series,
    date_str: str,
    df: pd.DataFrame,
    idx: int,
) -> None:
    """Handle UTC midnight reset."""
    state.current_date = date_str
    state.day_start_balance = state.balance
    state.drawdown_triggered = False
    state.pending_orders.clear()

    # Reset sessions
    reset_all_sessions(state.sessions)

    # Reset daily state
    state.daily = DailyState()

    # Compute previous day high/low
    if idx > 0:
        prev_day = (candle["timestamp"] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        prev_mask = df["timestamp"].dt.strftime("%Y-%m-%d") == prev_day
        prev_candles = df[prev_mask]
        if not prev_candles.empty:
            state.daily.prev_high = prev_candles["high"].max()
            state.daily.prev_low = prev_candles["low"].min()


def _check_drawdown(state: BacktestState, config: dict) -> bool:
    """Check daily drawdown kill switch."""
    max_dd = config["risk"]["max_daily_drawdown_pct"]
    if max_dd <= 0:
        return False

    if state.day_start_balance <= 0:
        return False

    current_dd = (state.day_start_balance - state.balance) / state.day_start_balance * 100
    if current_dd >= max_dd:
        if not state.drawdown_triggered:
            state.drawdown_triggered = True
            state.pending_orders.clear()
            logger.warning(
                "%s: Daily drawdown %.2f%% >= %.2f%%, orders cancelled",
                state.asset,
                current_dd,
                max_dd,
            )
        return True
    return False


def _enter_blackout(
    state: BacktestState,
    candle: pd.Series,
    news_filter: NewsFilter,
    config: dict,
) -> None:
    """Enter news blackout — cancel orders, optionally close positions."""
    state.in_blackout = True
    state.blackout_high = candle["high"]
    state.blackout_low = candle["low"]
    state.pending_orders.clear()

    if news_filter.close_positions:
        costs = config.get("costs", {})
        for pos in list(state.open_positions):
            pos.close(candle["timestamp"], candle["close"], "news", costs)
            state.balance += pos.pnl_usd
            state.closed_trades.append(pos)
        state.open_positions.clear()


def _track_blackout(state: BacktestState, candle: pd.Series) -> None:
    """Track price extremes during blackout."""
    if candle["high"] > state.blackout_high:
        state.blackout_high = candle["high"]
    if candle["low"] < state.blackout_low:
        state.blackout_low = candle["low"]


def _exit_blackout(
    state: BacktestState,
    candle: pd.Series,
    config: dict,
    mode: str,
) -> None:
    """Exit blackout — check tapped levels, re-place untapped orders."""
    state.in_blackout = False

    # Check daily levels
    if mode in ("DAILY", "BOTH") and state.daily.orders_placed:
        if state.blackout_high >= state.daily.buy_level:
            state.daily.buy_tapped = True
        if state.blackout_low <= state.daily.sell_level:
            state.daily.sell_tapped = True
        state.daily.orders_placed = False

    # Check session levels
    if mode in ("SESSION", "BOTH"):
        for sr in state.sessions.values():
            if sr.range_complete and sr.orders_placed:
                if state.blackout_high >= sr.buy_level and not sr.buy_filled:
                    sr.buy_filled = True
                if state.blackout_low <= sr.sell_level and not sr.sell_filled:
                    sr.sell_filled = True
                sr.orders_placed = False

    state.blackout_high = 0.0
    state.blackout_low = float("inf")


def _process_daily(
    state: BacktestState,
    now,
    candle: pd.Series,
    config: dict,
) -> None:
    """Handle daily mode order placement."""
    if state.daily.orders_placed:
        return
    if state.daily.prev_high == 0 or state.daily.prev_low == 0:
        return

    # Place after 01:15 UTC
    daily_place_time = "01:15"
    delete_time = config["orders"].get("delete_orders_utc", "23:00")
    if not is_within_window(now, daily_place_time, delete_time):
        return

    ref_price = candle["close"]
    buy_level, sell_level = compute_daily_levels(
        state.daily.prev_high, state.daily.prev_low, ref_price
    )
    state.daily.buy_level = buy_level
    state.daily.sell_level = sell_level

    if not state.daily.buy_tapped:
        sl, tp = calculate_sl_tp(buy_level, "long", config)
        lot = calculate_lot_size(state.balance, buy_level, sl, config)
        state.pending_orders.append(
            PendingOrder(
                asset=state.asset, session="daily", direction="long",
                trigger_price=buy_level, sl=sl, tp=tp, lot_size=lot,
            )
        )

    if not state.daily.sell_tapped:
        sl, tp = calculate_sl_tp(sell_level, "short", config)
        lot = calculate_lot_size(state.balance, sell_level, sl, config)
        state.pending_orders.append(
            PendingOrder(
                asset=state.asset, session="daily", direction="short",
                trigger_price=sell_level, sl=sl, tp=tp, lot_size=lot,
            )
        )

    state.daily.orders_placed = True


def _process_sessions(
    state: BacktestState,
    now,
    candle: pd.Series,
    config: dict,
) -> None:
    """Update session ranges and place orders when ranges complete."""
    for sr in state.sessions.values():
        if not sr.enabled:
            continue

        just_completed = sr.update(candle["high"], candle["low"], now)

        if sr.range_complete and not sr.orders_placed:
            if not sr.is_valid():
                logger.warning("%s %s: flat range, skipping", state.asset, sr.name)
                sr.orders_placed = True
                continue

            ref_price = candle["close"]
            buy_level, sell_level = compute_levels(sr, ref_price)
            sr.buy_level = buy_level
            sr.sell_level = sell_level

            if not sr.buy_filled:
                sl, tp = calculate_sl_tp(buy_level, "long", config)
                lot = calculate_lot_size(state.balance, buy_level, sl, config)
                state.pending_orders.append(
                    PendingOrder(
                        asset=state.asset, session=sr.name, direction="long",
                        trigger_price=buy_level, sl=sl, tp=tp, lot_size=lot,
                    )
                )

            if not sr.sell_filled:
                sl, tp = calculate_sl_tp(sell_level, "short", config)
                lot = calculate_lot_size(state.balance, sell_level, sl, config)
                state.pending_orders.append(
                    PendingOrder(
                        asset=state.asset, session=sr.name, direction="short",
                        trigger_price=sell_level, sl=sl, tp=tp, lot_size=lot,
                    )
                )

            sr.orders_placed = True
            logger.debug(
                "%s %s: range complete H=%.2f L=%.2f → Buy=%.2f Sell=%.2f",
                state.asset, sr.name, sr.high, sr.low, buy_level, sell_level,
            )


def _check_fills(state: BacktestState, candle: pd.Series, config: dict) -> None:
    """Check if any pending stop orders are triggered by this candle."""
    filled = []

    for order in state.pending_orders:
        triggered = False

        if order.direction == "long" and candle["high"] >= order.trigger_price:
            triggered = True
        elif order.direction == "short" and candle["low"] <= order.trigger_price:
            triggered = True

        if triggered:
            trade = Trade(
                trade_id=str(uuid.uuid4())[:8],
                asset=order.asset,
                session=order.session,
                direction=order.direction,
                entry_time=candle["timestamp"],
                entry_price=order.trigger_price,
                sl=order.sl,
                tp=order.tp,
                lot_size=order.lot_size,
            )
            state.open_positions.append(trade)
            filled.append(order)

            # Mark one-shot
            _mark_filled(state, order)

            logger.debug(
                "%s %s %s filled at %.2f",
                order.asset, order.session, order.direction, order.trigger_price,
            )

    for order in filled:
        state.pending_orders.remove(order)


def _mark_filled(state: BacktestState, order: PendingOrder) -> None:
    """Mark the session's buy_filled or sell_filled flag."""
    if order.session == "daily":
        return

    sr = state.sessions.get(order.session)
    if sr:
        if order.direction == "long":
            sr.buy_filled = True
        else:
            sr.sell_filled = True


def _manage_positions(state: BacktestState, candle: pd.Series, config: dict) -> None:
    """Check SL/TP hits, update trailing stops and breakeven."""
    closed = []
    costs = config.get("costs", {})

    for pos in state.open_positions:
        exited, exit_price, reason = _check_exit(candle, pos)

        if exited:
            pos.close(candle["timestamp"], exit_price, reason, costs)
            state.balance += pos.pnl_usd
            closed.append(pos)
        else:
            # Update trailing stop and breakeven
            price = candle["close"]
            pos.update_breakeven(price, config)
            pos.update_trailing_stop(price, config)

    for pos in closed:
        state.open_positions.remove(pos)
        state.closed_trades.append(pos)


def _check_exit(candle: pd.Series, pos: Trade) -> tuple[bool, float, str]:
    """Check if position exits on this candle.

    Priority: SL -> TP -> (trailing stop is just SL movement, not an exit type)
    Returns (exited, exit_price, reason).
    """
    if pos.direction == "long":
        # SL hit
        if pos.sl > 0 and candle["low"] <= pos.sl:
            return True, pos.sl, "sl"
        # TP hit
        if pos.tp > 0 and candle["high"] >= pos.tp:
            return True, pos.tp, "tp"
    else:
        # SL hit
        if pos.sl > 0 and candle["high"] >= pos.sl:
            return True, pos.sl, "sl"
        # TP hit
        if pos.tp > 0 and candle["low"] <= pos.tp:
            return True, pos.tp, "tp"

    return False, 0.0, ""


def run_backtest(config: dict, candle_data: dict[str, pd.DataFrame]) -> BacktestResult:
    """Run backtest across all assets.

    Args:
        config: full config dict
        candle_data: {asset: DataFrame} mapping

    Returns:
        BacktestResult with per-asset and combined metrics.
    """
    initial_capital = config["backtest"]["initial_capital"]
    all_trades: list[Trade] = []
    asset_metrics: dict[str, AssetMetrics] = {}

    for asset, df in candle_data.items():
        logger.info("Running backtest for %s (%d candles)...", asset, len(df))
        trades = run_backtest_single_asset(df, asset, config)
        all_trades.extend(trades)

        metrics = compute_asset_metrics(trades, asset, initial_capital)
        asset_metrics[asset] = metrics
        logger.info(
            "%s: %d trades, %.1f%% win rate, $%.2f PnL, %.2f%% max DD",
            asset, metrics.total_trades, metrics.win_rate,
            metrics.total_pnl, metrics.max_drawdown_pct,
        )

    combined_pnl, combined_dd, combined_eq = compute_combined(asset_metrics, initial_capital)

    return BacktestResult(
        asset_metrics=asset_metrics,
        combined_pnl=combined_pnl,
        combined_max_drawdown_pct=combined_dd,
        combined_equity_curve=combined_eq,
        all_trades=all_trades,
    )
