import httpx

urls = [
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE_FO.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz",
    "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
]

for u in urls:
    try:
        r = httpx.head(u, follow_redirects=True)
        print(f"{u}: {r.status_code}")
    except Exception as e:
        print(f"{u}: Error - {e}")
