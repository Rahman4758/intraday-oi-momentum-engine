"""
Relative Strength Scorer — 15 Points Maximum.

Compares a stock's intraday performance against its sector index
and Nifty 50 to identify relative leaders.
"""

import logging

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    RS_MAX_SCORE,
    RS_LEADER_SCORE,
    RS_PARTIAL_SCORE,
)

logger = logging.getLogger(__name__)


class RSScorer(BaseScorer):
    """Scores stocks based on relative strength vs sector and market.

    Tiers:
    - Leader: Stock > Sector > Nifty → 15 pts
    - Partial: Stock > Nifty but < Sector → 7 pts
    - Laggard: Stock < Sector OR < Nifty → 0 pts
    """

    def calculate(self, symbol: str, data: dict, bias: str = "LONG") -> ScoreResult:
        """Calculate Relative Strength score for a symbol.

        Args:
            symbol: Stock ticker symbol.
            data: Dict with keys:
                - stock_change_pct: float (today's % change)
                - sector_index_change_pct: float
                - nifty_change_pct: float
        """
        logger.info("Calculating RS score for %s", symbol)

        stock_change: float = data.get("stock_change_pct", 0.0)
        sector_change: float = data.get("sector_index_change_pct", 0.0)
        nifty_change: float = data.get("nifty_change_pct", 0.0)

        score: float = 0.0
        strength_category: str = "laggard"

        if bias == "LONG":
            if stock_change > sector_change and sector_change > nifty_change:
                # Stock is leading both sector and market
                score = RS_LEADER_SCORE
                strength_category = "leader"
            elif stock_change > nifty_change and stock_change <= sector_change:
                # Stock beats Nifty but not its sector
                score = RS_PARTIAL_SCORE
                strength_category = "partial"
            else:
                # Stock underperforming either sector or Nifty
                score = 0.0
                strength_category = "laggard"
        elif bias == "SHORT":
            if stock_change < sector_change and sector_change < nifty_change:
                # Stock is weaker than both sector and market
                score = RS_LEADER_SCORE
                strength_category = "weakest"
            elif stock_change < nifty_change and stock_change >= sector_change:
                # Stock is weaker than Nifty but not sector
                score = RS_PARTIAL_SCORE
                strength_category = "partial_weak"
            else:
                score = 0.0
                strength_category = "strong"

        score = max(0.0, min(score, RS_MAX_SCORE))

        details = {
            "stock_change": round(stock_change, 4),
            "sector_change": round(sector_change, 4),
            "nifty_change": round(nifty_change, 4),
            "strength_category": strength_category,
        }

        logger.info(
            "RS score for %s: %.1f/%.1f (stock=%.2f%%, sector=%.2f%%, "
            "nifty=%.2f%%, category=%s)",
            symbol, score, RS_MAX_SCORE, stock_change,
            sector_change, nifty_change, strength_category,
        )

        return ScoreResult(
            score=score,
            max_score=RS_MAX_SCORE,
            details=details,
            auto_skip=False,
            skip_reason=None,
        )
