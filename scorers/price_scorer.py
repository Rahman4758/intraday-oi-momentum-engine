"""
Price Scorer — 20 Points Maximum.

Evaluates price action via VWAP position, ADX momentum strength,
and candle volume confirmation.
"""

import logging

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    PRICE_MAX_SCORE,
    PRICE_VWAP_SCORE,
    PRICE_ADX_MAX_SCORE,
    PRICE_CANDLE_SCORE,
    PRICE_ADX_FRESH_LOW,
    PRICE_ADX_FRESH_HIGH,
    PRICE_ADX_STRONG_HIGH,
    PRICE_ADX_FRESH_SCORE,
    PRICE_ADX_STRONG_SCORE,
    PRICE_CANDLE_VOLUME_MULTIPLIER,
)

logger = logging.getLogger(__name__)


class PriceScorer(BaseScorer):
    """Scores stocks based on price action analysis.

    Evaluates:
    - VWAP holding: price above VWAP (10 pts)
    - ADX strength: fresh vs strong vs extended (8 pts)
    - Candle confirmation: volume spike above 1.5× average (2 pts)
    """

    def calculate(self, symbol: str, data: dict) -> ScoreResult:
        """Calculate Price score for a symbol.

        Args:
            symbol: Stock ticker symbol.
            data: Dict with keys:
                - current_price: float
                - vwap: float
                - adx: float
                - latest_candle: dict with open/high/low/close/volume
                - avg_candle_volume: float
        """
        logger.info("Calculating Price score for %s", symbol)

        current_price: float = data.get("current_price", 0.0)
        vwap: float = data.get("vwap", 0.0)
        adx: float = data.get("adx", 0.0)
        latest_candle: dict = data.get("latest_candle", {})
        avg_candle_volume: float = data.get("avg_candle_volume", 0.0)

        candle_close: float = latest_candle.get("close", 0.0)
        candle_volume: float = latest_candle.get("volume", 0.0)

        # -----------------------------------------------------------
        # VWAP Score (10 pts)
        # -----------------------------------------------------------
        vwap_holding = current_price > vwap if vwap > 0 else False
        vwap_score = PRICE_VWAP_SCORE if vwap_holding else 0.0

        # -----------------------------------------------------------
        # ADX Score (8 pts)
        # -----------------------------------------------------------
        adx_score: float = 0.0
        adx_category: str = "no_momentum"

        if PRICE_ADX_FRESH_LOW <= adx < PRICE_ADX_FRESH_HIGH:
            adx_score = PRICE_ADX_FRESH_SCORE
            adx_category = "fresh_move"
        elif PRICE_ADX_FRESH_HIGH <= adx < PRICE_ADX_STRONG_HIGH:
            adx_score = PRICE_ADX_STRONG_SCORE
            adx_category = "strong_trend"
        elif adx >= PRICE_ADX_STRONG_HIGH:
            adx_score = 0.0
            adx_category = "extended"
        else:
            adx_score = 0.0
            adx_category = "no_momentum"

        # -----------------------------------------------------------
        # Candle Confirmation (2 pts)
        # -----------------------------------------------------------
        candle_confirmed = False
        candle_score: float = 0.0

        if avg_candle_volume > 0:
            volume_ratio = candle_volume / avg_candle_volume
            # Both conditions: volume > 1.5x AND close above VWAP
            if (volume_ratio > PRICE_CANDLE_VOLUME_MULTIPLIER
                    and candle_close > vwap):
                candle_confirmed = True
                candle_score = PRICE_CANDLE_SCORE

        # -----------------------------------------------------------
        # Total Score
        # -----------------------------------------------------------
        total_score = vwap_score + adx_score + candle_score
        total_score = max(0.0, min(total_score, PRICE_MAX_SCORE))

        details = {
            "vwap_holding": vwap_holding,
            "vwap": round(vwap, 2),
            "adx_value": round(adx, 2),
            "adx_category": adx_category,
            "candle_confirmed": candle_confirmed,
            "vwap_score": round(vwap_score, 2),
            "adx_score": round(adx_score, 2),
            "candle_score": round(candle_score, 2),
            "candle_volume": round(candle_volume, 2),
            "avg_candle_volume": round(avg_candle_volume, 2),
        }

        logger.info(
            "Price score for %s: %.1f/%.1f (VWAP=%s, ADX=%s, candle=%s)",
            symbol, total_score, PRICE_MAX_SCORE,
            vwap_holding, adx_category, candle_confirmed,
        )

        return ScoreResult(
            score=total_score,
            max_score=PRICE_MAX_SCORE,
            details=details,
            auto_skip=False,
            skip_reason=None,
        )
