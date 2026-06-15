from database.collections import get_active_watchlist
from engine.eod_scanner import EODScanner

scanner = EODScanner()
scanner.run()

wl = get_active_watchlist()
print(f"Watchlist length: {len(wl)}")
for w in wl[:5]:
    print(w)
