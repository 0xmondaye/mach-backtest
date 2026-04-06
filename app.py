"""Streamlit frontend for Breakout-HL backtesting."""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.backtest.engine import run_backtest
from src.backtest.metrics import BacktestResult
from src.data.cache import get_candles
from src.utils.config_loader import load_config
from src.utils.logger import setup_logger

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Breakout-HL Backtester",
    page_icon="📈",
    layout="wide",
)

setup_logger("breakout", "WARNING")

# ---------------------------------------------------------------------------
# Sidebar — parameters
# ---------------------------------------------------------------------------
st.sidebar.title("Breakout-HL")
st.sidebar.markdown("Session Range Breakout · Hyperliquid Perps")
st.sidebar.divider()

# Assets
all_assets = ["BTC", "ETH", "SOL"]
assets = st.sidebar.multiselect("Assets", all_assets, default=all_assets)

# Mode
mode = st.sidebar.selectbox("Mode", ["SESSION", "DAILY", "BOTH"], index=0)

# Date range
st.sidebar.subheader("Date Range")
col_s, col_e = st.sidebar.columns(2)
default_start = date.today() - timedelta(days=14)
default_end = date.today() - timedelta(days=1)
start_date = col_s.date_input("Start", value=default_start)
end_date = col_e.date_input("End", value=default_end)

# Data source
data_source = st.sidebar.selectbox(
    "Data Source",
    ["Binance", "Hyperliquid"],
    index=0,
    help="Binance has years of 1m data. Hyperliquid has limited retention.",
)
source_key = "binance" if data_source == "Binance" else "hyperliquid"

# Candle interval
interval = st.sidebar.selectbox(
    "Candle Interval",
    ["1m", "5m", "15m", "1h", "4h"],
    index=0 if data_source == "Binance" else 2,
    help="Binance: all intervals, years of history. Hyperliquid: 1m ~4d, 15m ~30d, 1h ~180d, 4h ~2yr",
)
if interval == "1m" and data_source == "Hyperliquid":
    st.sidebar.warning("Hyperliquid 1m data only available ~4 days back. Switch to Binance for more history.")

# Capital
initial_capital = st.sidebar.number_input("Initial Capital ($)", value=10000, step=1000, min_value=100)

# Sessions
st.sidebar.subheader("Sessions (UTC)")
col1, col2 = st.sidebar.columns(2)
tokyo_enabled = st.sidebar.checkbox("Tokyo", value=True)
tokyo_start = "00:00"
tokyo_end = "03:00"
london_enabled = st.sidebar.checkbox("London", value=True)
london_start = "07:00"
london_end = "09:00"
ny_enabled = st.sidebar.checkbox("New York", value=True)
ny_start = "13:00"
ny_end = "15:00"

# Order settings
st.sidebar.subheader("Orders")
tp_pct = st.sidebar.slider("Take Profit %", 0.5, 5.0, 1.5, 0.1)
sl_pct = st.sidebar.slider("Stop Loss %", 0.25, 3.0, 0.75, 0.05)

# Risk
st.sidebar.subheader("Risk")
risk_pct = st.sidebar.slider("Risk per Trade %", 0.1, 5.0, 1.0, 0.1)
max_dd = st.sidebar.slider("Max Daily Drawdown %", 0.0, 10.0, 3.0, 0.5)

# Trade management
st.sidebar.subheader("Trade Management")
trailing_enabled = st.sidebar.checkbox("Trailing Stop", value=True)
trailing_start = st.sidebar.slider("Trailing Start %", 0.1, 2.0, 0.3, 0.05)
trailing_dist = st.sidebar.slider("Trailing Distance %", 0.1, 2.0, 0.3, 0.05)
be_enabled = st.sidebar.checkbox("Breakeven", value=False)

# Execution costs
st.sidebar.subheader("Execution Costs")
exch_fee = st.sidebar.slider("Exchange Fee (bps/side)", 0.0, 10.0, 3.0, 0.5, help="HL taker = 3bp")
slip_bps = st.sidebar.slider("Slippage (bps/fill)", 0.0, 10.0, 1.5, 0.5)
fund_bps = st.sidebar.slider("Funding (bps/hr held)", 0.0, 5.0, 1.0, 0.25)
builder_bps = st.sidebar.slider("Builder Fee (bps/side)", 0.0, 5.0, 0.5, 0.1)

# News filter
st.sidebar.subheader("Filters")
news_enabled = st.sidebar.checkbox("News Filter (FOMC/CPI/NFP)", value=True)

# ---------------------------------------------------------------------------
# Build config from sidebar
# ---------------------------------------------------------------------------
def build_config() -> dict:
    config = load_config()
    config["assets"] = assets
    config["mode"] = mode
    config["sessions"] = {
        "tokyo": {"enabled": tokyo_enabled, "range_start": tokyo_start, "range_end": tokyo_end},
        "london": {"enabled": london_enabled, "range_start": london_start, "range_end": london_end},
        "new_york": {"enabled": ny_enabled, "range_start": ny_start, "range_end": ny_end},
    }
    config["orders"]["take_profit_pct"] = tp_pct
    config["orders"]["stop_loss_pct"] = sl_pct
    config["risk"]["risk_per_trade_pct"] = risk_pct
    config["risk"]["max_daily_drawdown_pct"] = max_dd
    config["management"]["trailing_stop_enabled"] = trailing_enabled
    config["management"]["trailing_start_pct"] = trailing_start
    config["management"]["trailing_distance_pct"] = trailing_dist
    config["management"]["breakeven_enabled"] = be_enabled
    config["filters"]["news_filter_enabled"] = news_enabled
    config["costs"] = {
        "exchange_fee_bps": exch_fee,
        "slippage_bps": slip_bps,
        "funding_rate_bps": fund_bps,
        "builder_fee_bps": builder_bps,
    }
    config["backtest"]["start_date"] = start_date.strftime("%Y-%m-%d")
    config["backtest"]["end_date"] = end_date.strftime("%Y-%m-%d")
    config["backtest"]["initial_capital"] = initial_capital
    config["backtest"]["candle_interval"] = interval
    return config


# ---------------------------------------------------------------------------
# Main area
# ---------------------------------------------------------------------------
st.title("📈 Breakout-HL Backtester")

if not assets:
    st.warning("Select at least one asset.")
    st.stop()

if start_date >= end_date:
    st.warning("Start date must be before end date.")
    st.stop()

run_btn = st.button("Run Backtest", type="primary", use_container_width=True)

if run_btn:
    config = build_config()

    # ---- Fetch data ----
    candle_data: dict[str, pd.DataFrame] = {}
    progress = st.progress(0, text="Loading candle data...")

    for i, asset in enumerate(assets):
        progress.progress((i) / len(assets), text=f"Fetching {asset} from {data_source}...")
        df = get_candles(
            asset,
            interval,
            config["backtest"]["start_date"],
            config["backtest"]["end_date"],
            source=source_key,
        )
        if df.empty:
            st.error(f"No data for {asset}. Try a more recent date range or larger interval.")
        else:
            candle_data[asset] = df

    if not candle_data:
        st.error("No candle data loaded.")
        st.stop()

    progress.progress(0.8, text="Running backtest...")

    # ---- Run backtest ----
    result = run_backtest(config, candle_data)
    progress.progress(1.0, text="Done!")

    # Store in session state so it persists
    st.session_state["result"] = result
    st.session_state["config"] = config
    st.session_state["candle_data"] = candle_data

# ---------------------------------------------------------------------------
# Display results
# ---------------------------------------------------------------------------
if "result" not in st.session_state:
    st.info("Configure parameters in the sidebar and click **Run Backtest**.")
    st.stop()

result: BacktestResult = st.session_state["result"]
config = st.session_state["config"]

# ---- Top-level metrics ----
st.divider()
cols = st.columns(4)
cols[0].metric("Combined PnL", f"${result.combined_pnl:,.2f}")
cols[1].metric("Max Drawdown", f"{result.combined_max_drawdown_pct:.2f}%")
cols[2].metric("Total Trades", str(len(result.all_trades)))
wins = sum(1 for t in result.all_trades if t.pnl_usd > 0)
total = len(result.all_trades) or 1
cols[3].metric("Win Rate", f"{wins / total * 100:.1f}%")

# Cost breakdown
total_fees = sum(t.fee_usd for t in result.all_trades)
total_slip = sum(t.slippage_usd for t in result.all_trades)
total_funding = sum(t.funding_usd for t in result.all_trades)
total_builder = sum(t.builder_fee_usd for t in result.all_trades)
total_costs = total_fees + total_slip + total_funding + total_builder
total_gross = sum(t.gross_pnl_usd for t in result.all_trades)

ccols = st.columns(6)
ccols[0].metric("Gross PnL", f"${total_gross:,.2f}")
ccols[1].metric("Exchange Fees", f"-${total_fees:,.2f}")
ccols[2].metric("Slippage", f"-${total_slip:,.2f}")
ccols[3].metric("Funding", f"-${total_funding:,.2f}")
ccols[4].metric("Builder Fees", f"-${total_builder:,.2f}")
ccols[5].metric("Total Costs", f"-${total_costs:,.2f}")

# ---- Equity curve ----
st.subheader("Equity Curve")

fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.06,
    row_heights=[0.72, 0.28],
    subplot_titles=("Equity", "Drawdown %"),
)

colors = {"BTC": "#F7931A", "ETH": "#627EEA", "SOL": "#00FFA3"}

for asset, m in result.asset_metrics.items():
    eq = m.equity_curve
    color = colors.get(asset, "#888")
    fig.add_trace(
        go.Scatter(y=eq.values, name=asset, mode="lines", line=dict(color=color)),
        row=1, col=1,
    )
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    fig.add_trace(
        go.Scatter(y=dd.values, name=f"{asset} DD", mode="lines", line=dict(color=color, dash="dot")),
        row=2, col=1,
    )

if len(result.combined_equity_curve) > 0:
    fig.add_trace(
        go.Scatter(
            y=result.combined_equity_curve.values,
            name="Combined",
            mode="lines",
            line=dict(width=2.5, color="white", dash="dash"),
        ),
        row=1, col=1,
    )

fig.update_layout(
    template="plotly_dark",
    height=550,
    margin=dict(t=40, b=20),
    legend=dict(orientation="h", y=1.02),
)
fig.update_yaxes(title_text="$", row=1, col=1)
fig.update_yaxes(title_text="%", row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# ---- Per-asset tables ----
st.subheader("Per-Asset Metrics")

asset_tabs = st.tabs(list(result.asset_metrics.keys()) + ["All Trades"])

for i, (asset, m) in enumerate(result.asset_metrics.items()):
    with asset_tabs[i]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Trades", m.total_trades)
        c2.metric("Win Rate", f"{m.win_rate:.1f}%")
        c3.metric("Profit Factor", f"{m.profit_factor:.2f}")
        c4.metric("Sharpe Ratio", f"{m.sharpe_ratio:.2f}")

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Total PnL", f"${m.total_pnl:,.2f}")
        c6.metric("Max Drawdown", f"{m.max_drawdown_pct:.2f}%")
        c7.metric("Best Trade", f"${m.best_trade:,.2f}")
        c8.metric("Worst Trade", f"${m.worst_trade:,.2f}")

        # Session breakdown
        if m.session_breakdown:
            st.markdown("**Session Breakdown**")
            srows = []
            for s in m.session_breakdown:
                srows.append({
                    "Session": s.session.replace("_", " ").title(),
                    "Trades": s.total_trades,
                    "Win Rate": f"{s.win_rate:.1f}%",
                    "Avg PnL": f"${s.avg_pnl:,.2f}",
                })
            st.dataframe(pd.DataFrame(srows), use_container_width=True, hide_index=True)

# All trades tab
with asset_tabs[-1]:
    trades_df = pd.DataFrame([
        {
            "Asset": t.asset,
            "Session": t.session,
            "Direction": t.direction,
            "Entry Time": t.entry_time,
            "Entry Price": f"{t.entry_price:,.2f}",
            "Exit Time": t.exit_time,
            "Exit Price": f"{t.exit_price:,.2f}" if t.exit_price else "",
            "Gross PnL": f"${t.gross_pnl_usd:,.2f}",
            "Fees": f"-${t.fee_usd:.2f}",
            "Slip": f"-${t.slippage_usd:.2f}",
            "Fund": f"-${t.funding_usd:.2f}",
            "Net PnL": f"${t.pnl_usd:,.2f}",
            "Exit": t.exit_reason,
        }
        for t in result.all_trades
    ])

    # Color rows by PnL
    st.dataframe(trades_df, use_container_width=True, hide_index=True, height=500)

    # Download CSV
    csv = trades_df.to_csv(index=False)
    st.download_button("Download Trades CSV", csv, "trades.csv", "text/csv")

# ---- Price chart with levels ----
st.subheader("Price Action & Levels")

if "candle_data" in st.session_state:
    price_asset = st.selectbox("Asset", list(st.session_state["candle_data"].keys()))
    cdf = st.session_state["candle_data"][price_asset]

    pfig = go.Figure()
    pfig.add_trace(go.Candlestick(
        x=cdf["timestamp"],
        open=cdf["open"],
        high=cdf["high"],
        low=cdf["low"],
        close=cdf["close"],
        name=price_asset,
    ))

    # Overlay trade entries/exits
    asset_trades = [t for t in result.all_trades if t.asset == price_asset]
    for t in asset_trades:
        color = "lime" if t.pnl_usd > 0 else "red"
        marker = "triangle-up" if t.direction == "long" else "triangle-down"

        pfig.add_trace(go.Scatter(
            x=[t.entry_time],
            y=[t.entry_price],
            mode="markers",
            marker=dict(symbol=marker, size=10, color=color),
            name=f"{t.direction} entry",
            showlegend=False,
            hovertext=f"{t.session} {t.direction} → {t.exit_reason} ${t.pnl_usd:.2f}",
        ))
        if t.exit_time and t.exit_price:
            pfig.add_trace(go.Scatter(
                x=[t.exit_time],
                y=[t.exit_price],
                mode="markers",
                marker=dict(symbol="x", size=8, color=color),
                showlegend=False,
            ))

    pfig.update_layout(
        template="plotly_dark",
        height=500,
        xaxis_rangeslider_visible=False,
        margin=dict(t=20, b=20),
    )
    st.plotly_chart(pfig, use_container_width=True)
