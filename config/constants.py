"""
Hardcoded constants for the Institutional Momentum Trading System.

These values are derived directly from the trading specification and should
NOT be changed without updating the scoring/risk logic that depends on them.

Categories:
    - Scoring maximums and sub-component weights
    - IST time windows with entry thresholds
    - Auto-skip filters
    - Risk parameters
    - Technical indicator periods and refresh intervals
"""

from datetime import time
from typing import NamedTuple


# =============================================================================
# Time Window Definition
# =============================================================================

class TimeWindow(NamedTuple):
    """Represents a trading time window with an entry-score threshold."""
    start: time
    end: time
    threshold: int


# =============================================================================
# SCORING – Maximum points per category
# =============================================================================

# 1. Open Interest Score (max 25)
OI_MAX_SCORE: int = 25
OI_PUT_MAX_SCORE: int = 12
OI_CALL_MAX_SCORE: int = 8
OI_PCR_MAX_SCORE: int = 5

# 2. Price Action Score (max 20)
PRICE_MAX_SCORE: int = 20
PRICE_VWAP_MAX: int = 10
PRICE_ADX_MAX_SCORE: int = 8
PRICE_CANDLE_MAX: int = 2

# 3. Volume Score (max 15)
VOLUME_MAX_SCORE: int = 15

# 4. Space-to-Move Score (max 15, with possible negative from rejection)
SPACE_MAX_SCORE: int = 15
SPACE_ATR_MAX_SCORE: int = 10
SPACE_MAXPAIN_MAX_SCORE: int = 6
SPACE_CONFLUENCE_MAX: int = 4
SPACE_REJECTION_PENALTY: int = -5

# 5. Relative Strength Score (max 15)
RS_MAX_SCORE: int = 15

# 6. Market Regime Score (max 10)
MARKET_MAX_SCORE: int = 10

# Total possible score
TOTAL_SCORE_MAX: int = (
    OI_MAX_SCORE
    + PRICE_MAX_SCORE
    + VOLUME_MAX_SCORE
    + SPACE_MAX_SCORE
    + RS_MAX_SCORE
    + MARKET_MAX_SCORE
)  # 100


# =============================================================================
# TIME WINDOWS (IST) – (start, end, entry_threshold)
# =============================================================================

PRIME_WINDOW: TimeWindow = TimeWindow(
    start=time(9, 15),
    end=time(10, 0),
    threshold=80,
)

TREND_WINDOW: TimeWindow = TimeWindow(
    start=time(10, 0),
    end=time(12, 0),
    threshold=80,
)

DEAD_ZONE: TimeWindow = TimeWindow(
    start=time(12, 0),
    end=time(14, 0),
    threshold=90,
)

CLOSING_WINDOW: TimeWindow = TimeWindow(
    start=time(14, 0),
    end=time(15, 15),
    threshold=85,
)

# Ordered list for easy iteration
ALL_WINDOWS: list[TimeWindow] = [
    PRIME_WINDOW,
    TREND_WINDOW,
    DEAD_ZONE,
    CLOSING_WINDOW,
]


# =============================================================================
# AUTO-SKIP THRESHOLDS
# =============================================================================

OI_CHANGE_THRESHOLD_PCT: float = 5.0       # % change in OI required to be significant
VIX_MAX: float = 16.0                  # Skip if India VIX > this value
RVOL_MIN: float = 1.5                  # Relative volume floor
GAP_UP_THRESHOLD: float = 2.0          # % gap-up threshold
RESISTANCE_ATR_MIN: float = 0.7        # Minimum ATR distance to resistance
CONFLUENCE_ZONE_PCT: float = 0.5       # % band around confluence zone


# =============================================================================
# RISK PARAMETERS
# =============================================================================

PER_TRADE_RISK_PCT: float = 1.0        # % of capital risked per trade
DAILY_LOSS_LIMIT_PCT: float = 3.0      # % of capital – hard stop for the day


# =============================================================================
# INTERVALS & TECHNICAL INDICATOR PERIODS
# =============================================================================

# Refresh intervals (seconds)
SCORE_UPDATE_INTERVAL: int = 180       # 3 minutes
OI_REFRESH_INTERVAL: int = 300         # 5 minutes

# Technical indicator look-back periods
ADX_PERIOD: int = 14
ATR_PERIOD: int = 14
EMA_SHORT: int = 20
EMA_LONG: int = 50
VOLUME_AVG_DAYS: int = 20

# =============================================================================
# SCORER SPECIFIC CONSTANTS
# =============================================================================

# Market Scorer
MARKET_NIFTY_GREEN_SCORE = 3
MARKET_VIX_LOW_SCORE = 3
MARKET_PCR_RISING_SCORE = 4
MARKET_VIX_LOW_THRESHOLD = 15.0
MARKET_VIX_HIGH_THRESHOLD = 20.0

# OI Scorer
OI_PCR_PENALTY = -2
OI_MULTI_STRIKE_TOP_N = 3

# Price Scorer
PRICE_VWAP_SCORE = 10
PRICE_CANDLE_SCORE = 2
PRICE_ADX_FRESH_LOW = 20
PRICE_ADX_FRESH_HIGH = 25
PRICE_ADX_STRONG_HIGH = 35
PRICE_ADX_FRESH_SCORE = 8
PRICE_ADX_STRONG_SCORE = 5
PRICE_CANDLE_VOLUME_MULTIPLIER = 1.5

# RS Scorer
RS_LEADER_SCORE = 15
RS_PARTIAL_SCORE = 7

# Space Scorer
SPACE_CONFLUENCE_BONUS = 4
SPACE_ATR_FULL_THRESHOLD = 1.5
SPACE_ATR_PARTIAL_THRESHOLD = 1.0
SPACE_ATR_FULL_SCORE = 10
SPACE_ATR_PARTIAL_SCORE = 5
SPACE_MAXPAIN_WEIGHT_EXPIRY_DAY = 1.0
SPACE_MAXPAIN_WEIGHT_1DAY = 0.75
SPACE_MAXPAIN_WEIGHT_2_3DAYS = 0.5
SPACE_MAXPAIN_WEIGHT_DEFAULT = 0.25
SPACE_CONFLUENCE_TOLERANCE_PCT = 0.5
SPACE_REJECTION_PROXIMITY_PCT = 1.0

# Volume Scorer
VOLUME_RVOL_HIGH_THRESHOLD = 2.5
VOLUME_RVOL_HIGH_SCORE = 15
VOLUME_RVOL_MED_THRESHOLD = 1.5
VOLUME_RVOL_MED_SCORE = 8
