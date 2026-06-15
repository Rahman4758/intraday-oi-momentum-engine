"""
Database package for the Institutional Momentum Trading System.

Exports:
    get_db         – Returns the pymongo Database instance.
    get_collection – Returns a specific collection by name.
    check_health   – Verifies MongoDB connectivity.
"""

from database.connection import get_db, get_collection, check_health

__all__ = ["get_db", "get_collection", "check_health"]
