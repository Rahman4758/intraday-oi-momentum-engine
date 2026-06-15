"""
Max-Pain (option pain) indicator and expiry-based weighting.

Max Pain is the strike price at which the total **intrinsic-value pain** for
all outstanding option holders is minimised.  Market makers (who are net short
options) benefit most when the underlying settles at max-pain, so it acts as
a gravitational anchor — especially close to expiry.
"""

import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


def calculate_max_pain(option_chain: List[Dict]) -> float:
    """
    Find the strike with the *minimum* aggregate pain across all strikes.

    Algorithm
    ---------
    For each candidate settlement price *S* (every strike in the chain):

    .. code-block:: text

        Total Pain(S) = Σ over all strikes K of:
            Call Pain = max(0, S − K) × call_OI(K)
          + Put Pain  = max(0, K − S) × put_OI(K)

    Max Pain = argmin_S { Total Pain(S) }

    Parameters
    ----------
    option_chain : list[dict]
        Each dict **must** have:
        - ``strike_price`` (float)
        - ``call_oi`` (int/float)
        - ``put_oi`` (int/float)

    Returns
    -------
    float
        The strike price with the lowest total pain.
        Returns ``NaN`` if the chain is empty or invalid.

    Raises
    ------
    ValueError
        If any entry is missing required keys.
    """
    if not option_chain:
        logger.warning("Empty option chain provided; returning NaN.")
        return float("nan")

    # Validate & extract data
    strikes: list[float] = []
    call_ois: list[float] = []
    put_ois: list[float] = []

    for idx, entry in enumerate(option_chain):
        for key in ("strike_price", "call_oi", "put_oi"):
            if key not in entry:
                raise ValueError(
                    f"option_chain[{idx}] is missing required key '{key}'. "
                    f"Got keys: {list(entry.keys())}"
                )
        strikes.append(float(entry["strike_price"]))
        call_ois.append(float(entry["call_oi"]))
        put_ois.append(float(entry["put_oi"]))

    if not strikes:
        logger.warning("No valid strikes in option chain; returning NaN.")
        return float("nan")

    # ── Compute total pain for each candidate settlement strike ─────────
    min_pain = float("inf")
    max_pain_strike = float("nan")

    for candidate in strikes:
        total_pain = 0.0
        for k, c_oi, p_oi in zip(strikes, call_ois, put_ois):
            # Pain to call holders if underlying settles at `candidate`
            call_pain = max(0.0, candidate - k) * c_oi
            # Pain to put holders
            put_pain = max(0.0, k - candidate) * p_oi
            total_pain += call_pain + put_pain

        if total_pain < min_pain:
            min_pain = total_pain
            max_pain_strike = candidate

    logger.debug(
        "Max-pain strike: %.2f  (min total pain: %.0f, %d strikes evaluated)",
        max_pain_strike,
        min_pain,
        len(strikes),
    )
    return float(max_pain_strike)


def get_max_pain_weight(days_to_expiry: int) -> float:
    """
    Dynamic weighting factor based on proximity to option expiry.

    The closer the expiry, the stronger the gravitational pull of max-pain
    on the underlying price.

    Mapping
    -------
    +-----------------------+--------+
    | Days to Expiry        | Weight |
    +=======================+========+
    | 0 (expiry day)        |  1.00  |
    | 1                     |  0.75  |
    | 2 – 3                 |  0.50  |
    | 4+                    |  0.25  |
    +-----------------------+--------+

    Parameters
    ----------
    days_to_expiry : int
        Calendar days remaining until the option contract expires.
        Negative values (past expiry) are treated as 0.

    Returns
    -------
    float
        Weight in the range [0.25, 1.0].
    """
    if days_to_expiry <= 0:
        weight = 1.0
    elif days_to_expiry == 1:
        weight = 0.75
    elif days_to_expiry <= 3:
        weight = 0.50
    else:
        weight = 0.25

    logger.debug(
        "Max-pain weight for %d days to expiry: %.2f",
        days_to_expiry,
        weight,
    )
    return weight
