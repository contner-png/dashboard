import numpy as np
from typing import Dict, Tuple


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


# =============================================================================
# 5-PILLAR PROFESSIONAL SCORING MODEL
# Inspired by: Seeking Alpha Quant, Goldman ActiveBeta, Zacks, CFRA
# Each pillar: 0-20 pts  |  Total: 0-100
# =============================================================================


def score_valuation(info: Dict) -> float:
    """
    Valuation Pillar (0-20 pts)
    Key insight from pros: Valuation is RELATIVE to growth + sector context.
    """
    pts = 0.0
    peg = info.get("pegRatio")
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    earnings_growth = info.get("earningsGrowth")

    # 1. PEG ratio (0-7 pts) — most widely accepted growth-adjusted valuation
    if _has(peg) and peg > 0:
        if peg < 1.0:
            pts += 7
        elif peg < 1.5:
            pts += 5
        elif peg < 2.0:
            pts += 3
        elif peg < 3.0:
            pts += 1
    else:
        pts += 3  # neutral if unavailable

    # 2. Forward PE vs Earnings Growth (proper PEG, 0-5 pts)
    if _has(fwd_pe) and _has(earnings_growth) and earnings_growth > 0:
        proper_peg = fwd_pe / (earnings_growth * 100)
        if proper_peg < 1.0:
            pts += 5
        elif proper_peg < 1.5:
            pts += 3
        elif proper_peg < 2.0:
            pts += 1
    elif _has(fwd_pe) and _has(trail_pe) and trail_pe > 0:
        # Fallback: forward discount implies growth even if growth not reported
        pe_discount = (trail_pe - fwd_pe) / trail_pe
        if pe_discount > 0.30:
            pts += 3
        elif pe_discount > 0.15:
            pts += 2
        elif pe_discount > 0:
            pts += 1
    else:
        pts += 2  # neutral

    # 3. Absolute Forward PE sanity check (0-4 pts)
    if _has(fwd_pe):
        if fwd_pe < 15:
            pts += 4
        elif fwd_pe < 25:
            pts += 2
        elif fwd_pe < 40:
            pts += 1
        else:
            pts -= 1  # penalty for very high absolute PE
    else:
        pts += 2  # neutral

    # 4. Price-to-Book (0-2 pts) — prevents PEG-only blindness
    if _has(pb):
        if pb < 2:
            pts += 2
        elif pb < 5:
            pts += 1
        elif pb > 15:
            pts -= 1
    else:
        pts += 1  # neutral

    # 5. PE expansion/contraction trend (0-2 pts)
    if _has(trail_pe) and _has(fwd_pe) and trail_pe > 0:
        pe_discount = (trail_pe - fwd_pe) / trail_pe
        if pe_discount > 0.30:
            pts += 2
        elif pe_discount > 0.15:
            pts += 1
        elif pe_discount < -0.10:  # PE expanding = getting more expensive
            pts -= 1

    return _clip(pts, 0, 20)


def score_growth(info: Dict) -> float:
    """
    Growth Pillar (0-20 pts)
    Key insight from Zacks: Earnings estimate revisions + growth trajectory
    """
    pts = 0.0
    earnings_growth = info.get("earningsGrowth")
    revenue_growth = info.get("revenueGrowth")
    rec_mean = info.get("recommendationMean")
    trail_pe = info.get("trailingPE")
    fwd_pe = info.get("forwardPE")

    # 1. Earnings growth (0-5 pts) — the "G" in PEG
    if _has(earnings_growth):
        eg = earnings_growth * 100  # convert decimal to pct
        if eg > 30:
            pts += 5
        elif eg > 15:
            pts += 3
        elif eg > 5:
            pts += 1
    else:
        pts += 2  # neutral

    # 2. Revenue growth (0-4 pts)
    if _has(revenue_growth):
        rg = revenue_growth * 100
        if rg > 20:
            pts += 4
        elif rg > 10:
            pts += 2
        elif rg > 0:
            pts += 1
    else:
        pts += 2  # neutral

    # 3. Analyst conviction (estimate revision proxy) (0-5 pts)
    # Zacks proved this is the #1 predictive factor
    if _has(rec_mean):
        if rec_mean <= 1.5:
            pts += 5  # Strong Buy consensus
        elif rec_mean <= 2.0:
            pts += 3  # Buy
        elif rec_mean <= 2.5:
            pts += 1  # Hold
        else:
            pts += 0  # Weak/Sell
    elif info.get("recommendationKey", "").lower() in ("buy", "strong_buy"):
        pts += 3  # fallback
    else:
        pts += 1  # neutral

    # 4. Forward PE < Trailing PE = earnings trajectory improving (0-2 pts)
    if _has(trail_pe) and _has(fwd_pe) and fwd_pe < trail_pe:
        pts += 2

    # 5. Growth consistency bonus (0-2 pts)
    if _has(earnings_growth) and _has(revenue_growth):
        if earnings_growth > 0 and revenue_growth > 0:
            pts += 2
        elif earnings_growth < 0 and revenue_growth < 0:
            pts -= 1  # both declining

    # 6. Earnings quarterly growth acceleration (0-2 pts)
    eqg = info.get("earningsQuarterlyGrowth")
    if _has(eqg) and _has(earnings_growth):
        if eqg > earnings_growth:
            pts += 2  # quarterly accelerating vs annual

    return _clip(pts, 0, 20)


def score_profitability(info: Dict) -> float:
    """
    Profitability Pillar (0-20 pts)
    Key insight from Seeking Alpha / Goldman Quality factor: high-quality
    companies compound capital better and are more resilient.
    """
    pts = 0.0
    roe = info.get("returnOnEquity")
    gross_margin = info.get("grossMargins")
    op_margin = info.get("operatingMargins")
    profit_margin = info.get("profitMargins")
    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")

    # 1. ROE (0-5 pts) — Buffett's favorite metric
    if _has(roe):
        roe_pct = roe * 100
        if roe_pct > 25:
            pts += 5
        elif roe_pct > 15:
            pts += 3
        elif roe_pct > 10:
            pts += 1
    else:
        pts += 2  # neutral

    # 2. Gross margin (0-4 pts) — pricing power
    if _has(gross_margin):
        gm = gross_margin * 100
        if gm > 40:
            pts += 4
        elif gm > 30:
            pts += 2
        elif gm > 20:
            pts += 1
    else:
        pts += 2  # neutral

    # 3. Operating margin (0-4 pts) — operational efficiency
    if _has(op_margin):
        om = op_margin * 100
        if om > 20:
            pts += 4
        elif om > 10:
            pts += 2
        elif om > 5:
            pts += 1
    else:
        pts += 2  # neutral

    # 4. FCF margin (0-4 pts) — cash generation quality
    if _has(fcf) and _has(revenue) and revenue > 0:
        fcf_margin = (fcf / revenue) * 100
        if fcf_margin > 15:
            pts += 4
        elif fcf_margin > 10:
            pts += 2
        elif fcf_margin > 5:
            pts += 1
    else:
        pts += 2  # neutral

    # 5. Profit margin (0-3 pts)
    if _has(profit_margin):
        pm = profit_margin * 100
        if pm > 15:
            pts += 3
        elif pm > 10:
            pts += 1
    else:
        pts += 1  # neutral

    return _clip(pts, 0, 20)


def score_momentum(
    history: Dict,
    price_vs_50ma: float,
    price_vs_200ma: float,
    macd_signal: str,
    volume_ratio: float,
    week_52_change: float,
    rsi: float,
) -> float:
    """
    Momentum Pillar (0-20 pts)
    Key insight from Goldman ActiveBeta: momentum persists. But we also
    reward healthy (not overheated) momentum with volume confirmation.
    """
    pts = 0.0

    # 1. Price vs 50MA (0-5 pts) — trend strength
    if _has(price_vs_50ma):
        if 5 <= price_vs_50ma <= 20:
            pts += 5  # healthy uptrend
        elif 0 <= price_vs_50ma < 5:
            pts += 3  # flat to slightly positive
        elif 20 < price_vs_50ma <= 35:
            pts += 3  # strong but getting extended
        elif price_vs_50ma > 35:
            pts += 1  # very extended, parabolic risk
        elif -10 <= price_vs_50ma < 0:
            pts += 1  # mild pullback within uptrend
        else:
            pts += 0  # significant downtrend
    else:
        pts += 2  # neutral

    # 2. Price vs 200MA (0-3 pts) — long-term trend health
    if _has(price_vs_200ma):
        if price_vs_200ma > 20:
            pts += 3
        elif price_vs_200ma > 0:
            pts += 2
        elif price_vs_200ma > -10:
            pts += 1
    else:
        pts += 2  # neutral

    # 3. 52-week return (0-4 pts) — 12m momentum (Goldman uses 11m)
    if _has(week_52_change):
        w52 = week_52_change * 100
        if w52 > 50:
            pts += 4
        elif w52 > 20:
            pts += 3
        elif w52 > 0:
            pts += 1
        elif w52 > -20:
            pts += 0
        else:
            pts -= 2  # severe 12m decline = broken momentum
    else:
        pts += 2  # neutral

    # 4. Volume confirmation (0-3 pts)
    if _has(volume_ratio):
        if volume_ratio > 1.2:
            pts += 3
        elif volume_ratio > 1.0:
            pts += 2
        elif volume_ratio > 0.9:
            pts += 1
    else:
        pts += 1  # neutral

    # 5. MACD (0-3 pts)
    if macd_signal in ("Bullish", "Bullish Crossover"):
        pts += 3
    elif macd_signal == "Bearish Crossover":
        pts += 0
    else:
        pts += 1  # neutral / bearish

    # 6. RSI — healthy momentum zone (50-70) is ideal (0-2 pts)
    if _has(rsi):
        if 50 <= rsi <= 70:
            pts += 2  # healthy momentum
        elif 40 <= rsi < 50 or 70 < rsi <= 75:
            pts += 1  # mild deviation
        elif rsi > 80 or rsi < 30:
            pts -= 1  # extreme overbought/oversold
    else:
        pts += 1  # neutral

    return _clip(pts, 0, 20)


def score_risk(
    info: Dict,
    exhaustion_level: str,
    week_52_high: float,
    week_52_low: float,
    current_price: float,
) -> float:
    """
    Risk / Stability Pillar (0-20 pts)
    Key insight: Low volatility + strong balance sheet + no exhaustion = hold.
    """
    pts = 0.0
    beta = info.get("beta")
    debt_equity = info.get("debtToEquity")
    current_ratio = info.get("currentRatio")

    # 1. Beta (0-5 pts) — volatility risk
    if _has(beta):
        if 0.8 <= beta <= 1.2:
            pts += 5  # market-like, predictable
        elif (0.5 <= beta < 0.8) or (1.2 < beta <= 1.5):
            pts += 3  # slightly defensive or aggressive
        elif 1.5 < beta <= 2.0:
            pts += 1  # high volatility
        elif beta > 2.0:
            pts += 0  # extreme volatility
        elif beta < 0.5:
            pts += 2  # very defensive
    else:
        pts += 3  # neutral

    # 2. Debt / Equity (0-4 pts) — balance sheet strength
    if _has(debt_equity):
        if debt_equity < 30:
            pts += 4
        elif debt_equity < 60:
            pts += 2
        elif debt_equity < 100:
            pts += 1
        else:
            pts += 0  # highly leveraged
    else:
        pts += 2  # neutral

    # 3. Current ratio (0-3 pts) — short-term liquidity
    if _has(current_ratio):
        if current_ratio > 2.0:
            pts += 3
        elif current_ratio > 1.5:
            pts += 2
        elif current_ratio > 1.0:
            pts += 1
        else:
            pts += 0  # potential liquidity issues
    else:
        pts += 2  # neutral

    # 4. Exhaustion level (0-5 pts) — multi-factor price stress signal
    exhaustion_pts = {"None": 5, "Building": 3, "High": 1, "Extreme": -2}
    pts += exhaustion_pts.get(exhaustion_level, 2)

    # 5. 52-week range width = volatility proxy (0-2 pts)
    # Very wide ranges = high uncertainty = penalty
    if _has(week_52_high) and _has(week_52_low) and week_52_low > 0:
        range_width = (week_52_high - week_52_low) / week_52_low * 100
        if range_width > 400:
            pts -= 1  # crypto-like volatility
        elif range_width < 50:
            pts += 1  # very stable
    elif _has(current_price) and _has(week_52_low) and week_52_low > 0:
        range_width = (current_price - week_52_low) / week_52_low * 100
        if range_width > 300:
            pts -= 1

    # 6. Quick ratio bonus if available (0-1 pt)
    qr = info.get("quickRatio")
    if _has(qr) and qr > 1.0:
        pts += 1

    return _clip(pts, 0, 20)


# =============================================================================
# LEGACY SCORES (kept for backward compat — not used in new composite)
# =============================================================================

def calculate_technical_score(history: Dict, indicators: Dict) -> int:
    """Legacy technical score (0-4). Kept for backward compatibility."""
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
    """Legacy commentary score (0-4). Kept for backward compatibility."""
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


# =============================================================================
# NEW COMPOSITE BUY SCORE
# =============================================================================

def _reality_check_adjustments(
    base_score: float,
    technical_score: int,
    commentary_score: int,
    target_upside: float,
    info: Dict,
    exhaustion_level: str,
) -> Tuple[float, Dict[str, float]]:
    """
    Apply cross-check adjustments to the 5-pillar base score.
    These catch cases where fundamentals look great but the market disagrees,
    or where technicals/commentary provide confirming/contradicting signals.
    """
    adjustments = {}

    # 1. Technical Score cross-check (-4 to +4 pts)
    # High technical score = confirming signal that the chart supports fundamentals
    tech_adj = 0.0
    if technical_score == 4:
        tech_adj = 4
    elif technical_score == 3:
        tech_adj = 2
    elif technical_score == 2:
        tech_adj = 0
    elif technical_score == 1:
        tech_adj = -2
    else:
        tech_adj = -4
    adjustments["technical_crosscheck"] = tech_adj

    # 2. Commentary Score cross-check (-3 to +3 pts)
    # High commentary = fundamentals confirmed by analyst consensus
    comm_adj = 0.0
    if commentary_score == 4:
        comm_adj = 3
    elif commentary_score == 3:
        comm_adj = 1
    elif commentary_score == 2:
        comm_adj = 0
    elif commentary_score == 1:
        comm_adj = -2
    else:
        comm_adj = -3
    adjustments["commentary_crosscheck"] = comm_adj

    # 3. Target Upside Reality Check (-6 to +4 pts)
    # If analysts collectively see negative upside, the market is saying
    # "fundamentals are priced in" regardless of how good they look
    target_adj = 0.0
    if _has(target_upside):
        if target_upside > 50:
            target_adj = 4  # analysts see huge upside = strong confirm
        elif target_upside > 30:
            target_adj = 2
        elif target_upside > 15:
            target_adj = 1
        elif target_upside > 5:
            target_adj = 0
        elif target_upside > -5:
            target_adj = -1  # fairly priced, slightly overvalued
        elif target_upside > -15:
            target_adj = -3  # analysts think it's overvalued
        else:
            target_adj = -6  # analysts strongly think it's overvalued
    else:
        target_adj = 0  # no target data = neutral
    adjustments["target_reality"] = target_adj

    # 4. Earnings Surprise Momentum (-2 to +2 pts)
    # Earnings growth accelerating vs quarterly = momentum in fundamentals
    eqg = info.get("earningsQuarterlyGrowth")
    eg = info.get("earningsGrowth")
    surprise_adj = 0.0
    if _has(eqg) and _has(eg) and eg > 0:
        surprise_ratio = eqg / eg
        if surprise_ratio > 1.5:
            surprise_adj = 2  # quarterly earnings accelerating strongly
        elif surprise_ratio > 1.0:
            surprise_adj = 1  # modest acceleration
        elif surprise_ratio < 0.5:
            surprise_adj = -2  # quarterly decelerating vs annual
        elif surprise_ratio < 0.8:
            surprise_adj = -1
    adjustments["earnings_surprise"] = surprise_adj

    # 5. PEG Premium Bonus (-3 to +5 pts)
    # Best-in-class PEG (< 0.5) gets a direct boost regardless of sector
    peg = info.get("pegRatio")
    peg_adj = 0.0
    if _has(peg) and peg > 0:
        if peg < 0.5:
            peg_adj = 5  # exceptional value
        elif peg < 0.8:
            peg_adj = 3
        elif peg < 1.0:
            peg_adj = 1
        elif peg > 3.0:
            peg_adj = -3  # expensive even for growth
        elif peg > 2.0:
            peg_adj = -1
    adjustments["peg_premium"] = peg_adj

    # 6. Expected CAGR / Growth Trajectory (-3 to +5 pts)
    # High projected growth with reasonable PE = compounding machine
    earnings_growth = info.get("earningsGrowth")
    fwd_pe = info.get("forwardPE")
    cagr_adj = 0.0
    if _has(earnings_growth):
        eg_pct = earnings_growth * 100
        if eg_pct > 50:
            cagr_adj = 5  # hypergrowth
        elif eg_pct > 30:
            cagr_adj = 3
        elif eg_pct > 15:
            cagr_adj = 1
        elif eg_pct < 0:
            cagr_adj = -3  # earnings declining
        elif eg_pct < 5:
            cagr_adj = -1  # stagnant
    # Also check if proper PEG (FwdPE / earningsGrowth) is attractive
    if _has(fwd_pe) and _has(earnings_growth) and earnings_growth > 0:
        proper_peg = fwd_pe / (earnings_growth * 100)
        if proper_peg < 0.8:
            cagr_adj += 2  # growth is extremely cheap
        elif proper_peg < 1.2:
            cagr_adj += 1
    adjustments["growth_trajectory"] = cagr_adj

    # 7. Forward vs Trailing PE Trajectory (-3 to +5 pts)
    # Big discount = earnings inflection, small or negative = PE expansion risk
    trail_pe = info.get("trailingPE")
    pe_traj_adj = 0.0
    if _has(fwd_pe) and _has(trail_pe) and trail_pe > 0:
        discount = (trail_pe - fwd_pe) / trail_pe
        if discount > 0.50:
            pe_traj_adj = 5  # massive earnings inflection expected
        elif discount > 0.30:
            pe_traj_adj = 3
        elif discount > 0.15:
            pe_traj_adj = 1
        elif discount < -0.10:
            pe_traj_adj = -3  # PE expanding = getting more expensive
        elif discount < 0:
            pe_traj_adj = -1
    elif _has(fwd_pe) and not _has(trail_pe):
        # Only forward PE available = analyst-estimated, slight trust penalty
        pe_traj_adj = 0
    adjustments["pe_trajectory"] = pe_traj_adj

    # 8. Exhaustion Penalty (-0 to -8 pts)
    # Direct penalty for price exhaustion regardless of other factors
    exhaustion_adj = 0.0
    if exhaustion_level == "Extreme":
        exhaustion_adj = -8
    elif exhaustion_level == "High":
        exhaustion_adj = -4
    elif exhaustion_level == "Building":
        exhaustion_adj = -1
    else:
        exhaustion_adj = 1  # reward for no exhaustion
    adjustments["exhaustion_penalty"] = exhaustion_adj

    # 9. Analyst Consensus Strength (-2 to +2 pts)
    # Number of analysts covering = confidence in data quality
    num_analysts = info.get("numberOfAnalystOpinions")
    coverage_adj = 0.0
    if _has(num_analysts):
        if num_analysts >= 30:
            coverage_adj = 2  # well-covered, reliable consensus
        elif num_analysts >= 15:
            coverage_adj = 1
        elif num_analysts >= 5:
            coverage_adj = 0
        else:
            coverage_adj = -1  # thin coverage, targets less reliable
    else:
        coverage_adj = -1  # no analyst data = penalty for uncertainty
    adjustments["coverage_quality"] = coverage_adj

    total_adj = sum(adjustments.values())
    return total_adj, adjustments


def calculate_buy_score_v2(
    info: Dict,
    history: Dict,
    exhaustion_level: str,
    price_vs_50ma: float,
    price_vs_200ma: float,
    macd_signal: str,
    volume_ratio: float,
    week_52_change: float,
    rsi: float,
    technical_score: int = 0,
    commentary_score: int = 0,
    target_upside: float = None,
) -> Tuple[int, Dict[str, float], Dict[str, float]]:
    """
    Professional 5-pillar composite Buy Score (0-100) with reality checks.

    Returns:
        (buy_score, pillar_scores, adjustments)
        pillar_scores = {"valuation": x, "growth": x, "profitability": x,
                         "momentum": x, "risk": x}
        adjustments = {"technical_crosscheck": x, "commentary_crosscheck": x,
                       "target_reality": x, "earnings_surprise": x, "coverage_quality": x}
    """
    val = score_valuation(info)
    growth = score_growth(info)
    prof = score_profitability(info)
    mom = score_momentum(
        history, price_vs_50ma, price_vs_200ma, macd_signal,
        volume_ratio, week_52_change, rsi,
    )
    risk = score_risk(
        info, exhaustion_level,
        info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow"),
        info.get("currentPrice") or info.get("regularMarketPrice"),
    )

    base = val + growth + prof + mom + risk

    # Apply reality-check adjustments
    adj_total, adjustments = _reality_check_adjustments(
        base, technical_score, commentary_score, target_upside, info, exhaustion_level
    )

    total = base + adj_total
    total = _clip(total, 0, 100)

    pillars = {
        "valuation": round(val, 1),
        "growth": round(growth, 1),
        "profitability": round(prof, 1),
        "momentum": round(mom, 1),
        "risk": round(risk, 1),
    }

    # Store adjustment values rounded
    adj_display = {k: round(v, 1) for k, v in adjustments.items()}

    return int(round(total)), pillars, adj_display


# Legacy wrapper for backward compatibility
def calculate_buy_score(
    technical_score: int,
    commentary_score: int,
    exhaustion_level: str,
    rsi: float,
    peg: float,
    trailing_pe: float,
    forward_pe: float,
    est_growth: float,
    beta: float,
    target_upside: float,
    week_52_high: float,
    week_52_low: float,
    current_price: float,
    macd_signal: str,
    price_vs_50ma: float,
    price_vs_200ma: float,
    volume_ratio: float,
) -> int:
    """DEPRECATED: Legacy scoring. Use calculate_buy_score_v2()."""
    # Build minimal info dict from legacy params for v2 compatibility
    info = {
        "pegRatio": peg,
        "trailingPE": trailing_pe,
        "forwardPE": forward_pe,
        "earningsGrowth": est_growth / 100 if est_growth else None,
        "beta": beta,
        "currentPrice": current_price,
        "revenueGrowth": None,
        "returnOnEquity": None,
        "grossMargins": None,
        "operatingMargins": None,
        "profitMargins": None,
        "freeCashflow": None,
        "totalRevenue": None,
        "debtToEquity": None,
        "currentRatio": None,
        "quickRatio": None,
        "priceToBook": None,
        "recommendationMean": None,
        "earningsQuarterlyGrowth": None,
        "fiftyTwoWeekHigh": week_52_high,
        "fiftyTwoWeekLow": week_52_low,
    }
    history = {"Close": None, "Volume": None}
    score, _, _ = calculate_buy_score_v2(
        info=info,
        history=history,
        exhaustion_level=exhaustion_level,
        price_vs_50ma=price_vs_50ma,
        price_vs_200ma=price_vs_200ma,
        macd_signal=macd_signal,
        volume_ratio=volume_ratio,
        week_52_change=None,
        rsi=rsi,
        technical_score=technical_score,
        commentary_score=commentary_score,
        target_upside=target_upside,
    )
    return score


def rating_band(score: int) -> str:
    """
    Map Buy Score to discrete rating band.
    Calibrated for the enhanced scoring range (13-96):
    """
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
