"""
Scorers package for the Institutional Momentum Trading System.

Provides six scoring modules that evaluate different dimensions of
institutional momentum, plus the base class and result container.

Scoring Modules (100 pts total):
    - OIScorer:     Open Interest analysis (25 pts)
    - PriceScorer:  Price action via VWAP/ADX (20 pts)
    - VolumeScorer: Relative volume (15 pts)
    - SpaceScorer:  Upside room to resistance (15 pts)
    - RSScorer:     Relative strength vs sector/market (15 pts)
    - MarketScorer: Broad market conditions (10 pts)
"""

from scorers.base import BaseScorer, ScoreResult
from scorers.oi_scorer import OIScorer
from scorers.price_scorer import PriceScorer
from scorers.volume_scorer import VolumeScorer
from scorers.space_scorer import SpaceScorer
from scorers.rs_scorer import RSScorer
from scorers.market_scorer import MarketScorer

__all__ = [
    "BaseScorer",
    "ScoreResult",
    "OIScorer",
    "PriceScorer",
    "VolumeScorer",
    "SpaceScorer",
    "RSScorer",
    "MarketScorer",
]
