import logging
from datetime import datetime, timedelta, date
import pandas as pd
import numpy as np

from services.upstox_client import UpstoxService
from services.nse_data import NSEDataService
from services.instrument_mapper import InstrumentMapper
from database.connection import get_db
from database.collections import upsert_stock, save_oi_baseline, save_watchlist
from indicators.atr import calculate_atr
from indicators.ema import calculate_ema

logger = logging.getLogger(__name__)

class EODScanner:
    def __init__(self):
        self.upstox = UpstoxService()
        self.nse = NSEDataService()
        self.mapper = InstrumentMapper()
        self.db = get_db()
        
    def _get_latest_bhavcopy(self):
        today = date.today()
        for days_back in range(7):
            target_date = today - timedelta(days=days_back)
            # Skip weekends implicitly if empty
            df = self.nse.fetch_bhavcopy(target_date)
            if not df.empty:
                return df, target_date
        return pd.DataFrame(), today

    def _get_delivery_pct(self, bhav_df: pd.DataFrame, symbol: str) -> float:
        if bhav_df.empty:
            return 0.0
            
        symbol_upper = symbol.strip().upper()
        mask = bhav_df["SYMBOL"].str.strip() == symbol_upper
        if "SERIES" in bhav_df.columns:
            mask = mask & (bhav_df["SERIES"].str.strip() == "EQ")
            
        rows = bhav_df.loc[mask]
        if rows.empty:
            return 0.0
            
        row = rows.iloc[0]
        delivery_pct = float(row.get("DELIV_PER", row.get("DELIVERY_PERCENTAGE", 0)))
        return delivery_pct

    def run(self):
        """Main EOD scan job. Run at 8 PM IST."""
        logger.info("Starting EOD Scanner Phase 1 (Universe Filter)...")
        
        from config.universe import UNIVERSE_SYMBOLS, SECTOR_INDEX_MAP
        symbols = UNIVERSE_SYMBOLS
        
        bhav_df, bhav_date = self._get_latest_bhavcopy()
        logger.info(f"Using Bhavcopy from {bhav_date}")
        
        shortlisted_stocks = []
        
        to_date_str = date.today().strftime("%Y-%m-%d")
        from_date_str = (date.today() - timedelta(days=40)).strftime("%Y-%m-%d")
        
        for symbol in symbols:
            try:
                instrument_key = self.mapper.get_equity_key(symbol)
                if not instrument_key:
                    logger.warning(f"[{symbol}] Skipped: No instrument key mapped.")
                    continue
                
                universe_info = SECTOR_INDEX_MAP.get(symbol, {})
                
                # 1. Delivery % Check
                delivery_pct = self._get_delivery_pct(bhav_df, symbol)
                if delivery_pct < 50.0:
                    logger.debug(f"[{symbol}] Skipped: Delivery {delivery_pct}% < 50%")
                    continue
                        
                # 2. OHLCV Fetch for Price/EMA & RVOL
                try:
                    candles = self.upstox.get_historical_candles(instrument_key, "day", from_date_str, to_date_str)
                except Exception as e:
                    logger.error(f"[{symbol}] Upstox API failed to fetch historical candles: {e}")
                    continue
                    
                if len(candles) < 20:
                    logger.debug(f"[{symbol}] Skipped: Insufficient candle data.")
                    continue
                    
                # 3. EMA & RVOL Calculation
                candles['ema_20'] = calculate_ema(candles['close'], 20)
                candles['ema_50'] = calculate_ema(candles['close'], 50)
                
                last_row = candles.iloc[-1]
                close_price = last_row['close']
                ema_20 = last_row['ema_20']
                ema_50 = last_row['ema_50']
                
                bias = "LONG" if close_price > ema_50 else "SHORT"
                    
                avg_volume_20d = candles['volume'].tail(20).mean()
                current_volume = last_row['volume']
                
                if current_volume < avg_volume_20d:
                    logger.debug(f"[{symbol}] Skipped: Volume {current_volume} < 20D Avg {avg_volume_20d:.0f}")
                    continue
                atr_14 = calculate_atr(candles, 14)
                if pd.isna(atr_14):
                    atr_14 = close_price * 0.02 # fallback
                
                # Passes Phase 1!
                stock_data = {
                    'symbol': symbol,
                    'sector': universe_info.get('sector', 'Unknown'),
                    'index': universe_info.get('index', 'OTHER F&O'),
                    'liquidity_tier': universe_info.get('liquidity_tier', 4),
                    'avg_volume_20d': float(avg_volume_20d),
                    'atr_14': float(atr_14),
                    'ema_20': float(ema_20),
                    'ema_50': float(ema_50),
                    'delivery_pct': float(delivery_pct),
                    'last_updated': datetime.now()
                }
                upsert_stock(stock_data)
                shortlisted_stocks.append({
                    'symbol': symbol,
                    'instrument_key': instrument_key,
                    'close_price': close_price,
                    'delivery_pct': delivery_pct,
                    'ema_20': ema_20,
                    'ema_50': ema_50,
                    'avg_volume_20d': avg_volume_20d,
                    'atr_14': atr_14,
                    'bias': bias
                })
                
            except Exception as e:
                logger.error(f"Error in Phase 1 for {symbol}: {e}")

        logger.info(f"Phase 1 complete. {len(shortlisted_stocks)} stocks shortlisted.")
        
        # -------------------------------------------------------------
        # Phase 2: OI Baseline Snapshot
        # -------------------------------------------------------------
        logger.info("Starting EOD Scanner Phase 2 (OI Baseline)...")
        watchlist_candidates = []
        
        # For simplicity, we just use the nearest expiry from API
        for stock_info in shortlisted_stocks:
            symbol = stock_info['symbol']
            instrument_key = stock_info['instrument_key']
            ltp = stock_info['close_price']
            try:
                expiries = self.upstox.get_expiry_dates(instrument_key)
                if not expiries:
                    logger.warning(f"[{symbol}] Skipped: No Option Expiries found.")
                    continue
                    
                target_expiry = expiries[0]
                chain = self.upstox.get_option_chain(instrument_key, target_expiry)
                
                if not chain:
                    logger.warning(f"[{symbol}] Skipped: Empty option chain returned for expiry {target_expiry}.")
                    continue
                    
                # Find ATM
                closest_diff = float('inf')
                atm_strike = chain[0]["strike_price"]
                total_ce_oi = 0
                total_pe_oi = 0
                
                for c in chain:
                    total_ce_oi += c["call_oi"]
                    total_pe_oi += c["put_oi"]
                    diff = abs(c["strike_price"] - ltp)
                    if diff < closest_diff:
                        closest_diff = diff
                        atm_strike = c["strike_price"]
                        
                stock_pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
                bias = stock_info['bias']
                
                if bias == "LONG" and stock_pcr < 0.8:
                    logger.debug(f"[{symbol}] Skipped: LONG PCR {stock_pcr:.2f} < 0.8")
                    continue
                elif bias == "SHORT" and stock_pcr > 0.6:
                    logger.debug(f"[{symbol}] Skipped: SHORT PCR {stock_pcr:.2f} > 0.6")
                    continue
                
                # Sort for Top 3 Put Strikes
                sorted_by_put = sorted(chain, key=lambda x: x["put_oi"], reverse=True)
                top_3_puts = sorted_by_put[:3]
                
                # Sort for Top 3 Call Strikes
                sorted_by_call = sorted(chain, key=lambda x: x["call_oi"], reverse=True)
                top_3_calls = sorted_by_call[:3]
                
                # Combine top strikes
                top_strikes_map = {}
                for c in (top_3_puts + top_3_calls):
                    strike = c["strike_price"]
                    if strike not in top_strikes_map:
                        stype = "ATM" if strike == atm_strike else ("OTM" if strike > ltp else "ITM")
                        top_strikes_map[strike] = {
                            'symbol': symbol,
                            'strike': strike,
                            'strike_type': stype,
                            'put_oi': c["put_oi"],
                            'call_oi': c["call_oi"],
                            'put_premium': c["put_premium"],
                            'call_premium': c["call_premium"],
                            'pcr': stock_pcr, # Storing aggregate PCR
                            'snapshot_time': datetime.now()
                        }
                
                for s_data in top_strikes_map.values():
                    save_oi_baseline(s_data)
                    
                stock_info['pcr'] = stock_pcr
                watchlist_candidates.append(stock_info)
                
            except Exception as e:
                logger.error(f"Error in Phase 2 for {symbol}: {e}")
                
        # Save selected candidates to tomorrow's watchlist
        # Limit to 30 to avoid massive dashboard load if mock passes too many
        final_list = watchlist_candidates[:30]
        for w_info in final_list:
            save_watchlist({
                'symbol': w_info['symbol'],
                'date': datetime.now().date().isoformat(),
                'status': 'active',
                'metrics': {
                    'delivery_pct': w_info['delivery_pct'],
                    'ema_20': w_info['ema_20'],
                    'ema_50': w_info['ema_50'],
                    'avg_volume_20d': w_info['avg_volume_20d'],
                    'atr_14': w_info['atr_14'],
                    'pcr': w_info['pcr']
                },
                'bias': w_info['bias']
            })
            
        logger.info(f"EOD Scanner complete. {len(final_list)} added to watchlist.")
