"""
Stock universe mapping for the Institutional Momentum Trading System.

Defines:
    SECTOR_INDEX_MAP – Maps each stock symbol to its sector, sectoral index,
                       and the Upstox instrument key for that index.
    INDEX_KEYS       – Upstox instrument keys for major benchmark indices.
    SECTORS          – Unique set of sectors in the universe.

Usage:
    from config.universe import SECTOR_INDEX_MAP, INDEX_KEYS

    info = SECTOR_INDEX_MAP["ICICIBANK"]
    print(info["sector"])            # "Banking"
    print(info["upstox_index_key"])  # "NSE_INDEX|Nifty Bank"
"""

import json
from pathlib import Path
from typing import TypedDict


class StockInfo(TypedDict):
    """Type definition for a single stock's universe metadata."""
    sector: str
    index: str
    upstox_index_key: str
    liquidity_tier: int


# =============================================================================
# Stock → Sector / Index Mapping (Loaded Dynamically)
# =============================================================================

universe_path = Path(__file__).parent / "universe.json"
if universe_path.exists():
    with open(universe_path, "r", encoding="utf-8") as f:
        SECTOR_INDEX_MAP: dict[str, StockInfo] = json.load(f)
else:
    # Fallback to an empty dictionary if the universe is not yet built
    SECTOR_INDEX_MAP: dict[str, StockInfo] = {}


# =============================================================================
# Benchmark Index Instrument Keys (Upstox format)
# =============================================================================

INDEX_KEYS: dict[str, str] = {
    "NIFTY 50": "NSE_INDEX|Nifty 50",
    "NIFTY BANK": "NSE_INDEX|Nifty Bank",
    "INDIA VIX": "NSE_INDEX|India VIX",
    "NIFTY FINANCIAL SERVICES": "NSE_INDEX|Nifty Fin Service",
    "NIFTY ENERGY": "NSE_INDEX|Nifty Energy",
    "NIFTY PSE": "NSE_INDEX|Nifty PSE",
    "NIFTY 500": "NSE_INDEX|NIFTY 500",
    "NIFTY INDIA CONSUMPTION": "NSE_INDEX|Nifty India Consumption",
    "NIFTY IT": "NSE_INDEX|Nifty IT",
    "NIFTY METAL": "NSE_INDEX|Nifty Metal",
    "NIFTY PHARMA": "NSE_INDEX|Nifty Pharma",
    "NIFTY AUTO": "NSE_INDEX|Nifty Auto",
    "NIFTY REALTY": "NSE_INDEX|Nifty Realty",
}


# =============================================================================
# Derived Helpers
# =============================================================================

# Unique set of sectors present in the universe
SECTORS: set[str] = {info["sector"] for info in SECTOR_INDEX_MAP.values()}

# All stock symbols in the universe as a sorted list
UNIVERSE_SYMBOLS: list[str] = sorted(SECTOR_INDEX_MAP.keys())
