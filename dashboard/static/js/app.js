let ws;

function connectWS() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    
    ws.onopen = () => {
        console.log('WebSocket connected');
        document.querySelector('.status-dot').style.backgroundColor = 'var(--color-green)';
    };
    
    ws.onclose = () => {
        console.log('WebSocket disconnected, reconnecting...');
        document.querySelector('.status-dot').style.backgroundColor = 'var(--color-red)';
        setTimeout(connectWS, 3000);
    };
    
    ws.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.type === 'risk_update') {
            updateRiskPanel(msg.data);
        } else if (msg.type === 'score_update') {
            fetchScores();
        } else if (msg.type === 'new_alert') {
            fetchAlerts();
        }
    };
}

async function fetchScores() {
    try {
        const res = await fetch('/api/scores');
        const data = await res.json();
        if (data.status === 'success') {
            renderScoreCards(data.data);
        }
    } catch (e) {
        console.error("Error fetching scores", e);
    }
}

async function fetchAlerts() {
    try {
        const res = await fetch('/api/alerts');
        const data = await res.json();
        if (data.status === 'success') {
            const container = document.getElementById('alerts-container');
            if (!container) return;
            container.innerHTML = '';
            data.data.slice(0, 5).forEach(alert => {
                container.appendChild(createAlertCard(alert));
            });
        }
    } catch (e) {
        console.error("Error fetching alerts", e);
    }
}

async function fetchRisk() {
    try {
        const res = await fetch('/api/risk');
        const data = await res.json();
        if (data.status === 'success') {
            updateRiskPanel(data.data);
        }
    } catch (e) {
        console.error("Error fetching risk", e);
    }
}

async function fetchWatchlist() {
    try {
        const res = await fetch('/api/watchlist');
        const data = await res.json();
        if (data.status === 'success') {
            const container = document.getElementById('watchlist-container');
            if (!container) return;
            container.innerHTML = '';
            
            if (!data.data || data.data.length === 0) {
                container.innerHTML = '<div style="color: var(--text-muted); font-size: 0.875rem; padding: 1rem;">No stocks in watchlist for today. Run EOD Scanner.</div>';
                return;
            }
            // Sort data by bullishness
            let sortedData = data.data.sort((a, b) => {
                let aScore = (a.pre_market_oi_score || 0) + (a.pre_market_rs_score || 0);
                let bScore = (b.pre_market_oi_score || 0) + (b.pre_market_rs_score || 0);
                if (aScore !== bScore) {
                    return bScore - aScore; // Descending pre-market conviction
                }
                // Fallback if pre-market hasn't run: sort by Delivery %
                let aDel = a.metrics ? a.metrics.delivery_pct : 0;
                let bDel = b.metrics ? b.metrics.delivery_pct : 0;
                return bDel - aDel;
            });
            
            // Reusing score-card class for simple display
            sortedData.forEach(item => {
                const el = document.createElement('div');
                el.className = 'score-card glass-panel';
                el.style.padding = '1.5rem';
                
                const dateStr = item.date ? item.date : new Date().toISOString().split('T')[0];
                
                let metricsHtml = '';
                if (item.metrics) {
                    metricsHtml = `
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-top: 1rem; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 0.5rem;">
                            <div style="color: var(--text-muted);">Delivery: <span style="color: var(--text-main); font-weight: 600;">${item.metrics.delivery_pct.toFixed(1)}%</span></div>
                            <div style="color: var(--text-muted);">PCR: <span style="color: var(--text-main); font-weight: 600;">${item.metrics.pcr.toFixed(2)}</span></div>
                            <div style="color: var(--text-muted);">20 EMA: <span style="color: var(--text-main); font-weight: 600;">${Math.round(item.metrics.ema_20)}</span></div>
                            <div style="color: var(--text-muted);">50 EMA: <span style="color: var(--text-main); font-weight: 600;">${Math.round(item.metrics.ema_50)}</span></div>
                            <div style="color: var(--text-muted); grid-column: span 2;">Avg Vol: <span style="color: var(--text-main); font-weight: 600;">${(item.metrics.avg_volume_20d/1000000).toFixed(2)}M</span></div>
                        </div>
                    `;
                }
                
                el.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-size: 1.125rem; font-weight: 700;">${item.symbol}</span>
                        <span class="status-active" style="font-size: 0.75rem;">ON WATCH</span>
                    </div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.5rem; font-family: var(--font-mono);">
                        Added: ${dateStr}
                    </div>
                    ${metricsHtml}
                `;
                container.appendChild(el);
            });
        }
    } catch (e) {
        console.error("Error fetching watchlist", e);
    }
}

function updateRiskPanel(data) {
    document.getElementById('risk-trades').innerText = `${data.trades_taken}/3`;
    
    const pnlEl = document.getElementById('risk-pnl');
    pnlEl.innerText = `₹${data.daily_pnl.toFixed(2)}`;
    pnlEl.style.color = data.daily_pnl >= 0 ? 'var(--color-green)' : 'var(--color-red)';
    
    const statusEl = document.getElementById('risk-status');
    if (data.system_active) {
        statusEl.innerText = 'ACTIVE';
        statusEl.className = 'status-active';
    } else {
        statusEl.innerText = 'STOPPED';
        statusEl.className = 'status-inactive';
    }
}

function renderScoreCards(scores) {
    const container = document.getElementById('score-cards');
    if (!container) return;
    container.innerHTML = '';
    
    scores.forEach(score => {
        const card = document.createElement('div');
        card.className = 'score-card glass-panel';
        
        let skipBadge = score.auto_skip ? `<div class="auto-skip-badge" title="${score.skip_reason || 'Auto-skipped'}">SKIPPED</div>` : '';
        
        let tierClass = score.liquidity_tier === 1 ? 'tier-1' : (score.liquidity_tier === 2 ? 'tier-2' : 'tier-3');
        let indexBadge = score.index_name ? `<div class="index-badge ${tierClass}" title="Liquidity Tier ${score.liquidity_tier || 4}">${score.index_name}</div>` : '';
        
        // Gauge stroke calculation
        const circumference = 2 * Math.PI * 45;
        const offset = circumference - (score.total_score / 100) * circumference;
        let gaugeColor = score.total_score >= 80 ? 'var(--color-green)' : (score.total_score >= 60 ? 'var(--color-amber)' : 'var(--color-red)');
        
        card.innerHTML = `
            <div class="card-header">
                <div class="symbol-container">
                    <div class="symbol">${score.symbol}</div>
                    ${indexBadge}
                </div>
                ${skipBadge}
            </div>
            <div class="gauge-container">
                <svg class="gauge" viewBox="0 0 100 100">
                    <circle cx="50" cy="50" r="45" fill="none" stroke="#374151" stroke-width="8"></circle>
                    <circle cx="50" cy="50" r="45" fill="none" stroke="${gaugeColor}" stroke-width="8" 
                            stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" 
                            stroke-linecap="round" transform="rotate(-90 50 50)"></circle>
                    <text x="50" y="55" class="gauge-text" text-anchor="middle">${Math.round(score.total_score)}</text>
                </svg>
            </div>
            <div class="breakdown-bar">
                <div class="segment seg-oi" style="width: ${score.oi_score}%"></div>
                <div class="segment seg-price" style="width: ${score.price_score}%"></div>
                <div class="segment seg-vol" style="width: ${score.volume_score}%"></div>
                <div class="segment seg-space" style="width: ${score.space_score}%"></div>
                <div class="segment seg-rs" style="width: ${score.rs_score}%"></div>
                <div class="segment seg-market" style="width: ${score.market_score}%"></div>
            </div>
            <div class="details-grid">
                <div>OI <span>${score.oi_score}/25</span></div>
                <div>Space <span>${score.space_score}/15</span></div>
                <div>Price <span>${score.price_score}/20</span></div>
                <div>RS <span>${score.rs_score}/15</span></div>
                <div>Vol <span>${score.volume_score}/15</span></div>
                <div>Market <span>${score.market_score}/10</span></div>
            </div>
        `;
        container.appendChild(card);
    });
}

function createAlertCard(alert) {
    const el = document.createElement('div');
    el.className = 'alert-card glass-panel';
    
    const time = new Date(alert.triggered_at.$date || alert.triggered_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
    
    el.innerHTML = `
        <div>
            <div class="alert-symbol">${alert.symbol}</div>
            <div class="alert-time">${time}</div>
        </div>
        <div class="alert-stats">
            <div>Score: <span>${alert.total_score}</span></div>
            <div>Entry: <span>₹${alert.entry_price}</span></div>
            <div>SL: <span>₹${alert.support}</span></div>
            <div>R:R: <span>${alert.rr_ratio}x</span></div>
        </div>
        <div class="alert-signals">
            ${alert.signals.length > 0 ? alert.signals[0] : ''} ${alert.signals.length > 1 ? `+${alert.signals.length - 1} more` : ''}
        </div>
    `;
    return el;
}

// Modal controls
function openTradeModal() {
    document.getElementById('trade-modal').style.display = 'flex';
}

function closeTradeModal() {
    document.getElementById('trade-modal').style.display = 'none';
}

async function submitTrade() {
    const symbol = document.getElementById('trade-symbol').value;
    const pnl = parseFloat(document.getElementById('trade-pnl').value);
    const isWin = document.getElementById('trade-result').value === 'win';
    
    if (!symbol || isNaN(pnl)) {
        alert("Please enter valid symbol and P&L");
        return;
    }
    
    try {
        const res = await fetch('/api/trade', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ symbol, pnl, is_win: isWin })
        });
        const data = await res.json();
        if (data.status === 'success') {
            closeTradeModal();
            fetchRisk();
        }
    } catch (e) {
        console.error("Error saving trade", e);
    }
}

function showToast(message, type='info', duration=null) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    const icon = type === 'info' ? '<div class="spinner"></div>' : (type === 'success' ? '✓' : '✗');
    
    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-message">${message}</div>
    `;
    
    container.appendChild(toast);
    
    if (duration) {
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }
    
    return toast;
}

function removeToast(toast) {
    if (toast) {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }
}

async function triggerEOD() {
    const toast = showToast("EOD Scan is running. This may take a while...", "info");
    try {
        const res = await fetch('/api/eod/run', {method: 'POST'});
        const data = await res.json();
        removeToast(toast);
        if (data.status === 'success') {
            showToast("EOD Scan completed successfully!", "success", 4000);
            fetchWatchlist();
        } else {
            showToast("EOD Scan failed: " + (data.message || "Unknown error"), "error", 5000);
        }
    } catch (e) {
        removeToast(toast);
        showToast("Error triggering EOD Scan", "error", 5000);
        console.error("Error running EOD Scan", e);
    }
}

async function triggerPreMarket() {
    const toast = showToast("Pre-Market Analysis is running...", "info");
    try {
        const res = await fetch('/api/premarket/run', {method: 'POST'});
        const data = await res.json();
        removeToast(toast);
        if (data.status === 'success') {
            showToast("Pre-Market analysis completed successfully!", "success", 4000);
        } else {
            showToast("Pre-Market analysis failed: " + (data.message || "Unknown error"), "error", 5000);
        }
    } catch (e) {
        removeToast(toast);
        showToast("Error triggering Pre-Market Analysis", "error", 5000);
        console.error("Error running Pre-Market Analysis", e);
    }
}

// Initial load
document.addEventListener('DOMContentLoaded', () => {
    connectWS();
    fetchScores();
    fetchAlerts();
    fetchRisk();
    fetchWatchlist();
    
    // Poll fallback every 30s
    setInterval(() => {
        fetchScores();
        fetchAlerts();
        fetchRisk();
        fetchWatchlist();
    }, 30000);
});
