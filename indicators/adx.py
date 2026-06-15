"""
Average Directional Index (ADX) indicator — full Wilder's smoothing implementation.

The ADX quantifies trend *strength* (not direction).  Values above 25 are
generally considered indicative of a strong trend; below 20 suggests a
range-bound market.

All smoothing uses Wilder's method (exponential smoothing with
``alpha = 1 / period``), matching the original specification from
J. Welles Wilder's *New Concepts in Technical Trading Systems* (1978).
"""

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _wilders_smooth(values: np.ndarray, period: int) -> np.ndarray:
    """
    Apply Wilder's smoothing to a 1-D array.

    The first valid value is the simple average of the first ``period``
    elements.  Subsequent values use the recursive formula::

        smoothed[i] = smoothed[i-1] - (smoothed[i-1] / period) + values[i]

    which is equivalent to an EMA with ``alpha = 1 / period``.

    Parameters
    ----------
    values : np.ndarray
        Raw series to smooth (length >= ``period``).
    period : int
        Smoothing window.

    Returns
    -------
    np.ndarray
        Same length as *values*; the first ``period - 1`` entries are ``NaN``.
    """
    result = np.full_like(values, np.nan, dtype=np.float64)
    if len(values) < period:
        return result

    # Seed: simple mean of first `period` observations
    result[period - 1] = np.mean(values[:period])

    # Recursive Wilder's smoothing
    for i in range(period, len(values)):
        result[i] = result[i - 1] - (result[i - 1] / period) + values[i]

    return result


def calculate_adx(candles_df: pd.DataFrame, period: int = 14) -> float:
    """
    Compute the latest ADX value using Wilder's smoothing.

    Steps
    -----
    1. Compute +DM (positive directional movement) and −DM for each bar.
    2. Compute True Range (TR) for each bar.
    3. Apply Wilder's smoothing to +DM, −DM, and TR.
    4. Derive +DI = 100 × smoothed(+DM) / smoothed(TR)
       and   −DI = 100 × smoothed(−DM) / smoothed(TR).
    5. DX = 100 × |+DI − −DI| / (+DI + −DI).
    6. ADX = Wilder's smooth of DX over *period*.

    Parameters
    ----------
    candles_df : pd.DataFrame
        Must contain columns ``high``, ``low``, ``close`` with at least
        ``2 × period`` rows for a meaningful result.
    period : int, optional
        Smoothing period (default 14).

    Returns
    -------
    float
        The most recent ADX value.  Returns ``NaN`` when insufficient data.

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
            "Not enough data for ADX (need >= %d rows, got %d).",
            period + 1,
            len(candles_df),
        )
        return float("nan")

    high = candles_df["high"].values.astype(np.float64)
    low = candles_df["low"].values.astype(np.float64)
    close = candles_df["close"].values.astype(np.float64)

    n = len(high)

    # ── Step 1: Directional Movement ────────────────────────────────────
    plus_dm = np.zeros(n, dtype=np.float64)
    minus_dm = np.zeros(n, dtype=np.float64)

    for i in range(1, n):
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # ── Step 2: True Range ──────────────────────────────────────────────
    tr = np.zeros(n, dtype=np.float64)
    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )

    # ── Step 3: Wilder's smoothing of +DM, -DM, TR ─────────────────────
    # Skip index-0 (no prior bar), so work from index 1 onward
    smoothed_plus_dm = _wilders_smooth(plus_dm[1:], period)
    smoothed_minus_dm = _wilders_smooth(minus_dm[1:], period)
    smoothed_tr = _wilders_smooth(tr[1:], period)

    # ── Step 4: +DI and -DI ────────────────────────────────────────────
    length = len(smoothed_tr)
    plus_di = np.full(length, np.nan, dtype=np.float64)
    minus_di = np.full(length, np.nan, dtype=np.float64)

    for i in range(length):
        if not np.isnan(smoothed_tr[i]) and smoothed_tr[i] != 0:
            plus_di[i] = 100.0 * smoothed_plus_dm[i] / smoothed_tr[i]
            minus_di[i] = 100.0 * smoothed_minus_dm[i] / smoothed_tr[i]

    # ── Step 5: DX ─────────────────────────────────────────────────────
    dx = np.full(length, np.nan, dtype=np.float64)
    for i in range(length):
        if not np.isnan(plus_di[i]) and not np.isnan(minus_di[i]):
            di_sum = plus_di[i] + minus_di[i]
            if di_sum != 0:
                dx[i] = 100.0 * abs(plus_di[i] - minus_di[i]) / di_sum

    # ── Step 6: ADX = Wilder's smooth of DX ────────────────────────────
    # Find the first valid DX index for seeding
    valid_dx_indices = np.where(~np.isnan(dx))[0]
    if len(valid_dx_indices) < period:
        logger.warning("Not enough valid DX values for ADX smoothing.")
        return float("nan")

    first_valid = valid_dx_indices[0]
    dx_for_adx = dx[first_valid:]
    adx_series = _wilders_smooth(dx_for_adx, period)

    # Return the last non-NaN ADX value
    valid_adx = adx_series[~np.isnan(adx_series)]
    if len(valid_adx) == 0:
        logger.warning("ADX calculation produced no valid values.")
        return float("nan")

    adx_value = float(valid_adx[-1])
    logger.debug("ADX(%d) calculated: %.2f", period, adx_value)
    return adx_value
