"""
Tier-2 Research Pack: deterministic quantitative research from free Yahoo data.

Everything here is transparent arithmetic — no LLM, no paid data:
  - 2-stage DCF intrinsic value with bull/base/bear targets
  - Bear/base/bull CAGR scenario bands
  - Max drawdown from price history
  - Rule-based entry zones / stop levels
  - Rule-based position sizing (Core vs Satellite)
  - CIO memo prompt builder (grounds an external LLM with real numbers)
"""

from typing import Dict, List, Optional


def _num(val) -> Optional[float]:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def max_drawdown(close) -> Optional[float]:
    """Largest peak-to-trough decline (%) over the given close series."""
    if close is None or len(close) < 30:
        return None
    running_max = close.cummax()
    drawdown = (close / running_max - 1.0) * 100
    return round(float(drawdown.min()), 1)


def dcf_valuation(
    fcf,
    shares,
    price,
    growth_pct=None,
    beta=None,
    cash=None,
    debt=None,
) -> Optional[Dict]:
    """
    Simple 2-stage DCF: 5 years of FCF with growth fading linearly to a 2.5%
    terminal rate, discounted at a beta-scaled rate (8-14%), plus net cash.

    Requires positive FCF and shares outstanding — returns None otherwise
    (an auto-DCF on a money-losing company is fiction, not analysis).
    """
    fcf = _num(fcf)
    shares = _num(shares)
    price = _num(price)
    if not fcf or fcf <= 0 or not shares or shares <= 0 or not price or price <= 0:
        return None

    # Haircut the growth estimate — analyst/ensemble numbers skew optimistic.
    base_growth = _clamp(_num(growth_pct) if growth_pct is not None else 8.0, -10.0, 25.0) / 100 * 0.85
    beta_val = _num(beta) or 1.0
    discount = _clamp(0.045 + 0.045 * beta_val, 0.08, 0.14)
    terminal = 0.025
    net_cash = (_num(cash) or 0.0) - (_num(debt) or 0.0)

    def value_per_share(g0: float, r: float) -> float:
        pv = 0.0
        f = fcf
        for t in range(1, 6):
            g_t = g0 + (terminal - g0) * (t - 1) / 5  # fade toward terminal
            f *= (1 + g_t)
            pv += f / (1 + r) ** t
        tv = f * (1 + terminal) / (r - terminal)
        pv += tv / (1 + r) ** 5
        return (pv + net_cash) / shares

    base = value_per_share(base_growth, discount)
    bull = value_per_share(min(base_growth + 0.06, 0.30), max(discount - 0.01, 0.07))
    bear = value_per_share(max(base_growth - 0.06, -0.10), discount + 0.01)

    upside = (base / price - 1) * 100
    if upside >= 20:
        verdict = "Undervalued"
    elif upside <= -20:
        verdict = "Overvalued"
    else:
        verdict = "Fairly Valued"

    return {
        "value": round(base, 2),
        "bull": round(bull, 2),
        "bear": round(bear, 2),
        "upside": round(upside, 1),
        "verdict": verdict,
        "growth_used": round(base_growth * 100, 1),
        "discount_rate": round(discount * 100, 1),
    }


def scenario_cagr(projected_cagr, beta, coverage) -> Optional[Dict]:
    """Bear/base/bull expected CAGR bands (3-4yr), spread scaled by uncertainty."""
    base = _num(projected_cagr)
    if base is None:
        return None
    base = _clamp(base, -20.0, 50.0)
    spread = 8.0
    beta_val = _num(beta)
    if beta_val is not None and beta_val > 1.5:
        spread += 4.0
    cov = _num(coverage)
    if cov is not None and cov < 80:
        spread += 3.0
    return {
        "bear": round(base - spread, 0),
        "base": round(base, 0),
        "bull": round(base + spread, 0),
    }


def entry_plan(row: Dict) -> Optional[Dict]:
    """Rule-based entry zone and stop levels from stored technicals."""
    price = _num(row.get("price"))
    if not price:
        return None
    vs50 = _num(row.get("price_vs_50ma"))
    vs200 = _num(row.get("price_vs_200ma"))
    week_low = _num(row.get("week_52_low"))

    ma50 = price / (1 + vs50 / 100) if vs50 is not None else None
    ma200 = price / (1 + vs200 / 100) if vs200 is not None else None

    if ma50 and price > ma50 * 1.02:
        entry_low, entry_high = ma50, ma50 * 1.05
        entry_note = "Extended above trend — stage in on a pullback toward the 50-day MA."
    elif ma50:
        entry_low, entry_high = min(price, ma50 * 0.97), max(price, ma50 * 1.02)
        entry_note = "Trading near trend — current zone is a reasonable accumulation range."
    else:
        entry_low = entry_high = None
        entry_note = "Not enough history for moving-average entry zones."

    stop_candidates = [s for s in (ma200, week_low * 1.05 if week_low else None) if s and s < price]
    hard_stop = max(stop_candidates) if stop_candidates else price * 0.85
    hard_stop = min(hard_stop, price * 0.92)  # never wider than -8% from current

    return {
        "ma50": round(ma50, 2) if ma50 else None,
        "ma200": round(ma200, 2) if ma200 else None,
        "entry_low": round(entry_low, 2) if entry_low else None,
        "entry_high": round(entry_high, 2) if entry_high else None,
        "hard_stop": round(hard_stop, 2),
        "note": entry_note,
    }


def position_plan(row: Dict) -> Dict:
    """Rule-based Core/Satellite classification and suggested weight range."""
    mcap = _num(row.get("market_cap")) or 0
    beta = _num(row.get("beta"))
    coverage = _num(row.get("data_coverage")) or 0
    profit = _num(row.get("score_profitability"))
    mode = row.get("score_mode") or ""

    reasons: List[str] = []
    if mcap >= 50e9 and (profit or 0) >= 12 and (beta is None or beta <= 1.5) and coverage >= 80:
        bucket, weight = "Core", "3-5%"
        reasons.append("large cap with strong profitability, manageable volatility, full data coverage")
    elif mode == "Technical" or coverage < 60 or (beta is not None and beta > 2.0) or mcap < 2e9:
        bucket, weight = "Speculative Satellite", "0.5-1%"
        if mode == "Technical" or coverage < 60:
            reasons.append("limited fundamental data — technically scored")
        if beta is not None and beta > 2.0:
            reasons.append(f"high volatility (beta {beta:.1f})")
        if 0 < mcap < 2e9:
            reasons.append("small cap")
    else:
        bucket, weight = "Satellite", "1-2.5%"
        reasons.append("solid but not core-grade on size/profitability/volatility")

    return {
        "bucket": bucket,
        "weight": weight,
        "rationale": "; ".join(reasons),
        "dca": "Split entry into 3 tranches over 6-8 weeks: 1/3 now (or at the entry zone), "
               "1/3 on a 5%+ pullback or after the next earnings report, 1/3 to confirm the trend. "
               "Rebalance if the position drifts 50% above its target weight.",
    }


def build_research_prompt(row: Dict, holdings: List[Dict]) -> str:
    """
    Assemble the full CIO deep-dive prompt pre-filled with this ticker's real
    numbers and the user's actual holdings, so the LLM is grounded instead of
    hallucinating figures. Paste into any chat LLM (free tiers work).
    """
    def fv(key, suffix="", money=False):
        v = row.get(key)
        v = _num(v) if not isinstance(v, str) else v
        if v is None:
            return "n/a"
        if money:
            return f"${v:,.2f}" if abs(v) < 10000 else f"${v:,.0f}"
        return f"{v}{suffix}"

    holdings_lines = "\n".join(
        f"- {h.get('symbol')} ({h.get('sector') or 'Unknown'}) — buy score {h.get('buy_score') if h.get('buy_score') is not None else 'n/a'}"
        for h in holdings
    ) or "- (no current holdings tagged)"

    pillars = ", ".join(
        f"{name} {_num(row.get(key)) if _num(row.get(key)) is not None else 'n/a'}/20"
        for name, key in [
            ("Valuation", "score_valuation"), ("Growth", "score_growth"),
            ("Profitability", "score_profitability"), ("Momentum", "score_momentum"),
            ("Risk", "score_risk"),
        ]
    )

    return f"""Act as the Chief Investment Officer (CIO) of an elite multi-family office. You are a Senior Hedge Fund Analyst producing a high-conviction deep-dive research memo for a Portfolio Manager. Prioritize non-obvious insights, rigorous systems thinking, and asymmetric risk-reward. Use step-by-step reasoning. Be professional, objective, and intellectually honest.

IMPORTANT: Use the VERIFIED DATA APPENDIX below for all quantitative claims — do not invent numbers. If a figure is not in the appendix and you cannot verify it, say so explicitly. Use web search (if available) only for qualitative/news context.

TARGET ASSET: {row.get('symbol')} — {row.get('name') or ''} ({row.get('sector') or 'Unknown sector'})

Produce the following report:

**1. The Thesis & Moat (Goldman/JPMorgan view)**
- Competitive moat rating and structural importance to its sector/supply chain
- Segment growth analysis and the 3-5 KPIs to monitor
- Earnings momentum and what to expect from management guidance

**2. Quantitative Valuation (Morgan Stanley view)**
- Sanity-check the DCF verdict in the appendix; state your own intrinsic-value view
- Balance sheet health check using the appendix figures
- Strict bull and bear price targets with reasoning

**3. Risk & Stress Testing (Bridgewater view)**
- Recession stress test and max-drawdown expectations (appendix has the trailing figure)
- Correlation/overlap risk versus my existing portfolio (listed below)
- Confirm or adjust the entry zone and hard stop in the appendix

**4. Portfolio Integration & Execution (BlackRock view)**
- Position sizing for an aggressive capital-appreciation investor (2-3 year horizon)
- Core vs Satellite classification (appendix has a rule-based suggestion — challenge it)
- Tax-efficient DCA and rebalancing plan
- If recommending a buy, state what I should sell (or whether to use cash) given my holdings

**5. Systems Map & Second/Third-Order Effects**
- Value chain: key players, dependencies, bottlenecks, leverage points
- 3-5 causal chains: Primary event → second-order → third-order → investment relevance

**6. Scenario Framework**
- Bull / base / bear with assumptions, probabilities, timelines, leading indicators
- The appendix has quantitative CAGR bands — layer your qualitative scenarios on top

**7. Non-Obvious Angle & Diligence Agenda**
- What is the market missing? (the variant perception)
- 5-10 high-value unanswered diligence questions, priority-ranked

**8. Conclusion**
- Should this become a position? Conviction level (1-10). Time horizon. How it improves the portfolio.

=== VERIFIED DATA APPENDIX (from my dashboard, as of {row.get('last_updated') or 'last sync'}) ===
Price: {fv('price', money=True)} | Market cap: {fv('market_cap', money=True)} | Next earnings: {row.get('next_earnings') or 'n/a'}
Buy score: {fv('buy_score')}/100 ({row.get('rating_band') or 'n/a'}) | Mode: {row.get('score_mode') or 'n/a'} | Data coverage: {fv('data_coverage', '%')}
Pillars: {pillars}
Valuation: trailing P/E {fv('pe_trailing')} | forward P/E {fv('pe_forward')} | PEG {fv('peg_ratio')} | analyst target upside {fv('target_upside', '%')}
DCF (2-stage, 5yr): intrinsic value {fv('dcf_value', money=True)} | upside {fv('dcf_upside', '%')} | verdict {row.get('dcf_verdict') or 'n/a'} | bull {fv('dcf_bull', money=True)} / bear {fv('dcf_bear', money=True)}
Growth: blended est. growth {fv('projected_cagr', '%')} | revenue growth {fv('revenue_growth', '%')} | earnings growth {fv('earnings_growth', '%')}
Profitability: ROE {fv('roe', '%')} | gross margin {fv('gross_margin', '%')} | operating margin {fv('operating_margin', '%')} | net margin {fv('profit_margin', '%')} | FCF {fv('free_cashflow', money=True)}
Balance sheet: debt/equity {fv('debt_to_equity')} | current ratio {fv('current_ratio')}
Risk: beta {fv('beta')} | max drawdown (1y) {fv('max_drawdown_1y', '%')} | exhaustion: {row.get('exhaustion_level') or 'n/a'} | RSI(14) {fv('rsi_14')}
Range: 52w high {fv('week_52_high', money=True)} / low {fv('week_52_low', money=True)} | vs 50-day MA {fv('price_vs_50ma', '%')} | vs 200-day MA {fv('price_vs_200ma', '%')}
Analyst coverage: {fv('num_analysts')} analysts | consensus rec (1=strong buy, 5=sell): {fv('recommendation_mean')}
Legacy 22V scores: Technical {fv('technical_score')}/4 | Commentary {fv('commentary_score')}/4

=== MY CURRENT HOLDINGS (capital-appreciation focus, 2-3 year horizon) ===
{holdings_lines}
"""
