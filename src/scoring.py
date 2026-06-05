import math
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


def _normalize_pillar(earned: float, possible: float):
    if possible <= 0:
        return None
    return round(_clip((earned / possible) * 20, 0, 20), 1)


def _normalize_total(earned: float, possible: float) -> float:
    if possible <= 0:
        return 0.0
    return _clip((earned / possible) * 100, 0, 100)


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
# 5-PILLAR PROFESSIONAL SCORING MODEL
# Inspired by: Seeking Alpha Quant, Goldman ActiveBeta, Zacks, CFRA
# Each pillar: 0-20 pts  |  Total: 0-100
# =============================================================================


def score_valuation(info: Dict) -> Tuple[float, float]:
    """
    Valuation Pillar (0-20 pts)
    Returns (points_earned, points_possible).
    """
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

    # 2. Forward PE vs Earnings Growth (proper PEG, 0-5 pts)
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

    # 3. Absolute Forward PE sanity check (0-4 pts)
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

    # 4. Price-to-Book (0-2 pts) — prevents PEG-only blindness
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
    """
    Growth Pillar (0-20 pts)
    Returns (points_earned, points_possible).
    """
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
        eg = earnings_growth * 100  # convert decimal to pct
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

    # 3. Analyst conviction (estimate revision proxy) (0-5 pts)
    # Zacks proved this is the #1 predictive factor
    rec_key = (info.get("recommendationKey") or "").lower()
    if _has(rec_mean):
        possible += 5
        if rec_mean <= 1.5:
            earned += 5  # Strong Buy consensus
        elif rec_mean <= 2.0:
            earned += 3  # Buy
        elif rec_mean <= 2.5:
            earned += 1  # Hold
        else:
            earned += 0  # Weak/Sell
    elif rec_key:
        possible += 5
        if rec_key in ("buy", "strong_buy"):
            earned += 3
        elif rec_key in ("hold", "neutral"):
            earned += 1
        else:
            earned += 0

    # 4. Forward PE < Trailing PE = earnings trajectory improving (0-2 pts)
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

    # 6. Earnings quarterly growth acceleration (0-2 pts)
    eqg = info.get("earningsQuarterlyGrowth")
    if _has(eqg) and _has(earnings_growth):
        possible += 2
        if eqg > earnings_growth:
            earned += 2  # quarterly accelerating vs annual

    return earned, possible


def score_profitability(info: Dict) -> Tuple[float, float]:
    """
    Profitability Pillar (0-20 pts)
    Returns (points_earned, points_possible).
    """
    efficiency_earned = 0.0
    efficiency_possible = 0.0
    roe = info.get("returnOnEquity")
    gross_margin = info.get("grossMargins")
    op_margin = info.get("operatingMargins")
    profit_margin = info.get("profitMargins")
    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")

    # 1. ROE (0-5 pts) — Buffett's favorite metric
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

    # 3. Operating margin (0-4 pts) — operational efficiency
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
    net_income_growth = info.get("netIncomeGrowth")
    fcf_growth = info.get("freeCashflowGrowth")
    for growth_val in (net_income_growth, fcf_growth):
        if _has(growth_val):
            score = _score_growth_rate(growth_val)
            if score is not None:
                growth_scores.append(score)
    growth_score = sum(growth_scores) / len(growth_scores) if growth_scores else None

    net_income = info.get("netIncome") or info.get("netIncomeToCommon") or info.get("netIncomeToCommonStockholders")
    scale_score = _score_scale(net_income)

    weights = {
        "efficiency": 0.5,
        "growth": 0.35,
        "scale": 0.15,
    }

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
    """
    Momentum Pillar (0-20 pts)
    Returns (points_earned, points_possible).
    """
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
        else:
            earned += 0  # significant downtrend

    # 2. Price vs 200MA (0-3 pts) — long-term trend health
    if _has(price_vs_200ma):
        possible += 3
        if price_vs_200ma > 20:
            earned += 3
        elif price_vs_200ma > 0:
            earned += 2
        elif price_vs_200ma > -10:
            earned += 1

    # 3. 52-week return (0-4 pts) — 12m momentum (Goldman uses 11m)
    if _has(week_52_change):
        possible += 4
        w52 = week_52_change * 100
        if w52 > 50:
            earned += 4
        elif w52 > 20:
            earned += 3
        elif w52 > 0:
            earned += 1
        elif w52 > -20:
            earned += 0
        else:
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
            earned += 2  # healthy momentum
        elif 40 <= rsi < 50 or 70 < rsi <= 75:
            earned += 1  # mild deviation
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
    """
    Risk / Stability Pillar (0-20 pts)
    Returns (points_earned, points_possible).
    """
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
            earned += 3  # slightly defensive or aggressive
        elif 1.5 < beta <= 2.0:
            earned += 1  # high volatility
        elif beta > 2.0:
            earned += 0  # extreme volatility
        elif beta < 0.5:
            earned += 2  # very defensive

    # 2. Debt / Equity (0-4 pts) — balance sheet strength
    if _has(debt_equity):
        possible += 4
        if debt_equity < 30:
            earned += 4
        elif debt_equity < 60:
            earned += 2
        elif debt_equity < 100:
            earned += 1
        else:
            earned += 0  # highly leveraged

    # 3. Current ratio (0-3 pts) — short-term liquidity
    if _has(current_ratio):
        possible += 3
        if current_ratio > 2.0:
            earned += 3
        elif current_ratio > 1.5:
            earned += 2
        elif current_ratio > 1.0:
            earned += 1
        else:
            earned += 0  # potential liquidity issues

    # 4. Exhaustion level (0-5 pts) — multi-factor price stress signal
    if exhaustion_level:
        possible += 5
        exhaustion_pts = {"None": 5, "Building": 3, "High": 1, "Extreme": -2}
        earned += exhaustion_pts.get(exhaustion_level, 2)

    # 5. 52-week range width = volatility proxy (0-2 pts)
    # Very wide ranges = high uncertainty = penalty
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

    # 6. Quick ratio bonus if available (0-1 pt)
    qr = info.get("quickRatio")
    if _has(qr):
        possible += 1
        if qr > 1.0:
            earned += 1

    return earned, possible


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
) -> Tuple[int, Dict[str, float], Dict[str, float], float, str]:
    """
    Professional 5-pillar composite Buy Score (0-100) with reality checks.

    Returns:
        (buy_score, pillar_scores, adjustments, data_coverage_pct, score_mode)
    """
    val_earned, val_possible = score_valuation(info)
    growth_earned, growth_possible = score_growth(info)
    prof_earned, prof_possible = score_profitability(info)
    mom_earned, mom_possible = score_momentum(
        history, price_vs_50ma, price_vs_200ma, macd_signal,
        volume_ratio, week_52_change, rsi,
    )
    risk_earned, risk_possible = score_risk(
        info, exhaustion_level,
        info.get("fiftyTwoWeekHigh"), info.get("fiftyTwoWeekLow"),
        info.get("currentPrice") or info.get("regularMarketPrice"),
    )

    total_earned = val_earned + growth_earned + prof_earned + mom_earned + risk_earned
    total_possible = val_possible + growth_possible + prof_possible + mom_possible + risk_possible
    data_coverage = round(total_possible, 1) if total_possible else 0.0

    pillars = {
        "valuation": _normalize_pillar(val_earned, val_possible),
        "growth": _normalize_pillar(growth_earned, growth_possible),
        "profitability": _normalize_pillar(prof_earned, prof_possible),
        "momentum": _normalize_pillar(mom_earned, mom_possible),
        "risk": _normalize_pillar(risk_earned, risk_possible),
    }

    score_mode = "Equity"
    if _is_non_equity(info) or data_coverage < 60:
        score_mode = "Technical"

    if score_mode == "Technical":
        tech_earned = 0.0
        tech_possible = 0.0
        if mom_possible > 0:
            tech_earned += mom_earned
            tech_possible += mom_possible
        if risk_possible > 0:
            tech_earned += risk_earned
            tech_possible += risk_possible
        base = _normalize_total(tech_earned, tech_possible)
        adjustments = {
            "technical_crosscheck": 0.0,
            "commentary_crosscheck": 0.0,
            "target_reality": 0.0,
            "earnings_surprise": 0.0,
            "coverage_quality": 0.0,
            "peg_premium": 0.0,
            "growth_trajectory": 0.0,
            "pe_trajectory": 0.0,
            "exhaustion_penalty": 0.0,
        }
        adj_total = 0.0
    else:
        base = _normalize_total(total_earned, total_possible)
        # Apply reality-check adjustments
        adj_total, adjustments = _reality_check_adjustments(
            base, technical_score, commentary_score, target_upside, info, exhaustion_level
        )

    total = _clip(base + adj_total, 0, 100)

    # Store adjustment values rounded
    adj_display = {k: round(v, 1) for k, v in adjustments.items()}

    return int(round(total)), pillars, adj_display, data_coverage, score_mode


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
    score, _, _, _, _ = calculate_buy_score_v2(
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
