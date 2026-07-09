import os
from dotenv import load_dotenv
load_dotenv()
from services.upstox_client import UpstoxService

def check_quotes():
    upstox = UpstoxService()
    keys = ["NSE_EQ|INE918I01026", "NSE_INDEX|Nifty 50"]
    quotes = upstox.get_market_quote(keys)
    print("Keys requested:", keys)
    print("Keys returned:", list(quotes.keys()))
    print("Data:", quotes)

if __name__ == "__main__":
    check_quotes()
