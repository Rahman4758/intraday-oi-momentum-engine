import os
import sys
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
load_dotenv()

from engine.eod_scanner import EODScanner
from engine.premarket import PreMarketAnalyzer
from engine.live_engine import LiveEngine
from database.collections import get_active_watchlist, get_latest_scores
import pandas as pd

def run():
    print("--- 1. Running EOD Scanner ---")
    eod = EODScanner()
    eod.run()
    
    watchlist = get_active_watchlist()
    print(f"\nWatchlist contains {len(watchlist)} stocks.")
    
    if not watchlist:
        print("Watchlist empty. Exiting.")
        return
        
    print("\n--- 2. Running Pre-Market Analyzer ---")
    pre = PreMarketAnalyzer()
    pre.run()
    
    print("\n--- 3. Running Live Engine ---")
    live = LiveEngine()
    live._update_all_scores()
    
    print("\n--- 4. Fetching Top Scored Stocks ---")
    scores = get_latest_scores(limit=10)
    
    if not scores:
        print("No live scores found. Maybe all stocks were auto-skipped?")
    else:
        for s in scores:
            score = s.get('total_score', 0)
            symbol = s.get('symbol', 'UNKNOWN')
            details = s.get('details', {})
            skip = s.get('auto_skip', False)
            reason = s.get('skip_reason', '')
            
            if skip:
                print(f"[SKIPPED] {symbol} | Reason: {reason}")
            else:
                print(f"[PASSED] {symbol} | Score: {score:.1f}/100 | "
                      f"OI:{details.get('oi_score', 0)} Price:{details.get('price_score', 0)} "
                      f"Vol:{details.get('volume_score', 0)}")

if __name__ == "__main__":
    run()
