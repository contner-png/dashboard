"""
Buy Score framework (v3)
========================

A deliberately simple, coverage-aware composite built only from free
Yahoo Finance data:

1. Five pillars, each scored 0-20 from whatever data is available:
       Valuation - Growth - Profitability - Momentum - Risk
2. The pillars are blended with fixed weights (growth/quality tilt).
   Pillars with no data are dropped and the remaining weights are
   renormalized, so missing data never silently counts as zero.
3. Four transparent conviction adjustments (capped at +/-12 total):
       value premium (PEG) - analyst conviction (target upside)
       earnings trajectory (fwd vs trailing PE) - trend exhaustion
4. `data_coverage` (0-100) reports how much of the model had data.
   Non-equities (ETFs, crypto, indexes) or coverage < 60 fall back to
   "Technical" mode: momentum + risk only, no adjustments.

Score 0-100 -> rating bands: 80+ Strong Buy, 65+ Buy, 45+ Hold,
30+ Sell, else Strong Sell.
"""

import math
import numpy as np
from typing import Dict, Tuple

PILLAR_WEIGHTS = {
    "valuation": 0.22,
    "growth": 0.24,
    "profitability": 0.20,
    "momentum": 0.22,
    "risk": 0.12,
}

MAX_ADJUSTMENT = 12.0


def _clip(v: float, lo: float, hi: float) -> float:
    """Safe clip that handles NaN."""
    if v is None or (isinstance(v, float) and v != v):
        return lo
    return max(lo, min(hi, v))


def _has(val) -> bool:
    if val is None:
        return False
    if isinstance(val, float) and val != val:
        return False
    if isinstance(val, str):
        return False
    return True


def _normalize_pillar(earned: float, possible: float):
    if possible <= 0:
        return None
    return round(_clip((earned / possible) * 20, 0, 20), 1)


def _score_growth_rate(growth_pct: float):
    if growth_pct is None or (isinstance(growth_pct, float) and growth_pct != growth_pct):
        return None
    if growth_pct >= 40:
        return 20.0
    if growth_pct >= 25:
        return 17.0
    if growth_pct >= 10:
        return 14.0
    if growth_pct >= 0:
        return 10.0
    if growth_pct >= -10:
        return 7.0
    if growth_pct >= -25:
        return 4.0
    return 1.0


def _score_scale(net_income: float):
    if net_income is None or (isinstance(net_income, float) and net_income != net_income):
        return None
    if net_income <= 0:
        return 0.0
    log_val = math.log10(net_income)
    scaled = (log_val - 7.0) / 4.0 * 20.0
    return _clip(scaled, 0, 20)


def _is_non_equity(info: Dict) -> bool:
    quote_type = (info.get("quoteType") or "").upper()
    if quote_type in {"ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY"}:
        return True
    country = (info.get("country") or "").strip().upper()
    if country and country not in {"UNITED STATES", "US", "USA"}:
        return True
    return False


# =============================================================================
# PILLARS — each returns (points_earned, points_possible); max possible = 20
# =============================================================================


def score_valuation(info: Dict) -> Tuple[float, float]:
    """Valuation pillar (0-20): growth-adjusted and absolute valuation."""
    earned = 0.0
    possible = 0.0
    peg = info.get("pegRatio")
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    earnings_growth = info.get("earningsGrowth")

    # 1. PEG ratio (0-7 pts) — most widely accepted growth-adjusted valuation
    if _has(peg) and peg > 0:
        possible += 7
        if peg < 1.0:
            earned += 7
        elif peg < 1.5:
            earned += 5
        elif peg < 2.0:
            earned += 3
        elif peg < 3.0:
            earned += 1

    # 2. Forward PE vs earnings growth ("proper PEG", 0-5 pts)
    if _has(fwd_pe) and _has(earnings_growth) and earnings_growth > 0:
        possible += 5
        proper_peg = fwd_pe / (earnings_growth * 100)
        if proper_peg < 1.0:
            earned += 5
        elif proper_peg < 1.5:
            earned += 3
        elif proper_peg < 2.0:
            earned += 1
    elif _has(fwd_pe) and _has(trail_pe) and trail_pe > 0:
        possible += 5
        pe_discount = (trail_pe - fwd_pe) / trail_pe
        if pe_discount > 0.30:
            earned += 3
        elif pe_discount > 0.15:
            earned += 2
        elif pe_discount > 0:
            earned += 1

    # 3. Absolute forward PE sanity check (0-4 pts)
    if _has(fwd_pe):
        possible += 4
        if fwd_pe < 15:
            earned += 4
        elif fwd_pe < 25:
            earned += 2
        elif fwd_pe < 40:
            earned += 1
        else:
            earned -= 1  # penalty for very high absolute PE

    # 4. Price-to-book (0-2 pts) — prevents PEG-only blindness
    if _has(pb):
        possible += 2
        if pb < 2:
            earned += 2
        elif pb < 5:
            earned += 1
        elif pb > 15:
            earned -= 1

    # 5. PE expansion/contraction trend (0-2 pts)
    if _has(trail_pe) and _has(fwd_pe) and trail_pe > 0:
        possible += 2
        pe_discount = (trail_pe - fwd_pe) / trail_pe
        if pe_discount > 0.30:
            earned += 2
        elif pe_discount > 0.15:
            earned += 1
        elif pe_discount < -0.10:  # PE expanding = getting more expensive
            earned -= 1

    return earned, possible


def score_growth(info: Dict) -> Tuple[float, float]:
    """Growth pillar (0-20): earnings/revenue growth and analyst conviction."""
    earned = 0.0
    possible = 0.0
    earnings_growth = info.get("earningsGrowth")
    revenue_growth = info.get("revenueGrowth")
    rec_mean = info.get("recommendationMean")
    trail_pe = info.get("trailingPE")
    fwd_pe = info.get("forwardPE")

    # 1. Earnings growth (0-5 pts) — the "G" in PEG
    if _has(earnings_growth):
        possible += 5
        eg = earnings_growth * 100
        if eg > 30:
            earned += 5
        elif eg > 15:
            earned += 3
        elif eg > 5:
            earned += 1

    # 2. Revenue growth (0-4 pts)
    if _has(revenue_growth):
        possible += 4
        rg = revenue_growth * 100
        if rg > 20:
            earned += 4
        elif rg > 10:
            earned += 2
        elif rg > 0:
            earned += 1

    # 3. Analyst conviction (estimate revision proxy, 0-5 pts)
    rec_key = (info.get("recommendationKey") or "").lower()
    if _has(rec_mean):
        possible += 5
        if rec_mean <= 1.5:
            earned += 5  # Strong Buy consensus
        elif rec_mean <= 2.0:
            earned += 3  # Buy
        elif rec_mean <= 2.5:
            earned += 1  # Hold
    elif rec_key:
        possible += 5
        if rec_key in ("buy", "strong_buy"):
            earned += 3
        elif rec_key in ("hold", "neutral"):
            earned += 1

    # 4. Forward PE < trailing PE = earnings trajectory improving (0-2 pts)
    if _has(trail_pe) and _has(fwd_pe):
        possible += 2
        if fwd_pe < trail_pe:
            earned += 2

    # 5. Growth consistency bonus (0-2 pts)
    if _has(earnings_growth) and _has(revenue_growth):
        possible += 2
        if earnings_growth > 0 and revenue_growth > 0:
            earned += 2
        elif earnings_growth < 0 and revenue_growth < 0:
            earned -= 1  # both declining

    # 6. Quarterly earnings acceleration (0-2 pts)
    eqg = info.get("earningsQuarterlyGrowth")
    if _has(eqg) and _has(earnings_growth):
        possible += 2
        if eqg > earnings_growth:
            earned += 2

    return earned, possible


def score_profitability(info: Dict) -> Tuple[float, float]:
    """Profitability pillar (0-20): margins/returns, profit growth, and scale."""
    efficiency_earned = 0.0
    efficiency_possible = 0.0
    roe = info.get("returnOnEquity")
    gross_margin = info.get("grossMargins")
    op_margin = info.get("operatingMargins")
    profit_margin = info.get("profitMargins")
    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")

    # 1. ROE (0-5 pts)
    if _has(roe):
        efficiency_possible += 5
        roe_pct = roe * 100
        if roe_pct > 25:
            efficiency_earned += 5
        elif roe_pct > 15:
            efficiency_earned += 3
        elif roe_pct > 10:
            efficiency_earned += 1

    # 2. Gross margin (0-4 pts) — pricing power
    if _has(gross_margin):
        efficiency_possible += 4
        gm = gross_margin * 100
        if gm > 40:
            efficiency_earned += 4
        elif gm > 30:
            efficiency_earned += 2
        elif gm > 20:
            efficiency_earned += 1

    # 3. Operating margin (0-4 pts)
    if _has(op_margin):
        efficiency_possible += 4
        om = op_margin * 100
        if om > 20:
            efficiency_earned += 4
        elif om > 10:
            efficiency_earned += 2
        elif om > 5:
            efficiency_earned += 1

    # 4. FCF margin (0-4 pts) — cash generation quality
    if _has(fcf) and _has(revenue) and revenue > 0:
        efficiency_possible += 4
        fcf_margin = (fcf / revenue) * 100
        if fcf_margin > 15:
            efficiency_earned += 4
        elif fcf_margin > 10:
            efficiency_earned += 2
        elif fcf_margin > 5:
            efficiency_earned += 1

    # 5. Profit margin (0-3 pts)
    if _has(profit_margin):
        efficiency_possible += 3
        pm = profit_margin * 100
        if pm > 15:
            efficiency_earned += 3
        elif pm > 10:
            efficiency_earned += 1

    efficiency_score = _normalize_pillar(efficiency_earned, efficiency_possible)

    growth_scores = []
    for growth_val in (info.get("netIncomeGrowth"), info.get("freeCashflowGrowth")):
        if _has(growth_val):
            score = _score_growth_rate(growth_val)
            if score is not None:
                growth_scores.append(score)
    growth_score = sum(growth_scores) / len(growth_scores) if growth_scores else None

    net_income = info.get("netIncome") or info.get("netIncomeToCommon") or info.get("netIncomeToCommonStockholders")
    scale_score = _score_scale(net_income)

    weights = {"efficiency": 0.5, "growth": 0.35, "scale": 0.15}

    weighted_sum = 0.0
    weight_total = 0.0
    if efficiency_score is not None:
        weighted_sum += efficiency_score * weights["efficiency"]
        weight_total += weights["efficiency"]
    if growth_score is not None:
        weighted_sum += growth_score * weights["growth"]
        weight_total += weights["growth"]
    if scale_score is not None:
        weighted_sum += scale_score * weights["scale"]
        weight_total += weights["scale"]

    if weight_total <= 0:
        return 0.0, 0.0

    weighted_score = weighted_sum / weight_total
    possible = 20 * weight_total
    earned = weighted_score * weight_total
    return earned, possible


def score_momentum(
    history: Dict,
    price_vs_50ma: float,
    price_vs_200ma: float,
    macd_signal: str,
    volume_ratio: float,
    week_52_change: float,
    rsi: float,
) -> Tuple[float, float]:
    """Momentum pillar (0-20): trend strength with blow-off protection."""
    earned = 0.0
    possible = 0.0

    # 1. Price vs 50MA (0-5 pts) — trend strength
    if _has(price_vs_50ma):
        possible += 5
        if 5 <= price_vs_50ma <= 20:
            earned += 5  # healthy uptrend
        elif 0 <= price_vs_50ma < 5:
            earned += 3  # flat to slightly positive
        elif 20 < price_vs_50ma <= 35:
            earned += 3  # strong but getting extended
        elif price_vs_50ma > 35:
            earned += 1  # very extended, parabolic risk
        elif -10 <= price_vs_50ma < 0:
            earned += 1  # mild pullback within uptrend

    # 2. Price vs 200MA (0-3 pts) — long-term trend health
    if _has(price_vs_200ma):
        possible += 3
        if price_vs_200ma > 20:
            earned += 3
        elif price_vs_200ma > 0:
            earned += 2
        elif price_vs_200ma > -10:
            earned += 1

    # 3. 52-week return (0-4 pts) — 12m momentum
    if _has(week_52_change):
        possible += 4
        w52 = week_52_change * 100
        if w52 > 50:
            earned += 4
        elif w52 > 20:
            earned += 3
        elif w52 > 0:
            earned += 1
        elif w52 <= -20:
            earned -= 2  # severe 12m decline = broken momentum

    # 4. Volume confirmation (0-3 pts)
    if _has(volume_ratio):
        possible += 3
        if volume_ratio > 1.2:
            earned += 3
        elif volume_ratio > 1.0:
            earned += 2
        elif volume_ratio > 0.9:
            earned += 1

    # 5. MACD (0-3 pts)
    if macd_signal:
        possible += 3
        if macd_signal in ("Bullish", "Bullish Crossover"):
            earned += 3
        elif macd_signal == "Bearish Crossover":
            earned += 0
        else:
            earned += 1  # neutral / bearish

    # 6. RSI — healthy momentum zone (50-70) is ideal (0-2 pts)
    if _has(rsi):
        possible += 2
        if 50 <= rsi <= 70:
            earned += 2
        elif 40 <= rsi < 50 or 70 < rsi <= 75:
            earned += 1
        elif rsi > 80 or rsi < 30:
            earned -= 1  # extreme overbought/oversold

    return earned, possible


def score_risk(
    info: Dict,
    exhaustion_level: str,
    week_52_high: float,
    week_52_low: float,
    current_price: float,
) -> Tuple[float, float]:
    """Risk / stability pillar (0-20): volatility, balance sheet, price stress."""
    earned = 0.0
    possible = 0.0
    beta = info.get("beta")
    debt_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")

    # 1. Beta (0-5 pts) — volatility risk
    if _has(beta):
        possible += 5
        if 0.8 <= beta <= 1.2:
            earned += 5  # market-like, predictable
        elif (0.5 <= beta < 0.8) or (1.2 < beta <= 1.5):
            earned += 3
        elif beta < 0.5:
            earned += 2  # very defensive
        elif 1.5 < beta <= 2.0:
            earned += 1

    # 2. Debt / equity (0-4 pts) — balance sheet strength
    if _has(debt_equity):
        possible += 4
        if debt_equity < 30:
            earned += 4
        elif debt_equity < 60:
            earned += 2
        elif debt_equity < 100:
            earned += 1

    # 3. Current ratio (0-3 pts) — short-term liquidity
    if _has(current_ratio):
        possible += 3
        if current_ratio > 2.0:
            earned += 3
        elif current_ratio > 1.5:
            earned += 2
        elif current_ratio > 1.0:
            earned += 1

    # 4. Exhaustion level (0-5 pts) — multi-factor price stress signal
    if exhaustion_level:
        possible += 5
        exhaustion_pts = {"None": 5, "Building": 3, "High": 1, "Extreme": -2}
        earned += exhaustion_pts.get(exhaustion_level, 2)

    # 5. 52-week range width = volatility proxy (0-2 pts)
    if _has(week_52_high) and _has(week_52_low) and week_52_low > 0:
        possible += 2
        range_width = (week_52_high - week_52_low) / week_52_low * 100
        if range_width > 400:
            earned -= 1  # crypto-like volatility
        elif range_width < 50:
            earned += 1  # very stable
    elif _has(current_price) and _has(week_52_low) and week_52_low > 0:
        possible += 2
        range_width = (current_price - week_52_low) / week_52_low * 100
        if range_width > 300:
            earned -= 1

    # 6. Quick ratio bonus (0-1 pt)
    qr = info.get("quickRatio")
    if _has(qr):
        possible += 1
        if qr > 1.0:
            earned += 1

    return earned, possible


# =============================================================================
# CONVICTION ADJUSTMENTS — five transparent cross-checks, capped at +/-12
# =============================================================================

ADJUSTMENT_KEYS = ("value_premium", "analyst_conviction", "earnings_trajectory", "exhaustion", "intrinsic_value")


def _conviction_adjustments(
    info: Dict,
    target_upside: float,
    exhaustion_level: str,
    dcf_upside: float = None,
) -> Tuple[float, Dict[str, float]]:
    adjustments = {}

    # 1. Value premium (-4 to +5): best-in-class PEG earns a direct boost,
    #    expensive-even-for-growth gets dinged.
    peg = info.get("pegRatio")
    value_adj = 0.0
    if _has(peg) and peg > 0:
        if peg < 0.5:
            value_adj = 5
        elif peg < 0.8:
            value_adj = 3
        elif peg < 1.0:
            value_adj = 1
        elif peg > 3.0:
            value_adj = -4
        elif peg > 2.0:
            value_adj = -2
    adjustments["value_premium"] = value_adj

    # 2. Analyst conviction (-5 to +4): if consensus targets imply negative
    #    upside, the market says good fundamentals are already priced in.
    target_adj = 0.0
    if _has(target_upside):
        if target_upside > 40:
            target_adj = 4
        elif target_upside > 20:
            target_adj = 2
        elif target_upside > 10:
            target_adj = 1
        elif target_upside < -15:
            target_adj = -5
        elif target_upside < -5:
            target_adj = -2
    adjustments["analyst_conviction"] = target_adj

    # 3. Earnings trajectory (-3 to +3): forward PE far below trailing PE
    #    means analysts expect an earnings inflection; expansion is a warning.
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    traj_adj = 0.0
    if _has(fwd_pe) and _has(trail_pe) and trail_pe > 0:
        discount = (trail_pe - fwd_pe) / trail_pe
        if discount > 0.40:
            traj_adj = 3
        elif discount > 0.20:
            traj_adj = 2
        elif discount > 0.05:
            traj_adj = 1
        elif discount < -0.10:
            traj_adj = -3
        elif discount < 0:
            traj_adj = -1
    adjustments["earnings_trajectory"] = traj_adj

    # 4. Trend exhaustion (-6 to +1): direct penalty for blow-off conditions.
    exhaustion_map = {"Extreme": -6, "High": -3, "Building": -1, "None": 1}
    adjustments["exhaustion"] = float(exhaustion_map.get(exhaustion_level, 0))

    # 5. Intrinsic value (-4 to +4): DCF upside cross-check. Only present when
    #    the company has real positive FCF (the DCF returns None otherwise),
    #    so this never rewards story stocks on imaginary cash flows.
    dcf_adj = 0.0
    if _has(dcf_upside):
        if dcf_upside > 50:
            dcf_adj = 4
        elif dcf_upside > 25:
            dcf_adj = 3
        elif dcf_upside > 10:
            dcf_adj = 1
        elif dcf_upside < -40:
            dcf_adj = -4
        elif dcf_upside < -20:
            dcf_adj = -2
    adjustments["intrinsic_value"] = dcf_adj

    total = _clip(sum(adjustments.values()), -MAX_ADJUSTMENT, MAX_ADJUSTMENT)
    return total, adjustments


# =============================================================================
# COMPOSITE BUY SCORE
# =============================================================================


def calculate_buy_score(
    info: Dict,
    history: Dict,
    exhaustion_level: str,
    price_vs_50ma: float,
    price_vs_200ma: float,
    macd_signal: str,
    volume_ratio: float,
    week_52_change: float,
    rsi: float,
    target_upside: float = None,
    dcf_upside: float = None,
) -> Tuple[int, Dict[str, float], Dict[str, float], float, str]:
    """
    Coverage-aware 5-pillar composite Buy Score (0-100).

    Returns:
        (buy_score, pillar_scores, adjustments, data_coverage_pct, score_mode)
    """
    results = {
        "valuation": score_valuation(info),
        "growth": score_growth(info),
        "profitability": score_profitability(info),
        "momentum": score_momentum(
            history, price_vs_50ma, price_vs_200ma, macd_signal,
            volume_ratio, week_52_change, rsi,
        ),
        "risk": score_risk(
            info, exhaustion_level,
            info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow"),
            info.get("currentPrice") or info.get("regularMarketPrice"),
        ),
    }

    pillars = {name: _normalize_pillar(earned, possible) for name, (earned, possible) in results.items()}

    # Coverage: weighted share of the model that actually had data (each
    # pillar's possible points max out at 20).
    data_coverage = round(
        sum(PILLAR_WEIGHTS[name] * min(possible, 20) / 20 for name, (_, possible) in results.items()) * 100,
        1,
    )

    score_mode = "Equity"
    if _is_non_equity(info) or data_coverage < 60:
        score_mode = "Technical"

    if score_mode == "Technical":
        active = [name for name in ("momentum", "risk") if pillars[name] is not None]
        adjustments = {key: 0.0 for key in ADJUSTMENT_KEYS}
        adj_total = 0.0
    else:
        active = [name for name in PILLAR_WEIGHTS if pillars[name] is not None]
        adj_total, adjustments = _conviction_adjustments(info, target_upside, exhaustion_level, dcf_upside)

    weight_total = sum(PILLAR_WEIGHTS[name] for name in active)
    if weight_total > 0:
        base = sum(PILLAR_WEIGHTS[name] * (pillars[name] / 20 * 100) for name in active) / weight_total
    else:
        base = 0.0

    total = _clip(base + adj_total, 0, 100)
    adj_display = {k: round(v, 1) for k, v in adjustments.items()}

    return int(round(total)), pillars, adj_display, data_coverage, score_mode


# Backward-compatible alias (same return shape as before).
def calculate_buy_score_v2(*args, technical_score=0, commentary_score=0, **kwargs):
    kwargs.pop("technical_score", None)
    kwargs.pop("commentary_score", None)
    return calculate_buy_score(*args, **kwargs)


# =============================================================================
# LEGACY SCORES (kept for reference columns in the DB)
# =============================================================================

def calculate_technical_score(history: Dict, indicators: Dict) -> int:
    """Legacy technical score (0-4)."""
    from src.indicators import calc_price_vs_ma, calc_rsi, calc_macd
    prices = history["Close"]
    volume = history["Volume"]
    score = 0
    vs_50 = calc_price_vs_ma(prices, 50)
    vs_200 = calc_price_vs_ma(prices, 200)
    if not np.isnan(vs_50) and not np.isnan(vs_200):
        if vs_50 > 0 and vs_200 > 0:
            score += 1
    rsi = calc_rsi(prices)
    if not np.isnan(rsi) and 50 <= rsi <= 70:
        score += 1
    vol_20 = volume.tail(20).mean()
    vol_50 = volume.tail(50).mean()
    if not np.isnan(vol_20) and not np.isnan(vol_50):
        if vol_20 > vol_50:
            score += 1
    _, _, macd_signal = calc_macd(prices)
    if macd_signal in ("Bullish", "Bullish Crossover"):
        score += 1
    return score


def calculate_commentary_score(info: Dict) -> int:
    """Legacy commentary score (0-4)."""
    score = 0
    rec = info.get("recommendationKey", "").lower()
    if rec in ("buy", "strong_buy"):
        score += 1
    trail_pe = info.get("trailingPE")
    fwd_pe = info.get("forwardPE")
    if trail_pe and fwd_pe and fwd_pe < trail_pe:
        score += 1
    rev_growth = info.get("revenueGrowth")
    if rev_growth and rev_growth > 0.10:
        score += 1
    peg = info.get("pegRatio")
    if peg and peg < 2.0:
        score += 1
    return max(0, score)


def rating_band(score: int) -> str:
    """Map Buy Score to a discrete rating band."""
    if score >= 80:
        return "Strong Buy"
    elif score >= 65:
        return "Buy"
    elif score >= 45:
        return "Hold"
    elif score >= 30:
        return "Sell"
    else:
        return "Strong Sell"
