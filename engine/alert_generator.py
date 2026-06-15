import json
from datetime import datetime
from engine.risk_manager import RiskManager

class AlertGenerator:
    def __init__(self, db=None):
        self.db = db
        self.risk_manager = RiskManager(db)
        
    def generate_alert(self, symbol: str, scores: dict, data: dict) -> dict:
        """
        Generate full alert matching spec Section 7 format.
        """
        oi_result = scores['oi']
        price_result = scores['price']
        space_result = scores['space']
        volume_result = scores['volume']
        rs_result = scores['rs']
        market_result = scores['market']
        
        total_score = sum([s.score for s in scores.values()])
        
        entry_price = data.get('current_price', 0)
        support = space_result.details.get('support_price', entry_price * 0.99)
        resistance = space_result.details.get('resistance_price', entry_price * 1.01)
        atr = space_result.details.get('atr', 0)
        
        rr_ratio = self.risk_manager.calculate_rr_ratio(entry_price, support, resistance)
        position_size = self.risk_manager.calculate_position_size(entry_price, support)
        
        # Build signals list
        signals = []
        if oi_result.details.get('put_writing'): signals.append("✅ Put Writing confirmed")
        if oi_result.details.get('call_writing'): signals.append("✅ Call Writing confirmed")
        if oi_result.details.get('pcr_rising'): signals.append("✅ PCR Rising")
        if price_result.details.get('vwap_holding'): signals.append("✅ VWAP holding")
        if volume_result.score > 0: signals.append(f"✅ RVOL {volume_result.details.get('rvol_value', 0):.1f}x")
        if rs_result.score > 0: signals.append("✅ Sector leader")
        
        adx_cat = price_result.details.get('adx_category')
        if adx_cat == 'Fresh move': signals.append(f"⚠️ ADX {price_result.details.get('adx_value', 0):.0f} (Fresh move)")
        elif adx_cat == 'Strong trend': signals.append(f"⚠️ ADX {price_result.details.get('adx_value', 0):.0f} (Strong trend)")
        
        alert = {
            'symbol': symbol,
            'total_score': total_score,
            'entry_price': entry_price,
            'support': support,
            'resistance': resistance,
            'atr': atr,
            'rr_ratio': rr_ratio,
            'score_breakdown': {k: v.score for k, v in scores.items()},
            'signals': signals,
            'position_size': position_size,
            'max_loss': self.risk_manager.capital * 0.01, # Using 1% risk rule
            'triggered_at': datetime.now()
        }
        return alert

    def format_alert_text(self, alert: dict) -> str:
        """Format alert as text string matching the spec's emoji format."""
        
        breakdown = alert.get('score_breakdown', {})
        signals = "\n".join(alert.get('signals', []))
        
        text = f"""🎯 ALERT: {alert['symbol']}
Score: {alert['total_score']}/100
Time: {alert['triggered_at'].strftime('%I:%M %p')}

Entry Zone : ₹{alert['entry_price']:.2f}
Support/SL : ₹{alert['support']:.2f}
Resistance : ₹{alert['resistance']:.2f}
ATR        : ₹{alert['atr']:.2f}
R:R Ratio  : {alert['rr_ratio']}x

Score Breakdown:
OI Score    : {breakdown.get('oi', 0)}/25
Price Score : {breakdown.get('price', 0)}/20
Volume Score: {breakdown.get('volume', 0)}/15
Space Score : {breakdown.get('space', 0)}/15
RS Score    : {breakdown.get('rs', 0)}/15
Market Score: {breakdown.get('market', 0)}/10

Signals:
{signals}

Position Size: {alert['position_size']} shares
Max Loss    : ₹{alert['max_loss']:.0f}
"""
        return text
