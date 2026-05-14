import logging
from typing import List
from src.database import get_tickers, upsert_metrics, add_ticker
from src.fetcher import fetch_ticker_data, get_company_name, get_sector
from src.indicators import calculate_exhaustion, calc_price_vs_ma, calc_macd
from src.scoring import (
    calculate_technical_score,
    calculate_commentary_score,
    calculate_buy_score_v2,
    rating_band,
)

logger = logging.getLogger(__name__)


def sync_ticker(symbol: str) -> bool:
    """Fetch and store all metrics for a single ticker."""
    data = fetch_ticker_data(symbol)
    if not data:
        return False

    info = data["info"]
    history = data["history"]

    # Ensure ticker exists in DB
    add_ticker(symbol, get_company_name(info), get_sector(info, symbol))

    # Calculate indicators
    exhaustion = calculate_exhaustion(history)

    # Technical score
    tech_score = calculate_technical_score(history, exhaustion)

    # Commentary score
    comm_score = calculate_commentary_score(info)

    # Additional metrics
    vs_50 = calc_price_vs_ma(history["Close"], 50)
    vs_200 = calc_price_vs_ma(history["Close"], 200)
    _, _, macd_signal = calc_macd(history["Close"])

    # Estimated CAGR: derive from PEG ratio (PEG = Forward PE / Growth)
    # This gives the market-implied sustainable long-term growth rate
    projected_cagr = None
    peg = info.get("pegRatio")
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    if peg and peg > 0:
        if fwd_pe and not (isinstance(fwd_pe, float) and fwd_pe != fwd_pe):
            projected_cagr = round(fwd_pe / peg, 1)
        elif trail_pe and not (isinstance(trail_pe, float) and trail_pe != trail_pe):
            projected_cagr = round(trail_pe / peg, 1)
    # Fallback: use earningsGrowth dampened (next-year growth is typically 2-3x sustainable)
    if projected_cagr is None:
        eg = info.get("earningsGrowth")
        if eg and not (isinstance(eg, float) and eg != eg):
            projected_cagr = round(eg * 100 / 3, 1)  # Roughly convert next-year to sustainable

    # Compute target upside % and current price (needed for buy score)
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or history["Close"].iloc[-1]
    target_mean = info.get("targetMeanPrice")
    target_upside = None
    if target_mean and current_price and current_price > 0:
        target_upside = round((target_mean - current_price) / current_price * 100, 1)

    # New 5-pillar professional scoring
    buy_score, pillars = calculate_buy_score_v2(
        info=info,
        history=history,
        exhaustion_level=exhaustion.get("exhaustion_level", "None"),
        price_vs_50ma=vs_50,
        price_vs_200ma=vs_200,
        macd_signal=macd_signal,
        volume_ratio=exhaustion.get("volume_ratio"),
        week_52_change=info.get("52WeekChange"),
        rsi=exhaustion.get("rsi_14"),
    )
    band = rating_band(buy_score)

    metrics = {
        "price": round(current_price, 2),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
        "projected_cagr": projected_cagr,
        "beta": info.get("beta"),
        "target_mean": target_mean,
        "target_high": info.get("targetHighPrice"),
        "target_low": info.get("targetLowPrice"),
        "target_upside": target_upside,
        "week_52_high": info.get("fiftyTwoWeekHigh"),
        "week_52_low": info.get("fiftyTwoWeekLow"),
        "rsi_14": exhaustion.get("rsi_14"),
        "volume_20d_avg": exhaustion.get("volume_20d_avg"),
        "volume_50d_avg": exhaustion.get("volume_50d_avg"),
        "price_vs_50ma": round(vs_50, 2) if vs_50 and not (vs_50 != vs_50) else None,
        "price_vs_200ma": round(vs_200, 2) if vs_200 and not (vs_200 != vs_200) else None,
        "macd_signal": macd_signal,
        "bb_position": exhaustion.get("bb_position"),
        "roc_10d": exhaustion.get("roc_10d"),
        "exhaustion_level": exhaustion.get("exhaustion_level"),
        "technical_score": tech_score,
        "commentary_score": comm_score,
        "buy_score": buy_score,
        "rating_band": band,
        "score_valuation": pillars["valuation"],
        "score_growth": pillars["growth"],
        "score_profitability": pillars["profitability"],
        "score_momentum": pillars["momentum"],
        "score_risk": pillars["risk"],
    }

    # Clean NaN values for SQLite
    clean_metrics = {}
    for k, v in metrics.items():
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            clean_metrics[k] = None
        else:
            clean_metrics[k] = v

    upsert_metrics(symbol, clean_metrics)
    logger.info(
        f"Synced {symbol}: Buy={buy_score} ({band}), "
        f"V={pillars['valuation']:.0f} G={pillars['growth']:.0f} P={pillars['profitability']:.0f} "
        f"M={pillars['momentum']:.0f} R={pillars['risk']:.0f}"
    )
    return True


def sync_all() -> List[str]:
    """Sync all tracked tickers. Returns list of successfully synced symbols."""
    tickers = get_tickers()
    synced = []
    for symbol in tickers:
        if sync_ticker(symbol):
            synced.append(symbol)
    return synced
