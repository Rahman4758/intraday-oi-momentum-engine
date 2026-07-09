"""
Volume-Weighted Average Price (VWAP) indicator.

VWAP anchors to the market open (09:15 IST) and accumulates throughout the
trading session.  Only *today's* candles are used; any historical rows are
silently discarded before the calculation begins.
"""

import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

logger = logging.getLogger(__name__)

IST = pytz.timezone("Asia/Kolkata")


def calculate_vwap(candles_df: pd.DataFrame) -> float:
    """
    Compute the running VWAP from intraday 1-minute candles.

    Formula
    -------
    Typical Price  = (High + Low + Close) / 3
    VWAP           = Σ(Typical Price × Volume) / Σ(Volume)

    Parameters
    ----------
    candles_df : pd.DataFrame
        Must contain columns ``high``, ``low``, ``close``, ``volume``.
        An optional ``timestamp`` column (datetime or ISO-8601 string) is
        used to filter for today's session only (starting 09:15 IST).
        If ``timestamp`` is absent every row is assumed to belong to the
        current session.

    Returns
    -------
    float
        The current VWAP value.  Returns ``NaN`` if no valid candles remain
        after filtering.

    Raises
    ------
    ValueError
        If any of the required columns are missing.
    """
    required_cols = {"high", "low", "close", "volume"}
    missing = required_cols - set(candles_df.columns)
    if missing:
        raise ValueError(f"candles_df is missing required columns: {missing}")

    df = candles_df.copy()

    # ── Filter to today's session (09:15 IST onward) ────────────────────
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        now_ist = datetime.now(IST)
        session_start = now_ist.replace(hour=9, minute=15, second=0, microsecond=0)
        # Keep only candles from today's session
        df = df[df["timestamp"] >= session_start]

    if df.empty:
        logger.warning("No candles available for VWAP calculation after filtering.")
        return float("nan")

    # ── Core calculation ────────────────────────────────────────────────
    typical_price = (df["high"].values + df["low"].values + df["close"].values) / 3.0
    volume = df["volume"].values.astype(np.float64)

    cumulative_tp_vol = np.sum(typical_price * volume)
    cumulative_vol = np.sum(volume)

    if cumulative_vol == 0:
        logger.warning("Total volume is zero; VWAP is undefined.")
        return float("nan")

    vwap = cumulative_tp_vol / cumulative_vol
    logger.debug("VWAP calculated: %.2f  (from %d candles)", vwap, len(df))
    return float(vwap)
