"""
Relative Volume (RVOL) indicator.

RVOL compares the volume traded *so far today* against the historical average
for the same elapsed time window, answering: "Is this stock trading heavier or
lighter than usual right now?"

A value of 2.3 means the stock has traded 2.3× its normal volume for this
point in the session.
"""

import logging
from typing import List, Tuple, Union

logger = logging.getLogger(__name__)

# Total minutes in an NSE equity session: 09:15 → 15:30 = 375 minutes
FULL_SESSION_MINUTES: int = 375


def calculate_rvol(
    current_volume: int,
    historical_volumes: List[Union[Tuple[int, int], int]],
    current_minutes_elapsed: int,
) -> float:
    """
    Compute the Relative Volume ratio for the current session.

    Formula
    -------
    ::

        expected_volume = mean(
            day_vol × (minutes_elapsed / total_session_minutes)
            for each of the last 20 trading days
        )

        RVOL = current_volume / expected_volume

    Parameters
    ----------
    current_volume : int
        Total volume traded today up to now.
    historical_volumes : list
        Volume references for the last *N* trading days (ideally 20).
        Each element is **either**:

        * A ``(total_day_volume, minutes_in_day)`` tuple — the second
          value is typically 375 for a full session but may be shorter on
          truncated days.
        * A plain ``int`` total-day volume — ``minutes_in_day`` defaults
          to 375.
    current_minutes_elapsed : int
        Minutes elapsed since 09:15 AM IST today.

    Returns
    -------
    float
        RVOL ratio (e.g. 2.3 means 2.3× normal volume).
        Returns ``0.0`` if expected volume is zero or inputs are invalid.

    Notes
    -----
    * If ``current_minutes_elapsed`` exceeds ``FULL_SESSION_MINUTES`` it is
      clamped to 375 so that post-close calls don't inflate the ratio.
    * Days with zero volume in *historical_volumes* are silently excluded
      from the average to avoid skewing the result.
    """
    if current_minutes_elapsed <= 0:
        logger.warning(
            "current_minutes_elapsed is %d (≤ 0); returning RVOL 0.0.",
            current_minutes_elapsed,
        )
        return 0.0

    # Clamp elapsed minutes to full session length
    clamped_minutes = min(current_minutes_elapsed, FULL_SESSION_MINUTES)

    if not historical_volumes:
        logger.warning("No historical volume data provided; returning RVOL 0.0.")
        return 0.0

    # ── Compute expected volume for the same elapsed period each day ────
    prorated_volumes: list[float] = []
    for entry in historical_volumes:
        if isinstance(entry, (list, tuple)):
            day_vol, day_minutes = int(entry[0]), int(entry[1])
        else:
            day_vol = int(entry)
            day_minutes = FULL_SESSION_MINUTES

        if day_vol <= 0 or day_minutes <= 0:
            continue

        # Pro-rate: what portion of that day's volume would have occurred
        # in the first `clamped_minutes` minutes (linear interpolation)
        fraction = clamped_minutes / day_minutes
        prorated = day_vol * fraction
        prorated_volumes.append(prorated)

    if not prorated_volumes:
        logger.warning(
            "All historical volume entries are zero or invalid; "
            "returning RVOL 0.0."
        )
        return 0.0

    expected_volume = sum(prorated_volumes) / len(prorated_volumes)

    if expected_volume <= 0:
        logger.warning("Expected volume is zero; returning RVOL 0.0.")
        return 0.0

    rvol = current_volume / expected_volume
    logger.debug(
        "RVOL calculated: %.2f  (current=%d, expected=%.0f, elapsed=%d min)",
        rvol,
        current_volume,
        expected_volume,
        clamped_minutes,
    )
    return float(rvol)
