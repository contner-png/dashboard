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
