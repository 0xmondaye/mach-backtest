"""Load config.yaml and .env into a single config dict."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv


def load_config(config_path: str | Path | None = None) -> dict:
    """Load config.yaml and overlay .env secrets."""
    if config_path is None:
        config_path = Path(__file__).resolve().parents[2] / "config.yaml"
    else:
        config_path = Path(config_path)

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Load .env from project root
    env_path = config_path.parent / ".env"
    load_dotenv(env_path)

    # Overlay secrets
    cfg.setdefault("secrets", {})
    cfg["secrets"]["hl_private_key"] = os.getenv("HL_PRIVATE_KEY", "")
    cfg["secrets"]["hl_public_address"] = os.getenv("HL_PUBLIC_ADDRESS", "")
    cfg["secrets"]["builder_address"] = os.getenv("BUILDER_ADDRESS", "")
    cfg["secrets"]["hl_testnet"] = os.getenv("HL_TESTNET", "false").lower() == "true"

    # Populate builder address from env if not set in yaml
    if not cfg.get("builder", {}).get("address"):
        cfg.setdefault("builder", {})["address"] = cfg["secrets"]["builder_address"]

    return cfg
