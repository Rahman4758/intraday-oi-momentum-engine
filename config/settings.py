"""
Application settings loaded from environment variables via pydantic-settings.

All configuration is validated at startup. Missing required fields (API keys,
MongoDB URI) will raise a clear error immediately rather than failing later
at runtime.

Usage:
    from config.settings import settings
    print(settings.MONGO_URI)
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the .env file relative to the project root (one level up from config/)
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """
    Central configuration for the Institutional Momentum Trading System.

    Values are loaded from the .env file at the project root, with
    environment variables taking precedence over file-based values.
    """

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── Upstox API Credentials ──────────────────────────────────────────
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
    UPSTOX_ACCESS_TOKEN: str = ""
    UPSTOX_REDIRECT_URI: str = "http://localhost:8000/callback"

    # ── MongoDB ─────────────────────────────────────────────────────────
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "intraday_momentum"

    # ── Capital & Risk Management ───────────────────────────────────────
    CAPITAL: float = 100_000.0
    MAX_RISK_PER_TRADE: float = 1_000.0
    MAX_DAILY_LOSS: float = 3_000.0
    MAX_CONSECUTIVE_LOSSES: int = 3

    # ── Dashboard ───────────────────────────────────────────────────────
    DASHBOARD_HOST: str = "0.0.0.0"
    DASHBOARD_PORT: int = int(os.environ.get("PORT", 8000))

    # ── Logging ─────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"


# Module-level singleton – import this everywhere
settings = Settings()
