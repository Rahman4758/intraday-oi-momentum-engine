import logging
import uvicorn
from config.settings import settings
from database.connection import get_db, check_health
from database.collections import setup_indexes
from scheduler import create_scheduler
from dashboard.app import create_app

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Initializing Institutional Momentum Trading System...")
    
    # Initialize DB
    db = get_db()
    if not check_health():
        logger.error("Database connection failed. Exiting.")
        return
        
    setup_indexes()
    logger.info("Database initialized with indexes.")
    
    # Start Scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("Scheduler started.")
    
    # Create FastAPI app
    app = create_app()
    
    # Run server
    logger.info(f"Starting Dashboard on {settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}")
    uvicorn.run(app, host=settings.DASHBOARD_HOST, port=settings.DASHBOARD_PORT)

if __name__ == "__main__":
    main()
