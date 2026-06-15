"""
Space Scorer — 15 Points Maximum.

Evaluates how much upside room remains before the stock hits resistance.
Uses ATR-based distance, Max Pain analysis, confluence detection,
and rejection pattern penalties.
"""

import logging
from typing import Optional

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    SPACE_MAX_SCORE,
    SPACE_ATR_MAX_SCORE,
    SPACE_MAXPAIN_MAX_SCORE,
    SPACE_CONFLUENCE_BONUS,
    SPACE_REJECTION_PENALTY,
    SPACE_ATR_FULL_THRESHOLD,
    SPACE_ATR_PARTIAL_THRESHOLD,
    SPACE_ATR_FULL_SCORE,
    SPACE_ATR_PARTIAL_SCORE,
    SPACE_MAXPAIN_WEIGHT_EXPIRY_DAY,
    SPACE_MAXPAIN_WEIGHT_1DAY,
    SPACE_MAXPAIN_WEIGHT_2_3DAYS,
    SPACE_MAXPAIN_WEIGHT_DEFAULT,
    SPACE_CONFLUENCE_TOLERANCE_PCT,
    SPACE_REJECTION_PROXIMITY_PCT,
)

logger = logging.getLogger(__name__)


class SpaceScorer(BaseScorer):
    """Scores stocks based on available upside space to resistance.

    Evaluates:
    - ATR-based distance to resistance (10 pts)
    - Max Pain positioning relative to current price (up to 6 pts)
    - Confluence bonus when resistance ≈ Max Pain (4 pts)
    - Rejection penalty for failed resistance tests (-5 pts)
    """

    def _detect_oi_resistance_support(
        self, option_chain: list
    ) -> tuple[Optional[float], Optional[float]]:
        """Find OI-based resistance (heaviest Call OI) and support (heaviest Put OI).

        Args:
            option_chain: List of strike dicts with call_oi and put_oi.

        Returns:
            Tuple of (oi_resistance_strike, oi_support_strike).
        """
        if not option_chain:
            return None, None

        # Heaviest Call OI strike → resistance
        max_call_strike = max(option_chain, key=lambda s: s.get("call_oi", 0))
        oi_resistance = max_call_strike["strike_price"] if max_call_strike.get("call_oi", 0) > 0 else None

        # Heaviest Put OI strike → support
        max_put_strike = max(option_chain, key=lambda s: s.get("put_oi", 0))
        oi_support = max_put_strike["strike_price"] if max_put_strike.get("put_oi", 0) > 0 else None

        return oi_resistance, oi_support

    def _get_effective_resistance(
        self,
        current_price: float,
        oi_resistance: Optional[float],
        day_high: float,
        resistance_price_input: float,
    ) -> tuple[float, str]:
        """Determine the nearest resistance above current price.

        Considers OI-based resistance, day high, and any explicitly
        provided resistance. Returns the nearest one above current price.

        Args:
            current_price: Current stock price.
            oi_resistance: OI-derived resistance strike.
            day_high: Today's high price.
            resistance_price_input: Explicitly provided resistance price.

        Returns:
            Tuple of (resistance_price, resistance_type).
        """
        candidates: list[tuple[float, str]] = []

        if oi_resistance is not None and oi_resistance > current_price:
            candidates.append((oi_resistance, "oi_call"))

        if day_high > current_price:
            candidates.append((day_high, "day_high"))

        if resistance_price_input > 0 and resistance_price_input > current_price:
            candidates.append((resistance_price_input, "provided"))

        if not candidates:
            # If no resistance found above, use the closest one
            fallback_candidates: list[tuple[float, str]] = []
            if oi_resistance is not None:
                fallback_candidates.append((oi_resistance, "oi_call"))
            if day_high > 0:
                fallback_candidates.append((day_high, "day_high"))
            if resistance_price_input > 0:
                fallback_candidates.append((resistance_price_input, "provided"))

            if fallback_candidates:
                return min(fallback_candidates, key=lambda c: abs(c[0] - current_price))
            return current_price, "none"

        # Return the nearest resistance above current price
        return min(candidates, key=lambda c: c[0] - current_price)

    def _get_effective_support(
        self,
        current_price: float,
        oi_support: Optional[float],
        day_low: float,
        support_price_input: float,
    ) -> tuple[float, str]:
        """Determine the nearest support below current price.

        Args:
            current_price: Current stock price.
            oi_support: OI-derived support strike.
            day_low: Today's low price.
            support_price_input: Explicitly provided support price.

        Returns:
            Tuple of (support_price, support_type).
        """
        candidates: list[tuple[float, str]] = []

        if oi_support is not None and oi_support < current_price:
            candidates.append((oi_support, "oi_put"))

        if day_low > 0 and day_low < current_price:
            candidates.append((day_low, "day_low"))

        if support_price_input > 0 and support_price_input < current_price:
            candidates.append((support_price_input, "provided"))

        if not candidates:
            return current_price, "none"

        # Nearest support below → highest value below current price
        return max(candidates, key=lambda c: c[0])

    def _get_max_pain_weight(self, days_to_expiry: int) -> float:
        """Get Max Pain weight based on days to expiry.

        Args:
            days_to_expiry: Number of trading days to expiry.

        Returns:
            Weight multiplier for Max Pain score (0.25–1.0).
        """
        if days_to_expiry <= 0:
            return SPACE_MAXPAIN_WEIGHT_EXPIRY_DAY
        elif days_to_expiry == 1:
            return SPACE_MAXPAIN_WEIGHT_1DAY
        elif days_to_expiry <= 3:
            return SPACE_MAXPAIN_WEIGHT_2_3DAYS
        else:
            return SPACE_MAXPAIN_WEIGHT_DEFAULT

    def _detect_rejection(
        self,
        recent_candles: list[dict],
        resistance_price: float,
    ) -> bool:
        """Detect rejection pattern near resistance.

        A rejection is identified when:
        1. Stock tested resistance (got within 0.3% of resistance)
        2. Came back down
        3. Formed lower high (current high < previous high in window)

        Args:
            recent_candles: List of recent 30-min candle dicts (chronological).
            resistance_price: The resistance price to check against.

        Returns:
            True if rejection pattern detected.
        """
        if not recent_candles or len(recent_candles) < 2 or resistance_price <= 0:
            return False

        proximity_threshold = resistance_price * (SPACE_REJECTION_PROXIMITY_PCT / 100.0)

        # Check if any candle tested resistance
        tested_resistance = False
        for candle in recent_candles:
            candle_high = candle.get("high", 0.0)
            if abs(candle_high - resistance_price) <= proximity_threshold:
                tested_resistance = True
                break

        if not tested_resistance:
            return False

        # Check for lower high formation: latest high < previous high
        latest_candle = recent_candles[-1]
        previous_candle = recent_candles[-2]

        latest_high = latest_candle.get("high", 0.0)
        previous_high = previous_candle.get("high", 0.0)

        # Also check that current close came back down from resistance
        latest_close = latest_candle.get("close", 0.0)
        came_back_down = latest_close < resistance_price

        if latest_high < previous_high and came_back_down:
            return True

        return False

    def calculate(self, symbol: str, data: dict) -> ScoreResult:
        """Calculate Space score for a symbol.

        Args:
            symbol: Stock ticker symbol.
            data: Dict with keys:
                - current_price: float
                - atr: float
                - resistance_price: float
                - support_price: float
                - day_high: float
                - day_low: float
                - max_pain: float
                - days_to_expiry: int
                - option_chain: list
                - recent_candles_30min: list
        """
        logger.info("Calculating Space score for %s", symbol)

        current_price: float = data.get("current_price", 0.0)
        atr: float = data.get("atr", 0.0)
        resistance_price_input: float = data.get("resistance_price", 0.0)
        support_price_input: float = data.get("support_price", 0.0)
        day_high: float = data.get("day_high", 0.0)
        day_low: float = data.get("day_low", 0.0)
        max_pain: float = data.get("max_pain", 0.0)
        days_to_expiry: int = data.get("days_to_expiry", 7)
        option_chain: list = data.get("option_chain", [])
        recent_candles: list = data.get("recent_candles_30min", [])

        auto_skip = False
        skip_reasons: list[str] = []

        # -----------------------------------------------------------
        # Detect OI-based resistance and support
        # -----------------------------------------------------------
        oi_resistance, oi_support = self._detect_oi_resistance_support(option_chain)

        resistance_price, resistance_type = self._get_effective_resistance(
            current_price, oi_resistance, day_high, resistance_price_input,
        )
        support_price, support_type = self._get_effective_support(
            current_price, oi_support, day_low, support_price_input,
        )

        # -----------------------------------------------------------
        # ATR-Based Resistance Distance (10 pts)
        # -----------------------------------------------------------
        atr_score: float = 0.0
        distance = resistance_price - current_price
        distance_atr_ratio = distance / atr if atr > 0 else 0.0

        if distance_atr_ratio > SPACE_ATR_FULL_THRESHOLD:
            atr_score = SPACE_ATR_FULL_SCORE
        elif distance_atr_ratio >= SPACE_ATR_PARTIAL_THRESHOLD:
            atr_score = SPACE_ATR_PARTIAL_SCORE
        else:
            atr_score = 0.0
            auto_skip = True
            skip_reasons.append(
                f"Resistance too close: {distance_atr_ratio:.2f}x ATR "
                f"(need >= {SPACE_ATR_PARTIAL_THRESHOLD}x)"
            )

        # -----------------------------------------------------------
        # Max Pain Score (up to 6 pts, dynamically weighted)
        # -----------------------------------------------------------
        max_pain_weight = self._get_max_pain_weight(days_to_expiry)
        max_pain_score: float = 0.0

        if max_pain > 0:
            if max_pain > current_price:
                max_pain_score = SPACE_MAXPAIN_MAX_SCORE * max_pain_weight
            else:
                auto_skip = True
                skip_reasons.append(
                    f"Max Pain ₹{max_pain:.2f} below current price ₹{current_price:.2f}"
                )

        # -----------------------------------------------------------
        # Confluence Bonus (4 pts)
        # -----------------------------------------------------------
        confluence = False
        confluence_score: float = 0.0

        if resistance_price > 0 and max_pain > 0:
            pct_diff = abs(resistance_price - max_pain) / resistance_price * 100
            if pct_diff <= SPACE_CONFLUENCE_TOLERANCE_PCT:
                confluence = True
                confluence_score = SPACE_CONFLUENCE_BONUS

        # -----------------------------------------------------------
        # Rejection Penalty (-5 pts)
        # -----------------------------------------------------------
        rejection = self._detect_rejection(recent_candles, resistance_price)
        rejection_score: float = SPACE_REJECTION_PENALTY if rejection else 0.0

        # -----------------------------------------------------------
        # Total Score
        # -----------------------------------------------------------
        total_score = atr_score + max_pain_score + confluence_score + rejection_score
        # Clamp to [0, max] — penalties can reduce but not go negative
        total_score = max(0.0, min(total_score, SPACE_MAX_SCORE))

        skip_reason: str | None = "; ".join(skip_reasons) if skip_reasons else None

        details = {
            "resistance_price": round(resistance_price, 2),
            "resistance_type": resistance_type,
            "support_price": round(support_price, 2),
            "support_type": support_type,
            "distance_atr_ratio": round(distance_atr_ratio, 4),
            "max_pain_value": round(max_pain, 2),
            "max_pain_weight": round(max_pain_weight, 2),
            "confluence": confluence,
            "rejection": rejection,
            "atr": round(atr, 2),
            "atr_score": round(atr_score, 2),
            "max_pain_score": round(max_pain_score, 2),
            "confluence_score": round(confluence_score, 2),
            "rejection_score": round(rejection_score, 2),
            "days_to_expiry": days_to_expiry,
        }

        logger.info(
            "Space score for %s: %.1f/%.1f (dist_atr=%.2f, maxpain=%.1f, "
            "confluence=%s, rejection=%s, skip=%s)",
            symbol, total_score, SPACE_MAX_SCORE, distance_atr_ratio,
            max_pain_score, confluence, rejection, auto_skip,
        )

        return ScoreResult(
            score=total_score,
            max_score=SPACE_MAX_SCORE,
            details=details,
            auto_skip=auto_skip,
            skip_reason=skip_reason,
        )
