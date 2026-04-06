"""Load config.yaml and .env into a single config dict."""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def load_config(config_path: str | Path | None = None) -> dict:
    """Load config.yaml and overlay .env secrets."""
    if config_path is None:
        config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    else:
        config_path = Path(config_path)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Load .env if it exists (optional for cloud deployment)
    env_path = config_path.parent / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            pass

    # Overlay secrets (all optional for backtest-only mode)
    cfg.setdefault("secrets", {})
    cfg["secrets"]["hl_private_key"] = os.getenv("HL_PRIVATE_KEY", "")
    cfg["secrets"]["hl_public_address"] = os.getenv("HL_PUBLIC_ADDRESS", "")
    cfg["secrets"]["builder_address"] = os.getenv("BUILDER_ADDRESS", "")
    cfg["secrets"]["hl_testnet"] = os.getenv("HL_TESTNET", "false").lower() == "true"

    if not cfg.get("builder", {}).get("address"):
        cfg.setdefault("builder", {})["address"] = cfg["secrets"]["builder_address"]

    return cfg
