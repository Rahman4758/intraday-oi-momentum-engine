import os
import httpx
from dotenv import load_dotenv
load_dotenv()

def check_raw():
    token = os.getenv("UPSTOX_ACCESS_TOKEN")
    http = httpx.Client(
        base_url="https://api.upstox.com/v2",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    resp = http.get("/market-quote/quotes", params={"instrument_key": "NSE_EQ|INE918I01026"})
    print(resp.json())

if __name__ == "__main__":
    check_raw()
