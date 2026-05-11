import logging
from typing import List
from src.database import get_tickers, upsert_metrics, add_ticker
from src.fetcher import fetch_ticker_data, get_company_name, get_sector
from src.indicators import calculate_exhaustion, calc_price_vs_ma, calc_macd
from src.scoring import calculate_technical_score, calculate_commentary_score, calculate_buy_score

logger = logging.getLogger(__name__)


def sync_ticker(symbol: str) -> bool:
    """Fetch and store all metrics for a single ticker."""
    data = fetch_ticker_data(symbol)
    if not data:
        return False

    info = data["info"]
    history = data["history"]

    # Ensure ticker exists in DB
    add_ticker(symbol, get_company_name(info), get_sector(info))

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

    # Composite buy score
    buy_score = calculate_buy_score(
        technical_score=tech_score,
        commentary_score=comm_score,
        exhaustion_level=exhaustion.get("exhaustion_level", "None"),
        rsi=exhaustion.get("rsi_14"),
        peg=info.get("pegRatio"),
        trailing_pe=info.get("trailingPE"),
        forward_pe=info.get("forwardPE"),
        macd_signal=macd_signal,
        price_vs_50ma=vs_50,
        price_vs_200ma=vs_200,
        volume_ratio=exhaustion.get("volume_ratio"),
    )

    metrics = {
        "price": round(info.get("currentPrice") or info.get("regularMarketPrice") or history["Close"].iloc[-1], 2),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "peg_ratio": info.get("pegRatio"),
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
    }

    # Clean NaN values for SQLite
    clean_metrics = {}
    for k, v in metrics.items():
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            clean_metrics[k] = None
        else:
            clean_metrics[k] = v

    upsert_metrics(symbol, clean_metrics)
    logger.info(f"Synced {symbol}: Buy={buy_score}, Tech={tech_score}, Comm={comm_score}, Exhaustion={exhaustion['exhaustion_level']}")
    return True


def sync_all() -> List[str]:
    """Sync all tracked tickers. Returns list of successfully synced symbols."""
    tickers = get_tickers()
    synced = []
    for symbol in tickers:
        if sync_ticker(symbol):
            synced.append(symbol)
    return synced
