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


def _compute_expected_growth(info: dict) -> float:
    """
    Ensemble estimate of expected growth using 4 signals with outlier rejection.
    Analogous to how AI models blend multiple weak predictors into a robust estimate.

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
                # Dampen to a blend of revenue growth + a reasonable premium
                earn_growth = min(rev_growth * 1.5 + 25, 90)
            elif earn_growth > 100:
                # Pure small-base spike with no revenue backing
                earn_growth = min(earn_growth, 100)
        else:
            earn_growth = max(-30, min(earn_growth, 100))

        signals.append(earn_growth)
        weights.append(0.25)

    # --- Signal 4: PE trajectory (forward vs trailing implies expected growth) ---
    if fwd_pe and trail_pe and trail_pe > 0:
        pe_ratio = fwd_pe / trail_pe
        if pe_ratio < 1:
            # Forward PE lower than trailing = market expects earnings growth
            pe_trajectory = ((1 / pe_ratio) - 1) * 100
            pe_trajectory = max(-30, min(pe_trajectory, 100))
            signals.append(pe_trajectory)
            weights.append(0.10)

    if not signals:
        return None

    # Normalize weights and compute weighted average
    total_w = sum(weights)
    weights = [w / total_w for w in weights]
    blended = sum(s * w for s, w in zip(signals, weights))

    # Final sanity caps
    blended = max(-30, min(blended, 100))
    return round(blended, 1)


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

    # Expected growth: ensemble of 4 signals with outlier rejection
    projected_cagr = _compute_expected_growth(info)

    # Compute target upside % and current price (needed for buy score)
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or history["Close"].iloc[-1]
    target_mean = info.get("targetMeanPrice")
    target_upside = None
    if target_mean and current_price and current_price > 0:
        target_upside = round((target_mean - current_price) / current_price * 100, 1)

    # New 5-pillar professional scoring with reality checks
    buy_score, pillars, adjustments, data_coverage, score_mode = calculate_buy_score_v2(
        info=info,
        history=history,
        exhaustion_level=exhaustion.get("exhaustion_level", "None"),
        price_vs_50ma=vs_50,
        price_vs_200ma=vs_200,
        macd_signal=macd_signal,
        volume_ratio=exhaustion.get("volume_ratio"),
        week_52_change=info.get("52WeekChange"),
        rsi=exhaustion.get("rsi_14"),
        technical_score=tech_score,
        commentary_score=comm_score,
        target_upside=target_upside,
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
        "adj_technical": adjustments["technical_crosscheck"],
        "adj_commentary": adjustments["commentary_crosscheck"],
        "adj_target": adjustments["target_reality"],
        "adj_surprise": adjustments["earnings_surprise"],
        "adj_coverage": adjustments["coverage_quality"],
        "adj_peg": adjustments["peg_premium"],
        "adj_growth": adjustments["growth_trajectory"],
        "adj_pe_traj": adjustments["pe_trajectory"],
        "adj_exhaustion": adjustments["exhaustion_penalty"],
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

    def _fmt_pillar(value):
        return f"{value:.0f}" if isinstance(value, (int, float)) else "NA"

    logger.info(
        f"Synced {symbol}: Buy={buy_score} ({band}), "
        f"V={_fmt_pillar(pillars.get('valuation'))} G={_fmt_pillar(pillars.get('growth'))} "
        f"P={_fmt_pillar(pillars.get('profitability'))} M={_fmt_pillar(pillars.get('momentum'))} "
        f"R={_fmt_pillar(pillars.get('risk'))} | "
        f"adj={sum(adjustments.values()):+.0f} mode={score_mode} coverage={data_coverage:.0f}%"
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
