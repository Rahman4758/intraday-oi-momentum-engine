import logging
from datetime import datetime
from config.constants import VIX_MAX, RVOL_MIN, GAP_UP_THRESHOLD, RESISTANCE_ATR_MIN
from config.settings import settings

logger = logging.getLogger(__name__)

class AutoSkipChecker:
    """Checks all 10 auto-skip conditions from the spec."""
    
    def check_all(self, symbol: str, data: dict) -> tuple[bool, list[str]]:
        """
        Check all auto-skip conditions.
        Returns (should_skip: bool, reasons: list[str])
        """
        reasons = []
        should_skip = False
        
        if data.get('put_buying'):
            reasons.append("Put Buying Detected (Put OI up + Premium up)")
            should_skip = True
            
        if data.get('call_buying'):
            reasons.append("Call Buying Detected (Call OI up + Premium up)")
            should_skip = True
            
        if data.get('max_pain', 0) < data.get('current_price', 0):
            reasons.append("Max Pain < Current Price")
            should_skip = True
            
        if data.get('resistance_distance_atr', float('inf')) < RESISTANCE_ATR_MIN:
            reasons.append(f"Resistance < {RESISTANCE_ATR_MIN} ATR away")
            should_skip = True
            
        if data.get('vix', 0) > VIX_MAX:
            reasons.append(f"VIX > {VIX_MAX}")
            should_skip = True
            
        if data.get('rejection_detected'):
            reasons.append("Rejection candle in last 30 min")
            should_skip = True
            
        gap_up_pct = data.get('gap_up_pct', 0)
        if gap_up_pct > GAP_UP_THRESHOLD:
            if not data.get('put_writing_strong'):
                reasons.append(f"Gap Up > {GAP_UP_THRESHOLD}% and weak put writing")
                should_skip = True
            else:
                logger.info(f"{symbol} is a GAP UP PLAY")
                
        if data.get('rvol', float('inf')) < RVOL_MIN:
            reasons.append(f"RVOL < {RVOL_MIN}")
            should_skip = True
            
        if data.get('consecutive_losses', 0) >= settings.MAX_CONSECUTIVE_LOSSES:
            reasons.append(f"Reached {settings.MAX_CONSECUTIVE_LOSSES} consecutive losses")
            should_skip = True
            
        if data.get('daily_pnl', 0) < -settings.MAX_DAILY_LOSS:
            reasons.append(f"Daily loss exceeds max limit of {settings.MAX_DAILY_LOSS}")
            should_skip = True
            
        return should_skip, reasons
