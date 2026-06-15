import json
import logging
from pathlib import Path
from nselib import capital_market

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def build_universe():
    logger.info("Fetching F&O list from NSE...")
    fno_df = capital_market.fno_equity_list()
    # Handle both column name variations
    col_name = 'Symbol' if 'Symbol' in fno_df.columns else fno_df.columns[0]
    fno_symbols = set(fno_df[col_name].tolist())
    
    logger.info(f"Fetched {len(fno_symbols)} F&O symbols.")
    
    logger.info("Fetching Nifty 50 list...")
    n50_df = capital_market.nifty50_equity_list()
    n50_symbols = set(n50_df['Symbol'].tolist() if 'Symbol' in n50_df.columns else n50_df.iloc[:, 0].tolist())
    
    logger.info("Fetching Nifty Next 50 list...")
    nn50_df = capital_market.niftynext50_equity_list()
    nn50_symbols = set(nn50_df['Symbol'].tolist() if 'Symbol' in nn50_df.columns else nn50_df.iloc[:, 0].tolist())
    
    logger.info("Fetching Nifty Midcap 150 list...")
    nmid_df = capital_market.niftymidcap150_equity_list()
    nmid_symbols = set(nmid_df['Symbol'].tolist() if 'Symbol' in nmid_df.columns else nmid_df.iloc[:, 0].tolist())
    
    universe = {}
    for sym in fno_symbols:
        if sym in n50_symbols:
            tier = 1
            index_name = "NIFTY 50"
            index_key = "NSE_INDEX|Nifty 50"
        elif sym in nn50_symbols:
            tier = 2
            index_name = "NIFTY NEXT 50"
            index_key = "NSE_INDEX|NIFTY NEXT 50"
        elif sym in nmid_symbols:
            tier = 3
            index_name = "NIFTY MIDCAP 150"
            index_key = "NSE_INDEX|NIFTY MIDCAP 150"
        else:
            tier = 4
            index_name = "OTHER F&O"
            index_key = "NSE_INDEX|NIFTY 500"  # Generic fallback benchmark
            
        universe[sym] = {
            "sector": "Broad Market", # Simplification since live_engine doesn't strictly depend on sector
            "index": index_name,
            "upstox_index_key": index_key,
            "liquidity_tier": tier
        }
        
    out_path = Path("c:/Intraday2/config/universe.json")
    out_path.parent.mkdir(exist_ok=True, parents=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=4)
        
    logger.info(f"Successfully generated universe.json with {len(universe)} stocks.")

if __name__ == "__main__":
    build_universe()
