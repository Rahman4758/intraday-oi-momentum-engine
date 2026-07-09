"""
Market Scorer — 10 Points Maximum.

Evaluates broad market conditions via Nifty direction, India VIX level,
and index PCR trend. Acts as a market-regime gate that can auto-skip
all trades when conditions are hostile.
"""

import logging

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    MARKET_MAX_SCORE,
    MARKET_NIFTY_GREEN_SCORE,
    MARKET_VIX_LOW_SCORE,
    MARKET_PCR_RISING_SCORE,
    MARKET_VIX_LOW_THRESHOLD,
    MARKET_VIX_HIGH_THRESHOLD,
)

logger = logging.getLogger(__name__)


class MarketScorer(BaseScorer):
    """Scores the overall market environment for trade suitability.

    Components:
    - Nifty direction: positive change → 3 pts
    - VIX level: below 14 → 3 pts; above 16 → AUTO-SKIP
    - Index PCR trend: rising (today > yesterday) → 4 pts
    """

    def calculate(self, symbol: str, data: dict, bias: str = "LONG") -> ScoreResult:
        """Calculate Market score.

        Note: This scorer evaluates market conditions, not a specific
        symbol. The symbol parameter is included for interface consistency
        but the score applies globally.

        Args:
            symbol: Stock ticker symbol (for interface consistency).
            data: Dict with keys:
                - nifty_change_pct: float
                - vix_level: float
                - nifty_pcr_today: float
                - nifty_pcr_yesterday: float
        """
        logger.info("Calculating Market score (context: %s)", symbol)

        nifty_change: float = data.get("nifty_change_pct", 0.0)
        vix_level: float = data.get("vix_level", 0.0)
        nifty_pcr_today: float = data.get("nifty_pcr_today", 0.0)
        nifty_pcr_yesterday: float = data.get("nifty_pcr_yesterday", 0.0)

        auto_skip = False
        skip_reason: str | None = None

        # -----------------------------------------------------------
        # Nifty Direction (3 pts)
        # -----------------------------------------------------------
        nifty_green = nifty_change > 0
        nifty_direction = "green" if nifty_green else "red"
        
        nifty_score = 0.0
        if bias == "LONG" and nifty_green:
            nifty_score = MARKET_NIFTY_GREEN_SCORE
        elif bias == "SHORT" and not nifty_green:
            nifty_score = MARKET_NIFTY_GREEN_SCORE

        # -----------------------------------------------------------
        # VIX Level (3 pts)
        # -----------------------------------------------------------
        vix_score: float = 0.0
        vix_status: str = "normal"

        if vix_level < MARKET_VIX_LOW_THRESHOLD:
            vix_score = MARKET_VIX_LOW_SCORE
            vix_status = "low"
        elif vix_level > MARKET_VIX_HIGH_THRESHOLD:
            vix_score = 0.0
            vix_status = "high"
            auto_skip = True
            skip_reason = (
                f"VIX at {vix_level:.2f} exceeds {MARKET_VIX_HIGH_THRESHOLD} — "
                f"market too volatile for momentum trades"
            )
        else:
            vix_score = 0.0
            vix_status = "normal"

        # -----------------------------------------------------------
        # Index PCR Trend (4 pts)
        # -----------------------------------------------------------
        pcr_rising = nifty_pcr_today > nifty_pcr_yesterday
        pcr_score = 0.0
        
        if bias == "LONG" and pcr_rising:
            pcr_score = MARKET_PCR_RISING_SCORE
        elif bias == "SHORT" and not pcr_rising:
            pcr_score = MARKET_PCR_RISING_SCORE

        # -----------------------------------------------------------
        # Total Score
        # -----------------------------------------------------------
        total_score = nifty_score + vix_score + pcr_score
        total_score = max(0.0, min(total_score, MARKET_MAX_SCORE))

        details = {
            "nifty_direction": nifty_direction,
            "nifty_change_pct": round(nifty_change, 4),
            "vix_level": round(vix_level, 2),
            "vix_status": vix_status,
            "pcr_rising": pcr_rising,
            "nifty_pcr_today": round(nifty_pcr_today, 4),
            "nifty_pcr_yesterday": round(nifty_pcr_yesterday, 4),
            "nifty_score": round(nifty_score, 2),
            "vix_score": round(vix_score, 2),
            "pcr_score": round(pcr_score, 2),
        }

        logger.info(
            "Market score: %.1f/%.1f (Nifty=%s, VIX=%.1f/%s, PCR_rising=%s, skip=%s)",
            total_score, MARKET_MAX_SCORE, nifty_direction,
            vix_level, vix_status, pcr_rising, auto_skip,
        )

        return ScoreResult(
            score=total_score,
            max_score=MARKET_MAX_SCORE,
            details=details,
            auto_skip=auto_skip,
            skip_reason=skip_reason,
        )
