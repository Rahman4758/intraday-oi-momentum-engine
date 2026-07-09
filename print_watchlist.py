import os
from dotenv import load_dotenv
load_dotenv()

from database.collections import get_active_watchlist

watchlist = get_active_watchlist()
if not watchlist:
    print("Watchlist is empty.")
else:
    print(f"Total stocks in watchlist: {len(watchlist)}")
    for w in watchlist:
        metrics = w.get('metrics', {})
        print(f"- {w['symbol']}: Delivery={metrics.get('delivery_pct')}%, Volume Breakout=Yes, PCR={metrics.get('pcr'):.2f}")
