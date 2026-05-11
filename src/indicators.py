import pandas as pd
import numpy as np
from typing import Dict, Tuple


def calc_rsi(prices: pd.Series, period: int = 14) -> float:
    """Calculate RSI(14) from price series."""
    if len(prices) < period + 1:
        return np.nan
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def calc_macd(prices: pd.Series) -> Tuple[float, float, str]:
    """Calculate MACD and return signal status."""
    if len(prices) < 35:
        return np.nan, np.nan, "N/A"
    ema12 = prices.ewm(span=12, adjust=False).mean()
    ema26 = prices.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()

    macd_val = float(macd_line.iloc[-1])
    signal_val = float(signal_line.iloc[-1])

    # Determine signal
    if macd_val > signal_val and macd_line.iloc[-2] <= signal_line.iloc[-2]:
        signal = "Bullish Crossover"
    elif macd_val < signal_val and macd_line.iloc[-2] >= signal_line.iloc[-2]:
        signal = "Bearish Crossover"
    elif macd_val > signal_val:
        signal = "Bullish"
    else:
        signal = "Bearish"

    return macd_val, signal_val, signal


def calc_bollinger_position(prices: pd.Series, period: int = 20) -> str:
    """Return price position relative to Bollinger Bands."""
    if len(prices) < period:
        return "N/A"
    sma = prices.rolling(period).mean()
    std = prices.rolling(period).std()
    upper = sma + 2 * std
    lower = sma - 2 * std

    last_price = float(prices.iloc[-1])
    last_upper = float(upper.iloc[-1])
    last_lower = float(lower.iloc[-1])

    if last_price > last_upper:
        return "Above Upper"
    elif last_price < last_lower:
        return "Below Lower"
    else:
        return "Inside Bands"


def calc_volume_trend(volume: pd.Series) -> Tuple[float, float, float]:
    """Calculate 20-day and 50-day average volume, and their ratio."""
    if len(volume) < 50:
        return np.nan, np.nan, np.nan
    vol_20d = float(volume.tail(20).mean())
    vol_50d = float(volume.tail(50).mean())
    ratio = vol_20d / vol_50d if vol_50d > 0 else np.nan
    return vol_20d, vol_50d, ratio


def calc_price_vs_ma(prices: pd.Series, ma_period: int) -> float:
    """Calculate percentage distance from moving average."""
    if len(prices) < ma_period:
        return np.nan
    ma = prices.rolling(ma_period).mean()
    return float((prices.iloc[-1] / ma.iloc[-1] - 1) * 100)


def calc_roc(prices: pd.Series, period: int = 10) -> float:
    """Rate of change over N days."""
    if len(prices) < period + 1:
        return np.nan
    return float((prices.iloc[-1] / prices.iloc[-(period + 1)] - 1) * 100)


def calculate_exhaustion(history: pd.DataFrame) -> Dict:
    """
    Calculate exhaustion based on volume, RSI, and price action.
    Returns dict with exhaustion_level and component scores.
    """
    prices = history["Close"]
    volume = history["Volume"]

    rsi = calc_rsi(prices)
    vol_20d, vol_50d, vol_ratio = calc_volume_trend(volume)
    bb_pos = calc_bollinger_position(prices)
    roc_10d = calc_roc(prices, 10)

    # Volume exhaustion score (0-100)
    # Declining volume on up-moves = exhaustion building
    if np.isnan(vol_ratio):
        vol_score = 50
    elif vol_ratio < 0.85:
        vol_score = 85  # Strong exhaustion signal
    elif vol_ratio < 0.95:
        vol_score = 65
    elif vol_ratio < 1.05:
        vol_score = 50
    else:
        vol_score = 30  # Rising volume = healthy

    # RSI exhaustion score (0-100)
    if np.isnan(rsi):
        rsi_score = 50
    elif rsi > 80:
        rsi_score = 90
    elif rsi > 70:
        rsi_score = 75
    elif rsi < 20:
        rsi_score = 85
    elif rsi < 30:
        rsi_score = 70
    else:
        rsi_score = 40

    # Price action exhaustion (0-100)
    # Extreme moves + BB position
    price_score = 0
    if np.isnan(roc_10d):
        price_score = 50
    else:
        move = abs(roc_10d)
        if move > 15:
            price_score = 80
        elif move > 10:
            price_score = 65
        elif move > 5:
            price_score = 50
        else:
            price_score = 30

    # Adjust based on BB position
    if bb_pos == "Above Upper":
        price_score = min(100, price_score + 15)
    elif bb_pos == "Below Lower":
        price_score = min(100, price_score + 15)

    # Composite exhaustion (weighted average)
    composite = vol_score * 0.30 + rsi_score * 0.35 + price_score * 0.35

    if composite >= 80:
        level = "Extreme"
    elif composite >= 65:
        level = "High"
    elif composite >= 50:
        level = "Building"
    else:
        level = "None"

    return {
        "exhaustion_level": level,
        "exhaustion_composite": round(composite, 1),
        "rsi_14": round(rsi, 2) if not np.isnan(rsi) else None,
        "volume_20d_avg": round(vol_20d, 0) if not np.isnan(vol_20d) else None,
        "volume_50d_avg": round(vol_50d, 0) if not np.isnan(vol_50d) else None,
        "volume_ratio": round(vol_ratio, 3) if not np.isnan(vol_ratio) else None,
        "bb_position": bb_pos,
        "roc_10d": round(roc_10d, 2) if not np.isnan(roc_10d) else None,
    }
