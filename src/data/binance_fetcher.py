"""Fetch OHLCV candles from Binance via ccxt (no API key needed)."""

from __future__ import annotations

import logging
import time as _time

import ccxt
import pandas as pd

from src.utils.time_utils import date_to_unix_ms, ts_to_utc

logger = logging.getLogger("breakout")

# Binance perpetual futures symbols
SYMBOL_MAP = {
    "BTC": "BTC/USDT:USDT",
    "ETH": "ETH/USDT:USDT",
    "SOL": "SOL/USDT:USDT",
}

# ccxt interval names match Hyperliquid: '1m', '5m', '15m', '1h', '4h', '1d'
MAX_CANDLES = 1500  # Binance limit per request
RATE_LIMIT_SLEEP = 0.1


def fetch_candles_binance(
    coin: str,
    interval: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch OHLCV from Binance Futures. No API key required.

    Args:
        coin: 'BTC', 'ETH', or 'SOL'
        interval: '1m', '5m', '15m', '1h', '4h', '1d'
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
    """
    symbol = SYMBOL_MAP.get(coin)
    if not symbol:
        raise ValueError(f"Unknown coin '{coin}'. Supported: {list(SYMBOL_MAP.keys())}")

    exchange = ccxt.binance({"options": {"defaultType": "future"}})

    start_ms = date_to_unix_ms(start_date)
    end_ms = date_to_unix_ms(end_date)
    cursor = start_ms

    all_rows: list[dict] = []

    while cursor < end_ms:
        try:
            ohlcv = exchange.fetch_ohlcv(
                symbol,
                timeframe=interval,
                since=cursor,
                limit=MAX_CANDLES,
            )
        except Exception as e:
            logger.error("Binance fetch error for %s: %s", coin, e)
            break

        if not ohlcv:
            break

        for row in ohlcv:
            ts_ms, o, h, l, c, v = row
            if ts_ms >= end_ms:
                break
            all_rows.append({
                "timestamp": ts_to_utc(ts_ms),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            })

        last_ts = ohlcv[-1][0]
        if last_ts >= end_ms:
            break

        logger.info(
            "%s (Binance): fetched %d candles, last=%s",
            coin, len(ohlcv), ts_to_utc(last_ts),
        )

        cursor = last_ts + 1
        _time.sleep(RATE_LIMIT_SLEEP)

    if not all_rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)

    logger.info("%s (Binance): total %d candles", coin, len(df))
    return df
