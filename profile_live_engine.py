import tracemalloc
import time
from engine.live_engine import LiveEngine
from database.collections import get_active_watchlist

def profile_live_engine():
    # Make sure we have a watchlist
    wl = get_active_watchlist()
    if not wl:
        print("Watchlist empty. Cannot profile.")
        return

    engine = LiveEngine()
    
    # Run the update_all_scores loop once
    tracemalloc.start()
    
    start_time = time.time()
    try:
        engine._update_all_scores()
    except Exception as e:
        print(f"Error: {e}")
        
    # Run GC explicitly as it does in loop
    import gc
    gc.collect()
    
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"Took {time.time() - start_time:.2f}s")
    print(f"Current memory usage: {current / 10**6:.2f} MB")
    print(f"Peak memory usage: {peak / 10**6:.2f} MB")

if __name__ == "__main__":
    profile_live_engine()
