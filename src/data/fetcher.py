"""Fetch OHLCV candles from Hyperliquid REST API."""

from __future__ import annotations

import logging
import time as _time

import pandas as pd
import requests

from src.utils.time_utils import date_to_unix_ms, ts_to_utc

logger = logging.getLogger("breakout")

BASE_URL = "https://api.hyperliquid.xyz/info"
MAX_CANDLES_PER_REQ = 5000
RATE_LIMIT_SLEEP = 0.2  # 200ms between requests


def fetch_candles(
    coin: str,
    interval: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Fetch OHLCV candles in chunks, return a single DataFrame.

    Args:
        coin: Asset symbol, e.g. 'BTC'
        interval: Candle interval, e.g. '1m'
        start_date: 'YYYY-MM-DD'
        end_date: 'YYYY-MM-DD'
    """
    start_ms = date_to_unix_ms(start_date)
    end_ms = date_to_unix_ms(end_date)

    all_candles: list[dict] = []
    cursor = start_ms

    while cursor < end_ms:
        payload = {
            "type": "candleSnapshot",
            "req": {
                "coin": coin,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
            },
        }

        resp = requests.post(BASE_URL, json=payload, timeout=30)
        resp.raise_for_status()
        candles = resp.json()

        if not candles:
            # Data may not be available this far back — skip forward by 1 day
            logger.debug("Empty response for %s at cursor %d, advancing...", coin, cursor)
            cursor += 86_400_000  # skip 1 day
            _time.sleep(RATE_LIMIT_SLEEP)
            continue

        all_candles.extend(candles)
        last_t = candles[-1]["t"]
        logger.info(
            "%s: fetched %d candles, last=%s",
            coin,
            len(candles),
            ts_to_utc(last_t),
        )

        # Move cursor past last candle
        cursor = last_t + 1
        _time.sleep(RATE_LIMIT_SLEEP)

    if not all_candles:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    return _parse_candles(all_candles)


def _parse_candles(raw: list[dict]) -> pd.DataFrame:
    """Convert raw JSON candles to typed DataFrame."""
    rows = []
    for c in raw:
        rows.append(
            {
                "timestamp": ts_to_utc(c["t"]),
                "open": float(c["o"]),
                "high": float(c["h"]),
                "low": float(c["l"]),
                "close": float(c["c"]),
                "volume": float(c["v"]),
            }
        )

    df = pd.DataFrame(rows)
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df
