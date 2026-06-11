import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from src.database import get_tickers, upsert_metrics, add_ticker, store_prices
from src.fetcher import fetch_ticker_data, get_company_name, get_sector
from src.indicators import calculate_exhaustion, calc_price_vs_ma, calc_macd, calc_price_changes
from src.research import dcf_valuation, max_drawdown
from src.scoring import (
    calculate_technical_score,
    calculate_commentary_score,
    calculate_buy_score,
    rating_band,
)

logger = logging.getLogger(__name__)


def _compute_expected_growth(info: dict) -> float:
    """
    Ensemble estimate of expected growth using 4 signals with outlier rejection.

    Signals (processed individually):
      1. PEG-implied growth   = forwardPE / PEG  (market's embedded estimate)
      2. Revenue growth       = revenueGrowth * 100  (stable fundamental)
      3. Earnings growth      = earningsGrowth * 100  (analyst consensus, noisy)
      4. PE trajectory        = implied from forward vs trailing PE

    Outlier rejection:
      - If earningsGrowth > 3x revenueGrowth: treat as small-base artifact,
        replace with a dampened blend
      - Any signal > 100% is capped; any signal < -30% is floored

    Ensemble weights:
      PEG-implied: 0.35  |  Revenue: 0.30  |  Earnings: 0.25  |  PE trajectory: 0.10

    Returns rounded expected growth %, or None if no signals available.
    """
    signals = []
    weights = []

    # --- Signal 1: PEG-implied growth (market's own estimate) ---
    peg = info.get("pegRatio")
    fwd_pe = info.get("forwardPE")
    trail_pe = info.get("trailingPE")
    if peg and peg > 0:
        if fwd_pe and not (isinstance(fwd_pe, float) and fwd_pe != fwd_pe):
            peg_growth = fwd_pe / peg
        elif trail_pe and not (isinstance(trail_pe, float) and trail_pe != trail_pe):
            peg_growth = trail_pe / peg
        else:
            peg_growth = None
        if peg_growth is not None:
            peg_growth = max(-30, min(peg_growth, 100))
            signals.append(peg_growth)
            weights.append(0.35)

    # --- Signal 2: Revenue growth (stable fundamental anchor) ---
    rg = info.get("revenueGrowth")
    if rg and not (isinstance(rg, float) and rg != rg):
        rev_growth = rg * 100
        rev_growth = max(-30, min(rev_growth, 100))
        signals.append(rev_growth)
        weights.append(0.30)
    else:
        rev_growth = None

    # --- Signal 3: Earnings growth (analyst consensus, apply small-base filter) ---
    eg = info.get("earningsGrowth")
    if eg and not (isinstance(eg, float) and eg != eg):
        earn_growth = eg * 100

        # Small-base spike detection: if earnings growth is wildly above revenue,
        # it's likely from a near-zero earnings base (e.g., VICR, MU).
        if rev_growth is not None and earn_growth > 0:
            if earn_growth > 3 * rev_growth and earn_growth > 60:
                earn_growth = min(rev_growth * 1.5 + 25, 90)
            elif earn_growth > 100:
                earn_growth = min(earn_growth, 100)
        else:
            earn_growth = max(-30, min(earn_growth, 100))

        signals.append(earn_growth)
        weights.append(0.25)

    # --- Signal 4: PE trajectory (forward vs trailing implies expected growth) ---
    if fwd_pe and trail_pe and trail_pe > 0:
        pe_ratio = fwd_pe / trail_pe
        if pe_ratio < 1:
            pe_trajectory = ((1 / pe_ratio) - 1) * 100
            pe_trajectory = max(-30, min(pe_trajectory, 100))
            signals.append(pe_trajectory)
            weights.append(0.10)

    if not signals:
        return None

    total_w = sum(weights)
    weights = [w / total_w for w in weights]
    blended = sum(s * w for s, w in zip(signals, weights))

    blended = max(-30, min(blended, 100))
    return round(blended, 1)


def add_and_sync(symbol: str) -> bool:
    """
    Add a ticker to the watchlist and try to sync it.

    The ticker is persisted BEFORE the network fetch, so a flaky Yahoo
    response can never lose it — it just shows as unsynced until the
    next sync succeeds.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return False
    add_ticker(symbol)
    return sync_ticker(symbol)


def sync_ticker(symbol: str) -> bool:
    """Fetch and store all metrics for a single ticker."""
    symbol = symbol.strip().upper()
    try:
        data = fetch_ticker_data(symbol)
    except Exception as exc:
        logger.error(f"Sync failed for {symbol}: {exc}")
        return False
    if not data:
        return False

    info = data["info"]
    history = data["history"]

    # Ensure ticker exists in DB and refresh name/sector
    add_ticker(symbol, get_company_name(info), get_sector(info, symbol))

    # Calculate indicators
    exhaustion = calculate_exhaustion(history)
    tech_score = calculate_technical_score(history, exhaustion)
    comm_score = calculate_commentary_score(info)

    vs_50 = calc_price_vs_ma(history["Close"], 50)
    vs_200 = calc_price_vs_ma(history["Close"], 200)
    _, _, macd_signal = calc_macd(history["Close"])

    # Expected growth: ensemble of 4 signals with outlier rejection
    projected_cagr = _compute_expected_growth(info)

    # Compute target upside % and current price (needed for buy score)
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or history["Close"].iloc[-1]
    target_mean = info.get("targetMeanPrice")
    target_upside = None
    if target_mean and current_price and current_price > 0:
        target_upside = round((target_mean - current_price) / current_price * 100, 1)

    # Tier-2 research metrics: DCF intrinsic value + 1y max drawdown
    dcf = dcf_valuation(
        fcf=info.get("freeCashflow"),
        shares=info.get("sharesOutstanding"),
        price=current_price,
        growth_pct=projected_cagr,
        beta=info.get("beta"),
        cash=info.get("totalCash"),
        debt=info.get("totalDebt"),
    )
    mdd = max_drawdown(history["Close"])
    price_changes = calc_price_changes(history)

    next_earnings = None
    earnings_ts = info.get("earningsTimestampStart") or info.get("earningsTimestamp")
    if earnings_ts:
        try:
            next_earnings = datetime.fromtimestamp(float(earnings_ts), tz=timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            next_earnings = None

    def _pct(key):
        v = info.get(key)
        if v is None or (isinstance(v, float) and v != v):
            return None
        return round(v * 100, 1)

    buy_score, pillars, adjustments, data_coverage, score_mode = calculate_buy_score(
        info=info,
        history=history,
        exhaustion_level=exhaustion.get("exhaustion_level", "None"),
        price_vs_50ma=vs_50,
        price_vs_200ma=vs_200,
        macd_signal=macd_signal,
        volume_ratio=exhaustion.get("volume_ratio"),
        week_52_change=info.get("52WeekChange"),
        rsi=exhaustion.get("rsi_14"),
        target_upside=target_upside,
        dcf_upside=dcf["upside"] if dcf else None,
    )
    band = rating_band(buy_score)

    metrics = {
        "price": round(current_price, 2),
        "market_cap": info.get("marketCap"),
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
        "data_coverage": data_coverage,
        "score_mode": score_mode,
        "score_valuation": pillars["valuation"],
        "score_growth": pillars["growth"],
        "score_profitability": pillars["profitability"],
        "score_momentum": pillars["momentum"],
        "score_risk": pillars["risk"],
        # v3 conviction adjustments
        "adj_peg": adjustments["value_premium"],
        "adj_target": adjustments["analyst_conviction"],
        "adj_pe_traj": adjustments["earnings_trajectory"],
        "adj_exhaustion": adjustments["exhaustion"],
        "adj_dcf": adjustments["intrinsic_value"],
        # retired v2 adjustments — zeroed so stale values don't linger
        "adj_technical": 0,
        "adj_commentary": 0,
        "adj_surprise": 0,
        "adj_coverage": 0,
        "adj_growth": 0,
        # Tier-2 research pack fundamentals
        "free_cashflow": info.get("freeCashflow"),
        "shares_outstanding": info.get("sharesOutstanding"),
        "total_cash": info.get("totalCash"),
        "total_debt": info.get("totalDebt"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "roe": _pct("returnOnEquity"),
        "gross_margin": _pct("grossMargins"),
        "operating_margin": _pct("operatingMargins"),
        "profit_margin": _pct("profitMargins"),
        "revenue_growth": _pct("revenueGrowth"),
        "earnings_growth": _pct("earningsGrowth"),
        "recommendation_mean": info.get("recommendationMean"),
        "num_analysts": info.get("numberOfAnalystOpinions"),
        "next_earnings": next_earnings,
        "max_drawdown_1y": mdd,
        "change_1w": price_changes["change_1w"],
        "change_1m": price_changes["change_1m"],
        "change_ytd": price_changes["change_ytd"],
        "dcf_value": dcf["value"] if dcf else None,
        "dcf_upside": dcf["upside"] if dcf else None,
        "dcf_bull": dcf["bull"] if dcf else None,
        "dcf_bear": dcf["bear"] if dcf else None,
        "dcf_verdict": dcf["verdict"] if dcf else None,
        "description": info.get("longBusinessSummary", ""),
    }

    # Clean NaN values for SQLite
    clean_metrics = {}
    for k, v in metrics.items():
        if v is None or (isinstance(v, float) and v != v):  # NaN check
            clean_metrics[k] = None
        else:
            clean_metrics[k] = v

    upsert_metrics(symbol, clean_metrics)
    store_prices(symbol, history)  # local price cache: instant charts/correlations, backtest fuel

    logger.info(
        f"Synced {symbol}: Buy={buy_score} ({band}), mode={score_mode}, coverage={data_coverage:.0f}%"
    )
    return True


def sync_many(
    symbols: List[str],
    max_workers: int = 8,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> Dict[str, List[str]]:
    """
    Sync a list of tickers concurrently (network-bound, so threads give a
    near-linear speedup over the old sequential loop).

    Returns {"synced": [...], "failed": [...]}.
    """
    symbols = [s.strip().upper() for s in symbols if s and s.strip()]
    results: Dict[str, List[str]] = {"synced": [], "failed": []}
    if not symbols:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(symbols))) as executor:
        futures = {executor.submit(sync_ticker, sym): sym for sym in symbols}
        for done, future in enumerate(as_completed(futures), start=1):
            sym = futures[future]
            try:
                ok = future.result()
            except Exception as exc:
                logger.error(f"Sync failed for {sym}: {exc}")
                ok = False
            results["synced" if ok else "failed"].append(sym)
            if progress_cb:
                progress_cb(done, len(symbols), sym)

    results["synced"].sort()
    results["failed"].sort()
    return results


def sync_all(progress_cb: Optional[Callable[[int, int, str], None]] = None) -> List[str]:
    """Sync all tracked tickers. Returns list of successfully synced symbols."""
    return sync_many(get_tickers(), progress_cb=progress_cb)["synced"]
