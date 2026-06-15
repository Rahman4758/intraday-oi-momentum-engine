from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from engine.eod_scanner import EODScanner
from engine.premarket import PreMarketAnalyzer
from engine.live_engine import LiveEngine
from engine.risk_manager import RiskManager
from datetime import datetime
import os
import httpx
import logging
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

IST = pytz.timezone('Asia/Kolkata')

def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=IST)
    
    eod = EODScanner()
    premarket = PreMarketAnalyzer()
    live = LiveEngine()
    risk = RiskManager()
    
    # EOD Scanner: 8 PM Mon-Fri
    scheduler.add_job(eod.run, CronTrigger(hour=20, minute=0, day_of_week='mon-fri', timezone=IST), id='eod_scanner')
    
    # Pre-Market: 9:31 AM Mon-Fri
    scheduler.add_job(premarket.run, CronTrigger(hour=9, minute=31, day_of_week='mon-fri', timezone=IST), id='premarket')
    
    # Live Engine Start: 9:32 AM Mon-Fri (after pre-market)
    scheduler.add_job(live.start, CronTrigger(hour=9, minute=32, day_of_week='mon-fri', timezone=IST), id='live_start')
    
    # Live Engine Stop: 3:16 PM Mon-Fri
    scheduler.add_job(live.stop, CronTrigger(hour=15, minute=16, day_of_week='mon-fri', timezone=IST), id='live_stop')
    
    # Risk Reset: 9:00 AM Mon-Fri (reset daily tracker)
    def reset_risk():
        risk.reset_daily_tracker(datetime.now(IST).date())
        
    scheduler.add_job(reset_risk, CronTrigger(hour=9, minute=0, day_of_week='mon-fri', timezone=IST), id='risk_reset')
    
    # Keep-Alive Ping for Render Free Tier (runs every 5 minutes)
    def keep_alive_ping():
        url = os.environ.get("RENDER_EXTERNAL_URL")
        if url:
            try:
                # Ping the root dashboard to keep the web service awake
                httpx.get(url, timeout=10.0)
                logger.debug(f"Keep-alive ping sent to {url}")
            except Exception as e:
                logger.error(f"Keep-alive ping failed: {e}")
                
    scheduler.add_job(keep_alive_ping, IntervalTrigger(minutes=5), id='keep_alive')
    
    return scheduler
