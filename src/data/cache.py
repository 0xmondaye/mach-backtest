"""Local parquet cache for historical candle data."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import pandas as pd

from src.data.binance_fetcher import fetch_candles_binance
from src.data.fetcher import fetch_candles

logger = logging.getLogger("breakout")

# Use temp dir for Streamlit Cloud compatibility
try:
    CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Test write
    test_file = CACHE_DIR / ".write_test"
    test_file.write_text("ok")
    test_file.unlink()
except Exception:
    CACHE_DIR = Path(tempfile.gettempdir()) / "mach_cache"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_candles(
    coin: str,
    interval: str,
    start_date: str,
    end_date: str,
    source: str = "hyperliquid",
) -> pd.DataFrame:
    """Get candles from cache or fetch and cache them."""
    prefix = "hl" if source == "hyperliquid" else "bn"
    cache_key = f"{prefix}_{coin}_{interval}_{start_date}_{end_date}.parquet"
    cache_path = CACHE_DIR / cache_key

    if cache_path.exists():
        logger.info("Loading %s from cache", cache_key)
        df = pd.read_parquet(cache_path)
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
        return df

    logger.info("Cache miss for %s, fetching from %s...", cache_key, source)

    if source == "binance":
        df = fetch_candles_binance(coin, interval, start_date, end_date)
    else:
        df = fetch_candles(coin, interval, start_date, end_date)

    if not df.empty:
        try:
            df.to_parquet(cache_path, index=False)
            logger.info("Cached %d candles to %s", len(df), cache_key)
        except Exception:
            pass  # Cache write failed — OK, just won't cache

    return df
