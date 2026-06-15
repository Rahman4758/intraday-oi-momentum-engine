import logging
from datetime import datetime, date
from config.settings import settings
from database.collections import get_risk_tracker, update_risk_tracker

logger = logging.getLogger(__name__)

class RiskManager:
    def __init__(self, db=None):
        self.db = db
        self.capital = settings.CAPITAL
        
    def calculate_position_size(self, entry_price: float, stop_loss: float) -> int:
        """Quantity = Max Risk Per Trade / (Entry - SL)"""
        risk_per_share = abs(entry_price - stop_loss)
        if risk_per_share == 0:
            return 0
        return int(settings.MAX_RISK_PER_TRADE / risk_per_share)
    
    def calculate_rr_ratio(self, entry: float, stop_loss: float, target: float) -> float:
        """R:R = (Target - Entry) / (Entry - SL)"""
        risk = abs(entry - stop_loss)
        if risk == 0:
            return 0.0
        reward = abs(target - entry)
        return round(reward / risk, 2)
    
    def is_trading_allowed(self, current_date: date) -> tuple[bool, str]:
        """Check if trading is allowed based on daily limits."""
        tracker = get_risk_tracker(current_date)
        if not tracker:
            return True, "Trading allowed"
            
        if not tracker.get('system_active', True):
            return False, "System is inactive due to hitting risk limits"
            
        if tracker.get('consecutive_losses', 0) >= settings.MAX_CONSECUTIVE_LOSSES:
            return False, f"Max consecutive losses ({settings.MAX_CONSECUTIVE_LOSSES}) hit"
            
        if tracker.get('daily_pnl', 0) <= -settings.MAX_DAILY_LOSS:
            return False, f"Max daily loss ({settings.MAX_DAILY_LOSS}) hit"
            
        return True, "Trading allowed"
    
    def log_trade_result(self, current_date: date, pnl: float, is_win: bool):
        """Log a trade result, update consecutive losses and daily P&L."""
        tracker = get_risk_tracker(current_date)
        
        trades_taken = tracker.get('trades_taken', 0) + 1 if tracker else 1
        daily_pnl = tracker.get('daily_pnl', 0.0) + pnl if tracker else pnl
        consecutive_losses = 0 if is_win else (tracker.get('consecutive_losses', 0) + 1 if tracker else 1)
        
        system_active = True
        if consecutive_losses >= settings.MAX_CONSECUTIVE_LOSSES:
            system_active = False
            logger.warning("System deactivated: Max consecutive losses hit")
        if daily_pnl <= -settings.MAX_DAILY_LOSS:
            system_active = False
            logger.warning("System deactivated: Max daily loss limit hit")
            
        updates = {
            'trades_taken': trades_taken,
            'daily_pnl': daily_pnl,
            'consecutive_losses': consecutive_losses,
            'system_active': system_active
        }
        update_risk_tracker(current_date, updates)
    
    def reset_daily_tracker(self, current_date: date):
        """Reset risk tracker for a new trading day."""
        updates = {
            'trades_taken': 0,
            'daily_pnl': 0.0,
            'consecutive_losses': 0,
            'system_active': True
        }
        update_risk_tracker(current_date, updates)
        logger.info("Risk tracker reset for the new day")
