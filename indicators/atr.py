"""
Average True Range (ATR) indicator — Wilder's smoothing implementation.

ATR measures market volatility by decomposing the entire range of a bar
(including any gaps from the previous close).  It is used for position sizing
and stop-loss placement.
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def calculate_atr(candles_df: pd.DataFrame, period: int = 14) -> float:
    """
    Compute the latest ATR value using Wilder's smoothing.

    True Range for each bar is defined as::

        TR = max(High − Low, |High − PrevClose|, |Low − PrevClose|)

    ATR is the Wilder-smoothed moving average of TR over *period* bars.

    Parameters
    ----------
    candles_df : pd.DataFrame
        Daily (or any timeframe) OHLC data with columns ``high``, ``low``,
        ``close``.  At least ``period + 1`` rows are required (the first row
        cannot produce a TR because there is no previous close).
    period : int, optional
        Smoothing period (default 14).

    Returns
    -------
    float
        The most recent ATR value.  Returns ``NaN`` when insufficient data.

    Raises
    ------
    ValueError
        If required columns are missing.
    """
    required_cols = {"high", "low", "close"}
    missing = required_cols - set(candles_df.columns)
    if missing:
        raise ValueError(f"candles_df is missing required columns: {missing}")

    if len(candles_df) < period + 1:
        logger.warning(
            "Not enough data for ATR (need >= %d rows, got %d).",
            period + 1,
            len(candles_df),
        )
        return float("nan")

    high = candles_df["high"].values.astype(np.float64)
    low = candles_df["low"].values.astype(np.float64)
    close = candles_df["close"].values.astype(np.float64)

    n = len(high)

    # ── True Range series (index 0 has no previous close → skip) ────────
    tr = np.zeros(n - 1, dtype=np.float64)
    for i in range(1, n):
        hl = high[i] - low[i]
        hc = abs(high[i] - close[i - 1])
        lc = abs(low[i] - close[i - 1])
        tr[i - 1] = max(hl, hc, lc)

    if len(tr) < period:
        logger.warning(
            "True Range series too short for ATR smoothing "
            "(need >= %d, got %d).",
            period,
            len(tr),
        )
        return float("nan")

    # ── Wilder's smoothing ──────────────────────────────────────────────
    # Seed: simple average of first `period` TRs
    atr_values = np.full(len(tr), np.nan, dtype=np.float64)
    atr_values[period - 1] = np.mean(tr[:period])

    for i in range(period, len(tr)):
        atr_values[i] = (
            atr_values[i - 1] * (period - 1) + tr[i]
        ) / period

    # The last non-NaN entry is the current ATR
    valid = atr_values[~np.isnan(atr_values)]
    if len(valid) == 0:
        logger.warning("ATR calculation produced no valid values.")
        return float("nan")

    atr_value = float(valid[-1])
    logger.debug("ATR(%d) calculated: %.2f", period, atr_value)
    return atr_value
