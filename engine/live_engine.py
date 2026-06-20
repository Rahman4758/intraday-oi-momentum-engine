import threading
import time
import logging
from datetime import datetime, time as dt_time, timedelta
from config.constants import SCORE_UPDATE_INTERVAL, OI_REFRESH_INTERVAL, ALL_WINDOWS
from services.upstox_client import UpstoxService
from services.instrument_mapper import InstrumentMapper
from database.connection import get_db
from database.collections import get_active_watchlist, save_live_score, save_alert, get_oi_baseline, get_universe
from engine.risk_manager import RiskManager
from engine.alert_generator import AlertGenerator
from engine.auto_skip import AutoSkipChecker
from scorers.oi_scorer import OIScorer
from scorers.price_scorer import PriceScorer
from scorers.volume_scorer import VolumeScorer
from scorers.space_scorer import SpaceScorer
from scorers.rs_scorer import RSScorer
from scorers.market_scorer import MarketScorer
from indicators.vwap import calculate_vwap
from indicators.adx import calculate_adx
from indicators.rvol import calculate_rvol
from services.telegram_client import TelegramClient
from config.universe import SECTOR_INDEX_MAP, INDEX_KEYS

logger = logging.getLogger(__name__)

class LiveEngine:
    def __init__(self):
        self.upstox = UpstoxService()
        self.mapper = InstrumentMapper()
        self.db = get_db()
        self.risk_manager = RiskManager(self.db)
        self.alert_generator = AlertGenerator(self.db)
        self.auto_skip_checker = AutoSkipChecker()
        
        # All scorers
        self.oi_scorer = OIScorer()
        self.price_scorer = PriceScorer()
        self.volume_scorer = VolumeScorer()
        self.space_scorer = SpaceScorer()
        self.rs_scorer = RSScorer()
        self.market_scorer = MarketScorer()
        self.telegram = TelegramClient()
        
        # State
        self._running = False
        self._alerts_sent = set()
        
    def start(self):
        """Start the live engine. Called at 9:15 AM."""
        if self._running:
            return
        self._running = True
        logger.info("Live Engine starting (STRICT REAL API MODE)...")
        
        thread = threading.Thread(target=self._scoring_loop)
        thread.daemon = True
        thread.start()
        
    def stop(self):
        """Stop the live engine. Called at 3:15 PM."""
        self._running = False
        logger.info("Live Engine stopping...")
        
    def _is_market_hours(self, dt: datetime) -> bool:
        """Check if time is between 9:15 and 15:30 IST"""
        t = dt.time()
        start = dt_time(9, 15)
        end = dt_time(15, 30)
        return start <= t <= end
        
    def _get_time_threshold(self, t: dt_time) -> int:
        for window in ALL_WINDOWS:
            if window.start <= t <= window.end:
                return window.threshold
        return 100 # High threshold outside windows
        
    def _scoring_loop(self):
        """Main scoring loop running every 3 minutes."""
        # Force immediate first run
        last_score_time = 0
        
        while self._running:
            now = datetime.now()
            
            # if not self._is_market_hours(now):
            #     time.sleep(10)
            #     continue
                
            current_time_sec = time.time()
            
            if current_time_sec - last_score_time >= SCORE_UPDATE_INTERVAL:
                try:
                    self._update_all_scores()
                except Exception as e:
                    logger.error(f"Error in Live Engine scoring loop: {e}", exc_info=True)
                finally:
                    import gc
                    gc.collect()
                last_score_time = time.time()
                
            time.sleep(5)
            
    def _update_all_scores(self):
        """Calculate all scores for all watchlist stocks strictly using REST API."""
        watchlist = get_active_watchlist()
        if not watchlist:
            logger.info("LiveEngine: Watchlist empty. Nothing to score.")
            return
            
        symbols = [s['symbol'] for s in watchlist if s.get('status') != 'skip']
        if not symbols:
            logger.info("LiveEngine: All watchlist stocks are skipped. Nothing to score.")
            return
            
        logger.info(f"LiveEngine evaluating {len(symbols)} stocks...")
        
        instrument_keys = []
        symbol_to_key = {}
        for sym in symbols:
            key = self.mapper.get_equity_key(sym)
            if key:
                instrument_keys.append(key)
                symbol_to_key[sym] = key
            
        nifty_key = INDEX_KEYS.get("NIFTY 50")
        vix_key = INDEX_KEYS.get("INDIA VIX")
        all_keys = instrument_keys.copy()
        if nifty_key: all_keys.append(nifty_key)
        if vix_key: all_keys.append(vix_key)
        
        sectors_needed = set()
        for sym in symbols:
            info = SECTOR_INDEX_MAP.get(sym, {})
            s_key = info.get('upstox_index_key')
            if s_key:
                sectors_needed.add(s_key)
        all_keys.extend(list(sectors_needed))

        # 1. Fetch Market Quotes
        try:
            quotes = self.upstox.get_market_quote(all_keys)
        except Exception as e:
            logger.error(f"LiveEngine: Failed to fetch market quotes. Skipping this 3-min cycle. Error: {e}")
            return
            
        nifty_quote = quotes.get(nifty_key, {}) if nifty_key else {}
        vix_quote = quotes.get(vix_key, {}) if vix_key else {}
        nifty_change = nifty_quote.get('change_pct', 0.0)
        vix_ltp = vix_quote.get('ltp', 15.0)

        now = datetime.now()
        minutes_elapsed = int((now - now.replace(hour=9, minute=15, second=0)).total_seconds() / 60)
        if minutes_elapsed <= 0: minutes_elapsed = 1

        for sym in symbols:
            key = symbol_to_key.get(sym)
            if not key:
                continue
                
            stock_quote = quotes.get(key)
            if not stock_quote:
                logger.warning(f"[{sym}] No live quote found. Skipping.")
                continue
                
            current_price = stock_quote.get('ltp', 0)
            current_volume = stock_quote.get('volume', 0)
            stock_change = stock_quote.get('change_pct', 0.0)
            
            # Fetch Baseline data
            baseline = get_oi_baseline(sym)
            baseline_pcr = baseline[0].get('pcr', 1.0) if baseline else 1.0
            
            # Fetch Stock Universe metadata (for RVOL and ATR)
            stock_meta = None
            for s in get_universe():
                if s['symbol'] == sym:
                    stock_meta = s
                    break
            
            avg_vol_20d = stock_meta.get('avg_volume_20d', 100000) if stock_meta else 100000
            atr_14 = stock_meta.get('atr_14', current_price * 0.02) if stock_meta else current_price * 0.02
            
            # 2. Fetch Option Chain
            try:
                expiries = self.upstox.get_expiry_dates(key)
                if expiries:
                    current_chain = self.upstox.get_option_chain(key, expiries[0])
                else:
                    raise ValueError("No expiry dates found")
            except Exception as e:
                logger.error(f"[{sym}] Option chain fetch failed: {e}. Skipping stock.")
                continue
                
            total_ce = sum(c['call_oi'] for c in current_chain)
            total_pe = sum(c['put_oi'] for c in current_chain)
            current_pcr = total_pe / total_ce if total_ce > 0 else 1.0
            
            # Max Pain
            max_pain = 0
            if current_chain:
                # Basic max pain (simplified)
                min_pain = float('inf')
                for c in current_chain:
                    strike = c["strike_price"]
                    pain = 0
                    for oc in current_chain:
                        o_strike = oc["strike_price"]
                        pain += max(0, strike - o_strike) * oc["call_oi"]
                        pain += max(0, o_strike - strike) * oc["put_oi"]
                    if pain < min_pain:
                        min_pain = pain
                        max_pain = strike

            # 3. Fetch 1-min Candles for VWAP and ADX
            try:
                candles_1m = self.upstox.get_intraday_candles(key, "1minute")
                if candles_1m.empty:
                    logger.warning(f"[{sym}] Intraday candles empty. Cannot calculate VWAP/ADX. Skipping.")
                    continue
            except Exception as e:
                logger.error(f"[{sym}] Intraday candles fetch failed: {e}. Skipping stock.")
                continue
                
            vwap_val = calculate_vwap(candles_1m)
            adx_val = calculate_adx(candles_1m, 14)
            rvol_val = calculate_rvol(current_volume, [avg_vol_20d], minutes_elapsed)

            if pd.isna(vwap_val): vwap_val = current_price
            if pd.isna(adx_val): adx_val = 0

            # 4. Construct unified Data Dictionary
            info = SECTOR_INDEX_MAP.get(sym, {})
            s_key = info.get('upstox_index_key')
            sector_change = quotes.get(s_key, {}).get('change_pct', 0.0) if s_key else 0.0

            data = {
                'current_price': current_price,
                'vwap': vwap_val,
                'adx': adx_val,
                'rvol': rvol_val,
                'atr': atr_14,
                'max_pain': max_pain,
                'vix_value': vix_ltp,
                'nifty_change_pct': nifty_change,
                'sector_index_change_pct': sector_change,
                'stock_change_pct': stock_change,
                'current_option_chain': current_chain,
                'baseline_option_chain': baseline,
                'current_pcr': current_pcr,
                'baseline_pcr': baseline_pcr,
                'index_pcr_rising': True, # Simplified
            }
            
            # 5. Run All Scorers
            oi_result = self.oi_scorer.calculate(sym, data)
            price_result = self.price_scorer.calculate(sym, data)
            volume_result = self.volume_scorer.calculate(sym, data)
            space_result = self.space_scorer.calculate(sym, data)
            rs_result = self.rs_scorer.calculate(sym, data)
            market_result = self.market_scorer.calculate(sym, data)
            
            total_score = sum(r.score for r in [oi_result, price_result, volume_result, space_result, rs_result, market_result])
            
            should_skip, skip_reasons = self.auto_skip_checker.check_all(sym, data)
            for r in [oi_result, price_result, volume_result, space_result, rs_result, market_result]:
                if r.auto_skip:
                    should_skip = True
                    if r.skip_reason:
                        skip_reasons.append(r.skip_reason)
                        
            score_data = {
                'symbol': sym,
                'oi_score': oi_result.score,
                'price_score': price_result.score,
                'volume_score': volume_result.score,
                'space_score': space_result.score,
                'rs_score': rs_result.score,
                'market_score': market_result.score,
                'total_score': total_score,
                'auto_skip': should_skip,
                'skip_reason': '; '.join(skip_reasons) if skip_reasons else None,
                'timestamp': now
            }
            save_live_score(score_data)
            logger.info(f"[{sym}] Live Score Updated: {total_score}/100. Auto-skip: {should_skip}")
            
            # 6. Check Time Windows & Trigger Alert
            if not should_skip:
                threshold = self._get_time_threshold(now.time())
                trading_ok, _ = self.risk_manager.is_trading_allowed(now.date().isoformat())
                
                if total_score >= threshold and trading_ok:
                    if sym not in self._alerts_sent:
                        alert = self.alert_generator.generate_alert(sym, {
                            'oi': oi_result, 'price': price_result,
                            'volume': volume_result, 'space': space_result,
                            'rs': rs_result, 'market': market_result
                        }, data)
                        save_alert(alert)
                        self._alerts_sent.add(sym)
                        
                        # Send Telegram Notification
                        alert_text = self.alert_generator.format_alert_text(alert)
                        self.telegram.send_message(alert_text)
                        
                        logger.info(f"*** ALERT TRIGGERED: {sym} Score={total_score} >= Threshold({threshold}) ***")
