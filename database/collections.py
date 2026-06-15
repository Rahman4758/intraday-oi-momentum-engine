"""
Collection helpers for the Institutional Momentum Trading System.

Provides:
    - Collection name constants
    - Index creation (idempotent – safe to call on every startup)
    - Typed helper functions for common CRUD operations on each collection

All datetime values stored in MongoDB are in UTC.  Conversion to IST is
handled at the application/display layer, not here.

Usage:
    from database.collections import setup_indexes, save_live_score, get_latest_scores
"""

import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING, IndexModel
from pymongo.collection import Collection

from database.connection import get_collection

logger = logging.getLogger(__name__)

# =============================================================================
# Collection Name Constants
# =============================================================================

STOCKS_UNIVERSE: str = "stocks_universe"
OI_BASELINE: str = "oi_baseline"
WATCHLIST: str = "watchlist"
LIVE_SCORES: str = "live_scores"
ALERTS: str = "alerts"
RISK_TRACKER: str = "risk_tracker"


# =============================================================================
# Index Setup (idempotent)
# =============================================================================

def setup_indexes() -> None:
    """
    Create all required indexes across every collection.

    This function is idempotent – calling it multiple times is safe.
    pymongo's ``create_indexes`` will skip indexes that already exist.
    """
    logger.info("Setting up MongoDB indexes …")

    # ── stocks_universe ─────────────────────────────────────────────────
    _coll(STOCKS_UNIVERSE).create_indexes([
        IndexModel(
            [("symbol", ASCENDING)],
            unique=True,
            name="idx_symbol_unique",
        ),
    ])
    logger.debug("Indexes created for %s", STOCKS_UNIVERSE)

    # ── oi_baseline ─────────────────────────────────────────────────────
    _coll(OI_BASELINE).create_indexes([
        IndexModel(
            [("symbol", ASCENDING), ("strike", ASCENDING), ("snapshot_time", ASCENDING)],
            unique=False,
            name="idx_symbol_strike_time",
        ),
        IndexModel(
            [("symbol", ASCENDING), ("snapshot_time", DESCENDING)],
            name="idx_symbol_time_desc",
        ),
    ])
    logger.debug("Indexes created for %s", OI_BASELINE)

    # ── watchlist ───────────────────────────────────────────────────────
    _coll(WATCHLIST).create_indexes([
        IndexModel(
            [("symbol", ASCENDING), ("date", ASCENDING)],
            unique=True,
            name="idx_symbol_date",
        ),
        IndexModel(
            [("date", ASCENDING), ("active", ASCENDING)],
            name="idx_date_active",
        ),
    ])
    logger.debug("Indexes created for %s", WATCHLIST)

    # ── live_scores ─────────────────────────────────────────────────────
    _coll(LIVE_SCORES).create_indexes([
        IndexModel(
            [("symbol", ASCENDING), ("timestamp", DESCENDING)],
            name="idx_symbol_ts",
        ),
        IndexModel(
            [("timestamp", DESCENDING)],
            name="idx_ts_desc",
        ),
    ])
    logger.debug("Indexes created for %s", LIVE_SCORES)

    # ── alerts ──────────────────────────────────────────────────────────
    _coll(ALERTS).create_indexes([
        IndexModel(
            [("symbol", ASCENDING), ("triggered_at", DESCENDING)],
            name="idx_symbol_triggered",
        ),
        IndexModel(
            [("triggered_at", DESCENDING)],
            name="idx_triggered_desc",
        ),
    ])
    logger.debug("Indexes created for %s", ALERTS)

    # ── risk_tracker ────────────────────────────────────────────────────
    _coll(RISK_TRACKER).create_indexes([
        IndexModel(
            [("date", ASCENDING)],
            unique=True,
            name="idx_date_unique",
        ),
    ])
    logger.debug("Indexes created for %s", RISK_TRACKER)

    logger.info("All MongoDB indexes are up to date.")


# =============================================================================
# Private Helpers
# =============================================================================

def _coll(name: str) -> Collection:
    """Thin wrapper to keep call-sites tidy."""
    return get_collection(name)


def _today_str() -> str:
    """Return today's date in ``YYYY-MM-DD`` format (IST-aware via caller)."""
    return date.today().isoformat()


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


# =============================================================================
# stocks_universe Helpers
# =============================================================================

def upsert_stock(data: dict[str, Any]) -> None:
    """
    Insert or update a stock in the universe collection.

    ``data`` must contain a ``symbol`` key.  All other fields are merged
    via ``$set`` so partial updates are supported.

    Args:
        data: Stock metadata dict.  Must include ``"symbol"``.
    """
    symbol = data["symbol"]
    data["updated_at"] = _utcnow()
    _coll(STOCKS_UNIVERSE).update_one(
        {"symbol": symbol},
        {"$set": data},
        upsert=True,
    )
    logger.debug("Upserted stock: %s", symbol)


def get_universe() -> list[dict[str, Any]]:
    """
    Return all stocks in the universe collection.

    Returns:
        List of stock metadata dicts (``_id`` field excluded).
    """
    return list(
        _coll(STOCKS_UNIVERSE).find({}, {"_id": 0})
    )


# =============================================================================
# oi_baseline Helpers
# =============================================================================

def save_oi_baseline(data: dict[str, Any]) -> None:
    """
    Persist an OI baseline snapshot.

    Args:
        data: Must include ``symbol``, ``strike``, ``snapshot_time``.
    """
    data.setdefault("created_at", _utcnow())
    _coll(OI_BASELINE).insert_one(data)
    logger.debug(
        "Saved OI baseline: %s strike=%s @ %s",
        data.get("symbol"),
        data.get("strike"),
        data.get("snapshot_time"),
    )


def get_oi_baseline(
    symbol: str,
    snapshot_time: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """
    Retrieve OI baseline snapshots for a symbol.

    If ``snapshot_time`` is provided, return only those matching that exact
    timestamp.  Otherwise return the most recent set of snapshots (all
    strikes for the latest ``snapshot_time``).

    Args:
        symbol: Stock symbol (e.g. ``"ICICIBANK"``).
        snapshot_time: Optional exact snapshot timestamp.

    Returns:
        List of OI baseline documents (``_id`` excluded).
    """
    query: dict[str, Any] = {"symbol": symbol}

    if snapshot_time is not None:
        query["snapshot_time"] = snapshot_time
        return list(_coll(OI_BASELINE).find(query, {"_id": 0}))

    # Find the latest snapshot_time for this symbol
    latest = _coll(OI_BASELINE).find_one(
        {"symbol": symbol},
        sort=[("snapshot_time", DESCENDING)],
    )
    if latest is None:
        return []

    query["snapshot_time"] = latest["snapshot_time"]
    return list(_coll(OI_BASELINE).find(query, {"_id": 0}))


# =============================================================================
# watchlist Helpers
# =============================================================================

def save_watchlist(data: dict[str, Any]) -> None:
    """
    Add or update a stock on the watchlist for a specific date.

    Args:
        data: Must include ``symbol`` and ``date`` (ISO string ``YYYY-MM-DD``).
    """
    data.setdefault("active", True)
    data["updated_at"] = _utcnow()
    _coll(WATCHLIST).update_one(
        {"symbol": data["symbol"], "date": data["date"]},
        {"$set": data},
        upsert=True,
    )
    logger.debug("Watchlist upserted: %s on %s", data["symbol"], data["date"])


def get_active_watchlist(target_date: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Return all active watchlist entries for a given date.

    Args:
        target_date: ISO date string (``YYYY-MM-DD``).  Defaults to today.

    Returns:
        List of watchlist documents (``_id`` excluded).
    """
    if target_date is None:
        target_date = _today_str()

    return list(
        _coll(WATCHLIST).find(
            {"date": target_date, "active": True},
            {"_id": 0},
        )
    )


# =============================================================================
# live_scores Helpers
# =============================================================================

def save_live_score(data: dict[str, Any]) -> None:
    """
    Persist a computed live score snapshot.

    Args:
        data: Must include ``symbol`` and ``timestamp``.
    """
    data.setdefault("timestamp", _utcnow())
    _coll(LIVE_SCORES).insert_one(data)
    logger.debug("Saved live score: %s @ %s", data.get("symbol"), data.get("timestamp"))


def get_latest_scores(limit: int = 50) -> list[dict[str, Any]]:
    """
    Return the most recent score documents across all symbols.

    For each symbol, only the latest score is returned.  Results are sorted
    by ``total_score`` descending so the best opportunities appear first.

    Args:
        limit: Maximum number of symbols to return.

    Returns:
        List of score documents (``_id`` excluded).
    """
    pipeline = [
        {"$sort": {"timestamp": DESCENDING}},
        {
            "$group": {
                "_id": "$symbol",
                "doc": {"$first": "$$ROOT"},
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}},
        {
            "$lookup": {
                "from": STOCKS_UNIVERSE,
                "localField": "symbol",
                "foreignField": "symbol",
                "as": "universe_info"
            }
        },
        {
            "$addFields": {
                "liquidity_tier": {"$arrayElemAt": ["$universe_info.liquidity_tier", 0]},
                "index_name": {"$arrayElemAt": ["$universe_info.index", 0]}
            }
        },
        {"$sort": {"total_score": DESCENDING, "liquidity_tier": ASCENDING}},
        {"$limit": limit},
        {"$project": {"_id": 0, "universe_info": 0}},
    ]
    return list(_coll(LIVE_SCORES).aggregate(pipeline))


# =============================================================================
# alerts Helpers
# =============================================================================

def save_alert(data: dict[str, Any]) -> None:
    """
    Persist an alert (threshold breach, entry signal, risk warning, etc.).

    Args:
        data: Must include ``symbol``.  ``triggered_at`` defaults to now.
    """
    data.setdefault("triggered_at", _utcnow())
    data.setdefault("acknowledged", False)
    _coll(ALERTS).insert_one(data)
    logger.info("Alert saved: %s – %s", data.get("symbol"), data.get("message", ""))


def get_alerts_today(target_date: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Return all alerts triggered today (UTC day boundary).

    Args:
        target_date: ISO date string.  Defaults to today.

    Returns:
        List of alert documents (``_id`` excluded), newest first.
    """
    if target_date is None:
        target_date = _today_str()

    day_start = datetime.fromisoformat(f"{target_date}T00:00:00+00:00")
    day_end = datetime.fromisoformat(f"{target_date}T23:59:59+00:00")

    return list(
        _coll(ALERTS).find(
            {"triggered_at": {"$gte": day_start, "$lte": day_end}},
            {"_id": 0},
        ).sort("triggered_at", DESCENDING)
    )


# =============================================================================
# risk_tracker Helpers
# =============================================================================

def get_risk_tracker(target_date: Optional[str] = None) -> Optional[dict[str, Any]]:
    """
    Retrieve the risk tracker document for a specific date.

    The risk tracker stores daily P&L, trade count, consecutive losses, and
    whether the daily loss limit has been breached.

    Args:
        target_date: ISO date string.  Defaults to today.

    Returns:
        Risk tracker document (``_id`` excluded), or ``None`` if not found.
    """
    if target_date is None:
        target_date = _today_str()

    doc = _coll(RISK_TRACKER).find_one({"date": target_date}, {"_id": 0})
    return doc


def update_risk_tracker(
    target_date: Optional[str] = None,
    updates: Optional[dict[str, Any]] = None,
) -> None:
    """
    Upsert the risk tracker for a given date.

    If the document doesn't exist yet it is created with sensible defaults
    (zero P&L, zero trades, etc.) and then the supplied ``updates`` are
    merged in.

    Args:
        target_date: ISO date string.  Defaults to today.
        updates: Fields to ``$set`` on the risk tracker document.
    """
    if target_date is None:
        target_date = _today_str()
    if updates is None:
        updates = {}

    defaults = {
        "date": target_date,
        "total_pnl": 0.0,
        "trade_count": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "consecutive_losses": 0,
        "daily_limit_breached": False,
        "created_at": _utcnow(),
    }

    # Merge caller updates on top of defaults for the $setOnInsert path
    set_fields = {**updates, "updated_at": _utcnow()}

    _coll(RISK_TRACKER).update_one(
        {"date": target_date},
        {
            "$setOnInsert": defaults,
            "$set": set_fields,
        },
        upsert=True,
    )
    logger.debug("Risk tracker updated for %s: %s", target_date, set_fields)
