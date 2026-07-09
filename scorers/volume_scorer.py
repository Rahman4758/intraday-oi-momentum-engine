"""
Volume Scorer — 15 Points Maximum.

Evaluates relative volume (RVOL) to detect institutional participation.
Auto-skips stocks with insufficient volume activity.
"""

import logging

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    VOLUME_MAX_SCORE,
    VOLUME_RVOL_HIGH_THRESHOLD,
    VOLUME_RVOL_HIGH_SCORE,
    VOLUME_RVOL_MED_THRESHOLD,
    VOLUME_RVOL_MED_SCORE,
)

logger = logging.getLogger(__name__)


class VolumeScorer(BaseScorer):
    """Scores stocks based on Relative Volume (RVOL).

    RVOL measures today's volume against the average volume at the same
    time of day. High RVOL signals institutional participation.

    Tiers:
    - RVOL > 2.0  → 15 pts (heavy institutional activity)
    - RVOL 1.5–2.0 → 10 pts (moderate activity)
    - RVOL < 1.5  → 0 pts + AUTO-SKIP (no institutional participation)
    """

    def calculate(self, symbol: str, data: dict, bias: str = "LONG") -> ScoreResult:
        """Calculate Volume score for a symbol.

        Args:
            symbol: Stock ticker symbol.
            data: Dict with keys:
                - rvol: float (relative volume ratio)
        """
        logger.info("Calculating Volume score for %s", symbol)

        rvol: float = data.get("rvol", 0.0)

        score: float = 0.0
        auto_skip: bool = False
        skip_reason: str | None = None
        rvol_category: str = "low"

        if rvol > VOLUME_RVOL_HIGH_THRESHOLD:
            score = VOLUME_RVOL_HIGH_SCORE
            rvol_category = "high"
        elif rvol >= VOLUME_RVOL_MED_THRESHOLD:
            score = VOLUME_RVOL_MED_SCORE
            rvol_category = "medium"
        else:
            score = 0.0
            rvol_category = "low"
            auto_skip = True
            skip_reason = (
                f"RVOL {rvol:.2f} below {VOLUME_RVOL_MED_THRESHOLD} — "
                f"no institutional participation"
            )

        score = max(0.0, min(score, VOLUME_MAX_SCORE))

        details = {
            "rvol_value": round(rvol, 4),
            "rvol_category": rvol_category,
        }

        logger.info(
            "Volume score for %s: %.1f/%.1f (RVOL=%.2f, category=%s, skip=%s)",
            symbol, score, VOLUME_MAX_SCORE, rvol, rvol_category, auto_skip,
        )

        return ScoreResult(
            score=score,
            max_score=VOLUME_MAX_SCORE,
            details=details,
            auto_skip=auto_skip,
            skip_reason=skip_reason,
        )
