"""Buy-stop / sell-stop level generator and position sizing."""

from __future__ import annotations

from dataclasses import dataclass

from src.strategy.sessions import SessionRange


@dataclass
class PendingOrder:
    """A pending stop order waiting to be filled."""

    asset: str
    session: str       # 'tokyo' | 'london' | 'new_york' | 'daily'
    direction: str     # 'long' | 'short'
    trigger_price: float
    sl: float
    tp: float
    lot_size: float


def compute_levels(session: SessionRange, price: float) -> tuple[float, float]:
    """Compute buy/sell breakout levels from session range.

    Returns (buy_level, sell_level).
    """
    offset = price * 0.001  # ~0.1% of price
    buy_level = session.high + offset
    sell_level = session.low - offset
    return buy_level, sell_level


def compute_daily_levels(
    prev_high: float,
    prev_low: float,
    reference_price: float,
) -> tuple[float, float]:
    """Compute daily breakout levels from previous day high/low."""
    offset = reference_price * 0.001
    buy_level = prev_high + offset
    sell_level = prev_low - offset
    return buy_level, sell_level


def calculate_sl_tp(
    entry_price: float,
    direction: str,
    config: dict,
) -> tuple[float, float]:
    """Calculate stop-loss and take-profit prices.

    Returns (sl, tp).
    """
    sl_pct = config["orders"]["stop_loss_pct"] / 100
    tp_pct = config["orders"]["take_profit_pct"] / 100

    if direction == "long":
        sl = entry_price * (1 - sl_pct)
        tp = entry_price * (1 + tp_pct)
    else:
        sl = entry_price * (1 + sl_pct)
        tp = entry_price * (1 - tp_pct)

    return sl, tp


def calculate_lot_size(
    account_balance: float,
    entry: float,
    sl: float,
    config: dict,
) -> float:
    """Calculate position size based on risk parameters."""
    risk_cfg = config["risk"]

    if not risk_cfg["use_auto_lot"]:
        return risk_cfg["fixed_lot_size"]

    risk_amount = account_balance * (risk_cfg["risk_per_trade_pct"] / 100)
    sl_distance_pct = abs(entry - sl) / entry

    if sl_distance_pct == 0:
        return risk_cfg["fixed_lot_size"]

    lot_size = risk_amount / (entry * sl_distance_pct)
    return round(lot_size, 4)


def generate_orders(
    session: SessionRange,
    asset: str,
    reference_price: float,
    account_balance: float,
    config: dict,
) -> list[PendingOrder]:
    """Generate pending stop orders for a completed session range.

    Returns list of 0-2 PendingOrder objects.
    """
    if not session.is_valid():
        return []

    buy_level, sell_level = compute_levels(session, reference_price)
    session.buy_level = buy_level
    session.sell_level = sell_level

    orders = []

    if not session.buy_filled:
        sl, tp = calculate_sl_tp(buy_level, "long", config)
        lot = calculate_lot_size(account_balance, buy_level, sl, config)
        orders.append(
            PendingOrder(
                asset=asset,
                session=session.name,
                direction="long",
                trigger_price=buy_level,
                sl=sl,
                tp=tp,
                lot_size=lot,
            )
        )

    if not session.sell_filled:
        sl, tp = calculate_sl_tp(sell_level, "short", config)
        lot = calculate_lot_size(account_balance, sell_level, sl, config)
        orders.append(
            PendingOrder(
                asset=asset,
                session=session.name,
                direction="short",
                trigger_price=sell_level,
                sl=sl,
                tp=tp,
                lot_size=lot,
            )
        )

    return orders
