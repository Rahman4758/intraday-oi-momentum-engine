from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime, date, time
import logging

from database.collections import get_latest_scores, get_alerts_today, get_active_watchlist, get_risk_tracker
from engine.risk_manager import RiskManager
from engine.eod_scanner import EODScanner
from engine.premarket import PreMarketAnalyzer
from dashboard.websocket_handler import manager

router = APIRouter()
templates = Jinja2Templates(directory="dashboard/templates")
logger = logging.getLogger(__name__)

class TradeResult(BaseModel):
    symbol: str
    pnl: float
    is_win: bool

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@router.get("/alerts", response_class=HTMLResponse)
async def alerts_page(request: Request):
    return templates.TemplateResponse(request=request, name="alerts.html")

@router.get("/api/scores")
async def api_scores():
    scores = get_latest_scores()
    return {"status": "success", "data": scores}

@router.get("/api/alerts")
async def api_alerts():
    alerts = get_alerts_today()
    return {"status": "success", "data": alerts}

@router.get("/api/risk")
async def api_risk():
    tracker = get_risk_tracker()
    if not tracker:
        tracker = {
            'trades_taken': 0,
            'daily_pnl': 0.0,
            'consecutive_losses': 0,
            'system_active': True
        }
    return {"status": "success", "data": tracker}

@router.get("/api/watchlist")
async def api_watchlist():
    watchlist = get_active_watchlist()
    return {"status": "success", "data": watchlist}

@router.post("/api/trade")
async def log_trade(trade: TradeResult):
    rm = RiskManager()
    rm.log_trade_result(datetime.now().date().isoformat(), trade.pnl, trade.is_win)
    
    # Broadcast risk update
    tracker = get_risk_tracker()
    await manager.broadcast({"type": "risk_update", "data": tracker})
    
    return {"status": "success", "message": "Trade logged successfully"}



_is_eod_running = False
_is_premarket_running = False

@router.post("/api/eod/run")
def trigger_eod():
    global _is_eod_running
    if _is_eod_running:
        return {"status": "error", "message": "EOD Scan is already running! Please wait."}
        
    current_time = datetime.now().time()
    if time(9, 15) <= current_time <= time(15, 30):
        return {"status": "error", "message": "EOD Scan cannot be run during market hours (9:15 AM - 3:30 PM)."}
        
    try:
        _is_eod_running = True
        scanner = EODScanner()
        scanner.run()
        return {"status": "success", "message": "EOD Scan complete"}
    finally:
        _is_eod_running = False

@router.post("/api/premarket/run")
def trigger_premarket():
    global _is_premarket_running
    if _is_premarket_running:
        return {"status": "error", "message": "Pre-Market Analysis is already running! Please wait."}
        
    try:
        _is_premarket_running = True
        analyzer = PreMarketAnalyzer()
        analyzer.run()
        return {"status": "success", "message": "Pre-Market analysis complete"}
    finally:
        _is_premarket_running = False

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
