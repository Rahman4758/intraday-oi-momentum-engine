"""
OI (Open Interest) Scorer — 25 Points Maximum.

Analyses option chain data to detect institutional positioning via
Put Writing, Call Writing, PCR shifts, and multi-strike confirmation.
"""

import logging
from typing import Optional

from scorers.base import BaseScorer, ScoreResult
from config.constants import (
    OI_MAX_SCORE,
    OI_PUT_MAX_SCORE,
    OI_CALL_MAX_SCORE,
    OI_PCR_MAX_SCORE,
    OI_CHANGE_THRESHOLD_PCT,
    OI_PCR_PENALTY,
    OI_MULTI_STRIKE_TOP_N,
)

logger = logging.getLogger(__name__)


class OIScorer(BaseScorer):
    """Scores stocks based on Open Interest analysis of the option chain.

    Evaluates:
    - Put OI changes and premium direction (12 pts)
    - Call OI changes and premium direction (8 pts)
    - PCR shift relative to baseline (5 pts)
    - Multi-strike confirmation across top Put OI strikes
    """

    def calculate(self, symbol: str, data: dict) -> ScoreResult:
        """Calculate OI score for a symbol.

        Args:
            symbol: Stock ticker symbol.
            data: Dict with keys:
                - current_option_chain: list of strike dicts
                - baseline_option_chain: list of strike dicts
                - current_pcr: float
                - baseline_pcr: float
                - current_price: float
        """
        logger.info("Calculating OI score for %s", symbol)

        current_chain: list = data.get("current_option_chain", [])
        baseline_chain: list = data.get("baseline_option_chain", [])
        current_pcr: float = data.get("current_pcr", 0.0)
        baseline_pcr: float = data.get("baseline_pcr", 0.0)
        current_price: float = data.get("current_price", 0.0)

        # Build baseline lookup by strike price
        baseline_map: dict = {
            s["strike_price"]: s for s in baseline_chain
        }

        # -----------------------------------------------------------
        # Per-strike analysis: compute OI changes and classify action
        # -----------------------------------------------------------
        strike_analyses: list[dict] = []

        for strike in current_chain:
            sp = strike["strike_price"]
            baseline = baseline_map.get(sp)
            if baseline is None:
                continue

            # Put OI change
            base_put_oi = baseline.get("put_oi", 0)
            curr_put_oi = strike.get("put_oi", 0)
            put_oi_change_pct = (
                ((curr_put_oi - base_put_oi) / base_put_oi * 100)
                if base_put_oi > 0 else 0.0
            )

            # Put premium direction
            base_put_prem = baseline.get("put_premium", 0.0)
            curr_put_prem = strike.get("put_premium", 0.0)
            put_premium_decreased = curr_put_prem < base_put_prem

            # Call OI change
            base_call_oi = baseline.get("call_oi", 0)
            curr_call_oi = strike.get("call_oi", 0)
            call_oi_change_pct = (
                ((curr_call_oi - base_call_oi) / base_call_oi * 100)
                if base_call_oi > 0 else 0.0
            )

            # Call premium direction
            base_call_prem = baseline.get("call_premium", 0.0)
            curr_call_prem = strike.get("call_premium", 0.0)
            call_premium_decreased = curr_call_prem < base_call_prem

            # Classify put action
            put_action = "noise"
            if put_oi_change_pct > OI_CHANGE_THRESHOLD_PCT:
                put_action = "put_writing" if put_premium_decreased else "put_buying"

            # Classify call action
            call_action = "noise"
            if call_oi_change_pct > OI_CHANGE_THRESHOLD_PCT:
                call_action = "call_writing" if call_premium_decreased else "call_buying"

            strike_analyses.append({
                "strike_price": sp,
                "put_oi": curr_put_oi,
                "put_oi_change_pct": round(put_oi_change_pct, 2),
                "put_action": put_action,
                "put_premium_decreased": put_premium_decreased,
                "call_oi": curr_call_oi,
                "call_oi_change_pct": round(call_oi_change_pct, 2),
                "call_action": call_action,
                "call_premium_decreased": call_premium_decreased,
            })

        # -----------------------------------------------------------
        # ATM strike detection
        # -----------------------------------------------------------
        atm_strike: Optional[float] = None
        if strike_analyses and current_price > 0:
            atm_strike = min(
                strike_analyses,
                key=lambda s: abs(s["strike_price"] - current_price),
            )["strike_price"]

        # -----------------------------------------------------------
        # Multi-strike confirmation (top 3 by Put OI)
        # -----------------------------------------------------------
        sorted_by_put_oi = sorted(
            strike_analyses, key=lambda s: s["put_oi"], reverse=True
        )
        top_strikes = sorted_by_put_oi[:OI_MULTI_STRIKE_TOP_N]

        put_writing_count = sum(
            1 for s in top_strikes if s["put_action"] == "put_writing"
        )
        atm_has_put_writing = any(
            s["strike_price"] == atm_strike and s["put_action"] == "put_writing"
            for s in top_strikes
        )

        if put_writing_count >= 2:
            multi_strike_confirmation = "strong"
        elif atm_has_put_writing:
            multi_strike_confirmation = "weak"
        else:
            multi_strike_confirmation = "none"

        # -----------------------------------------------------------
        # Aggregate put/call action across ALL strikes
        # -----------------------------------------------------------
        any_put_writing = any(s["put_action"] == "put_writing" for s in strike_analyses)
        any_put_buying = any(s["put_action"] == "put_buying" for s in strike_analyses)
        any_call_writing = any(s["call_action"] == "call_writing" for s in strike_analyses)
        any_call_buying = any(s["call_action"] == "call_buying" for s in strike_analyses)

        # -----------------------------------------------------------
        # Score: Put OI Analysis (12 pts)
        # -----------------------------------------------------------
        auto_skip = False
        skip_reasons: list[str] = []

        # -----------------------------------------------------------
        # Pillar 3: The Path Clearer (Strict OI Ratio >= 0.40)
        # -----------------------------------------------------------
        if current_price > 0 and strike_analyses:
            sorted_by_strike = sorted(strike_analyses, key=lambda s: s["strike_price"])
            # Find the 2 strikes immediately above current price
            resistance_strikes = [s for s in sorted_by_strike if s["strike_price"] > current_price][:2]
            
            if len(resistance_strikes) >= 2:
                total_res_put_oi = sum(s["put_oi"] for s in resistance_strikes)
                total_res_call_oi = sum(s["call_oi"] for s in resistance_strikes)
                
                res_ratio = (total_res_put_oi / total_res_call_oi) if total_res_call_oi > 0 else 1.0
                
                if res_ratio < 0.40:
                    auto_skip = True
                    skip_reasons.append(f"Resistance Path Blocked (Put/Call OI Ratio {res_ratio:.2f} < 0.40 on next 2 strikes)")

        put_score: float = 0.0
        if any_put_writing:
            put_score = OI_PUT_MAX_SCORE
        if any_put_buying and not any_put_writing:
            auto_skip = True
            skip_reasons.append("Put Buying detected (bearish)")

        # Apply multi-strike scaling to put score
        if multi_strike_confirmation == "weak":
            put_score = put_score * 0.5
        elif multi_strike_confirmation == "none":
            put_score = 0.0

        # -----------------------------------------------------------
        # Score: Call OI Analysis (8 pts)
        # -----------------------------------------------------------
        call_score: float = 0.0
        if any_call_writing:
            call_score = OI_CALL_MAX_SCORE
        if any_call_buying and not any_call_writing:
            auto_skip = True
            skip_reasons.append("Call Buying detected (bearish)")

        # -----------------------------------------------------------
        # Score: PCR Shift (5 pts)
        # -----------------------------------------------------------
        pcr_score: float = 0.0
        pcr_rising = False
        if current_pcr > baseline_pcr:
            pcr_score = OI_PCR_MAX_SCORE
            pcr_rising = True
        elif current_pcr < baseline_pcr:
            pcr_score = OI_PCR_PENALTY  # negative penalty

        # -----------------------------------------------------------
        # Compute aggregate OI change %s for details
        # -----------------------------------------------------------
        avg_put_oi_change = (
            sum(s["put_oi_change_pct"] for s in strike_analyses) / len(strike_analyses)
            if strike_analyses else 0.0
        )
        avg_call_oi_change = (
            sum(s["call_oi_change_pct"] for s in strike_analyses) / len(strike_analyses)
            if strike_analyses else 0.0
        )

        total_score = put_score + call_score + pcr_score
        # Clamp score to [0, max]
        total_score = max(0.0, min(total_score, OI_MAX_SCORE))

        skip_reason: Optional[str] = "; ".join(skip_reasons) if skip_reasons else None

        details = {
            "put_writing": any_put_writing,
            "call_writing": any_call_writing,
            "pcr_rising": pcr_rising,
            "put_oi_change_pct": round(avg_put_oi_change, 2),
            "call_oi_change_pct": round(avg_call_oi_change, 2),
            "multi_strike_confirmation": multi_strike_confirmation,
            "put_score": round(put_score, 2),
            "call_score": round(call_score, 2),
            "pcr_score": round(pcr_score, 2),
            "current_pcr": round(current_pcr, 4),
            "baseline_pcr": round(baseline_pcr, 4),
            "atm_strike": atm_strike,
            "top_strikes_analyzed": len(top_strikes),
            "strike_count": len(strike_analyses),
        }

        logger.info(
            "OI score for %s: %.1f/%.1f (auto_skip=%s, confirmation=%s)",
            symbol, total_score, OI_MAX_SCORE, auto_skip,
            multi_strike_confirmation,
        )

        return ScoreResult(
            score=total_score,
            max_score=OI_MAX_SCORE,
            details=details,
            auto_skip=auto_skip,
            skip_reason=skip_reason,
        )
