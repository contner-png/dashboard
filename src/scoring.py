import numpy as np
from typing import Dict


def calculate_technical_score(history: Dict, indicators: Dict) -> int:
    """
    Technical Score: 0-4 (4 = strongest setup)
    Criteria:
    - Price > 50-day MA AND > 200-day MA (+1)
    - RSI between 50-70 (healthy momentum) (+1)
    - Volume > 20-day avg > 50-day avg (confirmed interest) (+1)
    - MACD bullish (+1)
    """
    from src.indicators import calc_price_vs_ma, calc_rsi, calc_macd

    prices = history["Close"]
    volume = history["Volume"]
    score = 0

    # 1. Moving averages
    vs_50 = calc_price_vs_ma(prices, 50)
    vs_200 = calc_price_vs_ma(prices, 200)
    if not np.isnan(vs_50) and not np.isnan(vs_200):
        if vs_50 > 0 and vs_200 > 0:
            score += 1

    # 2. RSI healthy zone
    rsi = calc_rsi(prices)
    if not np.isnan(rsi) and 50 <= rsi <= 70:
        score += 1

    # 3. Volume confirmation
    vol_20 = volume.tail(20).mean()
    vol_50 = volume.tail(50).mean()
    if not np.isnan(vol_20) and not np.isnan(vol_50):
        if vol_20 > vol_50:
            score += 1

    # 4. MACD bullish
    _, _, macd_signal = calc_macd(prices)
    if macd_signal in ("Bullish", "Bullish Crossover"):
        score += 1

    return score


def calculate_commentary_score(info: Dict) -> int:
    """
    Commentary Score: 1-4 (based on fundamentals & guidance trajectory)
    Criteria:
    - Analyst consensus = Buy/Strong Buy (+1)
    - Forward PE < Trailing PE (improving earnings) (+1)
    - Revenue growth YoY > 10% (+1)
    - PEG ratio < 2 (attractively valued) (+1)
    """
    score = 0

    # 1. Analyst recommendation
    rec = info.get("recommendationKey", "").lower()
    if rec in ("buy", "strong_buy"):
        score += 1

    # 2. Improving earnings trajectory
    trailing_pe = info.get("trailingPE")
    forward_pe = info.get("forwardPE")
    if trailing_pe and forward_pe and forward_pe < trailing_pe:
        score += 1

    # 3. Revenue growth
    rev_growth = info.get("revenueGrowth")
    if rev_growth and rev_growth > 0.10:
        score += 1

    # 4. PEG ratio
    peg = info.get("pegRatio")
    if peg and peg < 2.0:
        score += 1

    # Minimum score is 1 (we always have some commentary)
    return max(1, score)


def calculate_buy_score(
    technical_score: int,
    commentary_score: int,
    exhaustion_level: str,
    rsi: float,
    peg: float,
    trailing_pe: float,
    forward_pe: float,
    est_growth: float,
    macd_signal: str,
    price_vs_50ma: float,
    price_vs_200ma: float,
    volume_ratio: float,
) -> int:
    """
    Composite Buy Score: 0-100
    Combines all metrics into a single "best buy" score.

    Breakdown:
    - Technical Momentum: 0-25 pts
    - Fundamental Quality: 0-25 pts
    - Valuation Attractiveness: 0-20 pts
    - Entry Timing / Exhaustion: 0-20 pts
    - Risk / Momentum Balance: 0-10 pts
    """
    score = 0

    # 1. Technical Momentum (0-25 pts)
    # Technical score 0-4 mapped to 0-20 pts
    tech_points = (technical_score / 4) * 20
    # MACD bonus
    if macd_signal in ("Bullish", "Bullish Crossover"):
        tech_points += 5
    score += min(25, tech_points)

    # 2. Fundamental Quality (0-25 pts)
    # Commentary score 1-4 mapped to 10-25 pts
    comm_points = 10 + ((commentary_score - 1) / 3) * 15
    score += min(25, comm_points)

    # 3. Valuation Attractiveness (0-20 pts)
    val_points = 0
    # PEG ratio scoring
    if peg and not np.isnan(peg):
        if peg < 1:
            val_points += 10
        elif peg < 2:
            val_points += 7
        elif peg < 3:
            val_points += 4
        else:
            val_points += 1
    else:
        val_points += 4  # neutral if no PEG data

    # Forward PE discount vs Trailing PE
    if forward_pe and trailing_pe and not np.isnan(forward_pe) and not np.isnan(trailing_pe):
        pe_discount = (trailing_pe - forward_pe) / trailing_pe
        if pe_discount > 0.30:
            val_points += 6
        elif pe_discount > 0.15:
            val_points += 4
        elif pe_discount > 0:
            val_points += 2
        else:
            val_points += 0
    else:
        val_points += 2

    # Growth-adjusted valuation bonus
    # High expected growth + reasonable forward PE = great value
    if est_growth and not np.isnan(est_growth) and forward_pe and not np.isnan(forward_pe):
        # PEG-like check using analyst growth vs forward PE
        implied_peg = forward_pe / est_growth if est_growth > 0 else 999
        if implied_peg < 0.5:
            val_points += 6
        elif implied_peg < 1.0:
            val_points += 4
        elif implied_peg < 2.0:
            val_points += 2
        elif est_growth < 0:
            val_points -= 2  # penalty for expected earnings decline
    score += max(0, min(20, val_points))

    # 4. Entry Timing / Exhaustion (0-20 pts)
    exhaustion_map = {
        "None": 20,
        "Building": 12,
        "High": 5,
        "Extreme": 0,
    }
    score += exhaustion_map.get(exhaustion_level, 10)

    # 5. Risk / Momentum Balance (0-10 pts)
    # RSI ideal entry zone: 40-60 (not oversold, not overbought)
    if rsi and not np.isnan(rsi):
        if 40 <= rsi <= 60:
            rsi_points = 10
        elif 30 <= rsi < 40 or 60 < rsi <= 70:
            rsi_points = 6
        elif 20 <= rsi < 30 or 70 < rsi <= 80:
            rsi_points = 3
        else:
            rsi_points = 0
    else:
        rsi_points = 5

    # Price vs MA penalty (if far extended, reduce score)
    ma_penalty = 0
    if price_vs_50ma and not np.isnan(price_vs_50ma):
        if price_vs_50ma > 30:
            ma_penalty += 3
        elif price_vs_50ma > 20:
            ma_penalty += 1
    if price_vs_200ma and not np.isnan(price_vs_200ma):
        if price_vs_200ma > 50:
            ma_penalty += 2

    # Volume confirmation bonus
    vol_bonus = 0
    if volume_ratio and not np.isnan(volume_ratio):
        if volume_ratio > 1.1:
            vol_bonus += 2
        elif volume_ratio > 0.95:
            vol_bonus += 1

    score += max(0, min(10, rsi_points - ma_penalty + vol_bonus))

    return int(round(score))
