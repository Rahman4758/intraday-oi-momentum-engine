"""
MongoDB connection manager for the Institutional Momentum Trading System.

Uses pymongo's built-in connection pooling (default maxPoolSize=100).
A single MongoClient is lazily created on first access and reused for the
lifetime of the process.

Usage:
    from database.connection import get_db, get_collection, check_health

    db = get_db()
    coll = get_collection("live_scores")
    is_ok = check_health()
"""

import logging
from threading import Lock
from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Module-level singleton ──────────────────────────────────────────────────
_client: Optional[MongoClient] = None
_client_lock: Lock = Lock()


def _get_client() -> MongoClient:
    """
    Return the singleton MongoClient, creating it on first call.

    Thread-safe via a module-level lock.  pymongo's MongoClient is itself
    thread-safe and manages an internal connection pool, so sharing a
    single instance across threads is the recommended pattern.
    """
    global _client

    if _client is not None:
        return _client

    with _client_lock:
        # Double-checked locking
        if _client is not None:
            return _client

        logger.info(
            "Initialising MongoDB connection to %s (db=%s)",
            settings.MONGO_URI[:40] + "...",
            settings.MONGO_DB_NAME,
        )

        _client = MongoClient(
            settings.MONGO_URI,
            # Pool settings (pymongo defaults are fine for most cases)
            maxPoolSize=100,
            minPoolSize=5,
            # Wait up to 5 s when selecting a server
            serverSelectionTimeoutMS=5_000,
            # Socket-level timeouts
            connectTimeoutMS=10_000,
            socketTimeoutMS=30_000,
            # Retry on transient network errors
            retryWrites=True,
            retryReads=True,
        )
        logger.info("MongoDB client created successfully.")
        return _client


def get_db() -> Database:
    """
    Return the ``intraday_momentum`` Database object.

    The database name is read from ``settings.MONGO_DB_NAME`` and defaults
    to ``"intraday_momentum"``.
    """
    client = _get_client()
    return client[settings.MONGO_DB_NAME]


def get_collection(name: str) -> Collection:
    """
    Shortcut to retrieve a collection from the default database.

    Args:
        name: Collection name (e.g. ``"live_scores"``).

    Returns:
        pymongo Collection handle.
    """
    return get_db()[name]


def check_health() -> bool:
    """
    Verify that the MongoDB server is reachable.

    Sends a ``ping`` command to the admin database.  Returns ``True`` on
    success, ``False`` on failure (and logs the error).
    """
    try:
        client = _get_client()
        client.admin.command("ping")
        logger.info("MongoDB health check passed.")
        return True
    except (ConnectionFailure, ServerSelectionTimeoutError) as exc:
        logger.error("MongoDB health check FAILED: %s", exc)
        return False


def close_connection() -> None:
    """
    Gracefully close the MongoDB client.

    Should be called during application shutdown to release pooled
    connections.
    """
    global _client
    with _client_lock:
        if _client is not None:
            logger.info("Closing MongoDB connection.")
            _client.close()
            _client = None
