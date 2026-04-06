"""PnL, Sharpe, drawdown, win-rate calculations."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.backtest.trade import Trade


@dataclass
class SessionMetrics:
    """Metrics for a single session."""

    session: str
    total_trades: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0


@dataclass
class AssetMetrics:
    """Full metrics for a single asset."""

    asset: str
    total_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    session_breakdown: list[SessionMetrics] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))


@dataclass
class BacktestResult:
    """Aggregated result of a backtest run."""

    asset_metrics: dict[str, AssetMetrics] = field(default_factory=dict)
    combined_pnl: float = 0.0
    combined_max_drawdown_pct: float = 0.0
    combined_equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    all_trades: list[Trade] = field(default_factory=list)


def compute_asset_metrics(
    trades: list[Trade],
    asset: str,
    initial_capital: float,
) -> AssetMetrics:
    """Compute all metrics for a single asset's trades."""
    if not trades:
        return AssetMetrics(asset=asset)

    pnls = [t.pnl_usd for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0

    # Equity curve
    equity = [initial_capital]
    for pnl in pnls:
        equity.append(equity[-1] + pnl)
    eq_series = pd.Series(equity)

    # Max drawdown
    peak = eq_series.cummax()
    dd = (eq_series - peak) / peak * 100
    max_dd = abs(dd.min())

    # Sharpe ratio (annualized, 0% risk-free)
    if len(pnls) > 1:
        returns = np.array(pnls) / initial_capital
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0.0
    else:
        sharpe = 0.0

    # Session breakdown
    session_names = sorted(set(t.session for t in trades))
    session_breakdown = []
    for sname in session_names:
        s_trades = [t for t in trades if t.session == sname]
        s_pnls = [t.pnl_usd for t in s_trades]
        s_wins = [p for p in s_pnls if p > 0]
        session_breakdown.append(
            SessionMetrics(
                session=sname,
                total_trades=len(s_trades),
                win_rate=len(s_wins) / len(s_trades) * 100 if s_trades else 0,
                avg_pnl=np.mean(s_pnls) if s_pnls else 0,
            )
        )

    total_pnl = sum(pnls)
    return AssetMetrics(
        asset=asset,
        total_trades=len(trades),
        win_rate=len(wins) / len(trades) * 100 if trades else 0,
        avg_win=np.mean(wins) if wins else 0,
        avg_loss=np.mean(losses) if losses else 0,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else float("inf"),
        max_drawdown_pct=max_dd,
        sharpe_ratio=sharpe,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl / initial_capital * 100,
        best_trade=max(pnls) if pnls else 0,
        worst_trade=min(pnls) if pnls else 0,
        session_breakdown=session_breakdown,
        equity_curve=eq_series,
    )


def compute_combined(
    asset_results: dict[str, AssetMetrics],
    initial_capital: float,
) -> tuple[float, float, pd.Series]:
    """Compute combined portfolio metrics.

    Returns (combined_pnl, combined_max_dd_pct, combined_equity_curve).
    """
    if not asset_results:
        return 0.0, 0.0, pd.Series(dtype=float)

    # Sum equity curves (align by index length)
    max_len = max(len(m.equity_curve) for m in asset_results.values())
    combined = pd.Series(np.zeros(max_len))

    for m in asset_results.values():
        curve = m.equity_curve.reindex(range(max_len), method="ffill").ffill()
        combined += curve

    # Normalize to per-asset capital
    combined_pnl = sum(m.total_pnl for m in asset_results.values())

    peak = combined.cummax()
    dd = (combined - peak) / peak * 100
    combined_dd = abs(dd.min())

    return combined_pnl, combined_dd, combined
