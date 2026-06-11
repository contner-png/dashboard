import hashlib
import os
import tempfile

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.database import (
    init_db,
    add_ticker,
    remove_ticker,
    get_tickers,
    get_all_metrics,
    get_stale_tickers,
    get_holdings,
    set_holdings,
    get_prices,
)
from src.sync import add_and_sync, sync_many
from src.fetcher import fetch_history, fetch_news
from src.research import dcf_valuation, scenario_cagr, entry_plan, position_plan, build_research_prompt
from src.ui import (
    inject_css,
    fmt,
    fmt_large_number,
    time_ago,
    cell_style,
    badge,
    score_tier,
    pillar_tier,
    sort_key,
    sortable_table_doc,
    TIERS,
    RATING_TIER,
    RATING_ORDER,
)

st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")
inject_css(st)
init_db()

STALE_HOURS = 24

# ---------------------------------------------------------------------------
# Cached data access — the dashboard renders instantly from SQLite; network
# syncs only happen when explicitly requested.
# ---------------------------------------------------------------------------


@st.cache_data(ttl=120, show_spinner=False)
def load_metrics() -> pd.DataFrame:
    rows = get_all_metrics()
    return pd.DataFrame(rows)


PERIOD_DAYS = {"6mo": 182, "1y": 365, "2y": 730, "5y": 1825}


@st.cache_data(ttl=900, show_spinner=False)
def load_history(symbol: str, period: str = "1y"):
    """Serve price history from the local cache when it's fresh enough and
    covers the requested period; otherwise fall back to a network fetch."""
    days = PERIOD_DAYS.get(period, 365)
    cached = get_prices(symbol)
    if cached is not None and len(cached) > 30:
        age_days = (pd.Timestamp.now() - cached.index.max()).days
        span_days = (cached.index.max() - cached.index.min()).days
        if age_days <= 7 and span_days >= days * 0.8:
            return cached[cached.index >= cached.index.max() - pd.Timedelta(days=days)]
    fetched = fetch_history(symbol, period)
    if fetched is not None:
        return fetched
    # Network down but we have *something* local — stale beats blank.
    return cached


@st.cache_data(ttl=1800, show_spinner=False)
def load_news(symbol: str):
    return fetch_news(symbol)


def render_news_list(news: list):
    if not news:
        st.caption("No recent headlines available right now.")
        return
    for item in news:
        date_label = ""
        published = pd.to_datetime(item.get("published"), errors="coerce", utc=True)
        if pd.notna(published):
            date_label = f" · {published.strftime('%b %d')}"
        title = item.get("title", "")
        url = item.get("url", "")
        source = item.get("publisher") or "Yahoo Finance"
        if url:
            st.markdown(f"- [{title}]({url}) — {source}{date_label}")
        else:
            st.markdown(f"- {title} — {source}{date_label}")


def invalidate_data():
    load_metrics.clear()


def flash(message: str, kind: str = "success"):
    st.session_state["flash"] = (kind, message)


def show_flash(container):
    if "flash" in st.session_state:
        kind, message = st.session_state.pop("flash")
        getattr(container, kind)(message)


def run_sync(symbols, container) -> dict:
    """Sync tickers concurrently with a progress bar in `container`."""
    symbols = sorted(set(symbols))
    if not symbols:
        return {"synced": [], "failed": []}
    bar = container.progress(0.0, text=f"Syncing {len(symbols)} tickers…")

    def cb(done, total, sym):
        bar.progress(done / total, text=f"Syncing {done}/{total} · {sym}")

    results = sync_many(symbols, progress_cb=cb)
    bar.empty()
    invalidate_data()
    return results


def sync_and_report(symbols, container):
    results = run_sync(symbols, container)
    n_ok, n_fail = len(results["synced"]), len(results["failed"])
    if n_fail:
        failed = ", ".join(results["failed"][:12]) + ("…" if n_fail > 12 else "")
        flash(f"Synced {n_ok} tickers · {n_fail} failed ({failed}). Failed tickers stay on the watchlist and retry on the next sync.", "warning")
    else:
        flash(f"Synced {n_ok} tickers.")
    st.rerun()


def _style_fig(fig, height=360):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=10, r=10, t=42, b=10),
        font=dict(family="Inter, sans-serif", size=12),
    )
    return fig


def _extract_csv_symbols(upload_df: pd.DataFrame) -> list[str]:
    if upload_df is None or upload_df.empty:
        return []
    normalized_cols = {c.lower(): c for c in upload_df.columns}
    for key in ("symbol", "ticker", "tickers", "symbols"):
        if key in normalized_cols:
            col = normalized_cols[key]
            break
    else:
        col = upload_df.columns[0]
    series = upload_df[col].astype(str).str.strip().str.upper()
    return sorted({s for s in series if s and s not in ("NAN", "NONE")})


# ---------------------------------------------------------------------------
# Sidebar — watchlist & data management
# ---------------------------------------------------------------------------

st.sidebar.markdown("### ⚙️ Manage")
show_flash(st.sidebar)

all_symbols = get_tickers()

with st.sidebar.expander("➕ Add tickers", expanded=not all_symbols):
    with st.form("add_ticker_form", clear_on_submit=True):
        new_ticker = st.text_input("Ticker symbol", placeholder="e.g. AAPL")
        add_clicked = st.form_submit_button("Add & sync", type="primary", use_container_width=True)
    if add_clicked and new_ticker.strip():
        sym = new_ticker.strip().upper()
        with st.spinner(f"Adding {sym}…"):
            ok = add_and_sync(sym)
        invalidate_data()
        if ok:
            flash(f"Added and synced {sym}.")
        else:
            flash(f"{sym} saved to watchlist, but data fetch failed — it will retry on the next sync. Remove it below if the symbol is wrong.", "warning")
        st.rerun()

    bulk = st.text_area("Bulk add (comma-separated)", placeholder="AAPL, MSFT, NVDA")
    if st.button("Add all", use_container_width=True) and bulk.strip():
        symbols = sorted({s.strip().upper() for s in bulk.split(",") if s.strip()})
        for sym in symbols:
            add_ticker(sym)  # persist before any network call
        sync_and_report(symbols, st.sidebar)

with st.sidebar.expander("📥 Import CSV"):
    uploaded_csv = st.file_uploader("CSV with a Symbol/Ticker column", type=["csv"], key="csv_upload")
    if uploaded_csv is not None:
        try:
            upload_df = pd.read_csv(uploaded_csv)
        except Exception:
            upload_df = None
            st.error("Unable to read CSV. Please upload a valid file.")
        if upload_df is not None:
            csv_symbols = _extract_csv_symbols(upload_df)
            existing = set(all_symbols)
            new_syms = [s for s in csv_symbols if s not in existing]
            st.caption(f"{len(csv_symbols)} symbols found · {len(new_syms)} new")
            if st.button("Import", use_container_width=True, disabled=not new_syms):
                for sym in new_syms:
                    add_ticker(sym)
                sync_and_report(new_syms, st.sidebar)

with st.sidebar.expander("🎯 My holdings"):
    current_holdings = get_holdings()
    picked = st.multiselect(
        "Tickers you own",
        options=all_symbols,
        default=[s for s in current_holdings if s in all_symbols],
        key="holdings_picker",
    )
    if st.button("Save holdings", use_container_width=True, disabled=set(picked) == set(current_holdings)):
        set_holdings(picked)
        invalidate_data()
        flash(f"Saved {len(picked)} holdings.")
        st.rerun()

with st.sidebar.expander("🗑️ Remove tickers"):
    to_remove = st.multiselect("Select tickers", all_symbols, key="remove_picker")
    if st.button("Remove selected", use_container_width=True, disabled=not to_remove):
        for sym in to_remove:
            remove_ticker(sym)
        invalidate_data()
        flash(f"Removed {len(to_remove)} tickers.")
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔄 Data")

stale = get_stale_tickers(STALE_HOURS)
if all_symbols:
    st.sidebar.caption(
        f"{len(all_symbols)} tickers tracked · {len(stale)} stale (>{STALE_HOURS}h)"
    )
sync_cols = st.sidebar.columns(2)
if sync_cols[0].button("Sync stale", use_container_width=True, disabled=not stale):
    sync_and_report(stale, st.sidebar)
if sync_cols[1].button("Sync all", use_container_width=True, disabled=not all_symbols):
    sync_and_report(all_symbols, st.sidebar)

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

df = load_metrics()

last_sync = pd.to_datetime(df["last_updated"], errors="coerce").max() if "last_updated" in df.columns and not df.empty else None
last_sync_label = time_ago(last_sync) if last_sync is not None and pd.notna(last_sync) else "never"

# Staleness is a quiet pill in the header, not a full-width warning banner —
# the sync buttons live in the sidebar and the dashboard works fine on cached data.
stale_pill = ""
if all_symbols and stale:
    stale_label = "sync recommended" if len(stale) == len(all_symbols) else f"{len(stale)} stale"
    stale_pill = (
        '<span style="display:inline-block;margin-left:8px;padding:1px 9px;border-radius:999px;'
        'background:rgba(245,158,11,0.13);border:1px solid rgba(251,191,36,0.35);'
        f'color:#fbbf24;font-size:0.7rem;font-weight:600;">⟳ {stale_label}</span>'
    )

st.markdown(
    f"""
    <div class="app-header">
        <div>
            <h1>📈 Stock Dashboard</h1>
            <div class="sub">Coverage-aware 5-pillar buy scores · free Yahoo Finance data</div>
        </div>
        <div class="meta">
            {len(df) if not df.empty else 0} tickers tracked<br>
            Last sync: {last_sync_label}{stale_pill}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if df.empty:
    st.info("No tickers tracked yet — add some from the sidebar to get started.")
    st.stop()

# ---------------------------------------------------------------------------
# Prepare display frame
# ---------------------------------------------------------------------------

COLUMN_MAP = {
    "symbol": "Symbol",
    "name": "Name",
    "sector": "Sector",
    "price": "Price",
    "market_cap": "Market Cap",
    "pe_trailing": "Trailing P/E",
    "pe_forward": "Fwd P/E",
    "peg_ratio": "PEG",
    "projected_cagr": "Est Growth %",
    "beta": "Beta",
    "target_upside": "Target Upside %",
    "week_52_high": "52W High",
    "week_52_low": "52W Low",
    "rsi_14": "RSI(14)",
    "volume_20d_avg": "Vol 20d",
    "volume_50d_avg": "Vol 50d",
    "price_vs_50ma": "vs 50MA %",
    "price_vs_200ma": "vs 200MA %",
    "macd_signal": "MACD",
    "bb_position": "BB Position",
    "roc_10d": "ROC 10d",
    "exhaustion_level": "Exhaustion",
    "buy_score": "Buy Score",
    "rating_band": "Rating",
    "data_coverage": "Coverage %",
    "score_mode": "Mode",
    "score_valuation": "Valuation",
    "score_growth": "Growth",
    "score_profitability": "Profit",
    "score_momentum": "Momentum",
    "score_risk": "Risk",
    "adj_peg": "Value Δ",
    "adj_target": "Analyst Δ",
    "adj_pe_traj": "Trajectory Δ",
    "adj_exhaustion": "Exhaust Δ",
    "adj_dcf": "Intrinsic Δ",
    "dcf_value": "DCF Value",
    "dcf_upside": "DCF Upside %",
    "dcf_verdict": "DCF Verdict",
    "max_drawdown_1y": "Max DD %",
    "change_1w": "1W %",
    "change_1m": "1M %",
    "change_ytd": "YTD %",
    "roe": "ROE %",
    "gross_margin": "Gross M %",
    "operating_margin": "Op M %",
    "profit_margin": "Net M %",
    "revenue_growth": "Rev Growth %",
    "earnings_growth": "EPS Growth %",
    "debt_to_equity": "D/E",
    "current_ratio": "Current Ratio",
    "free_cashflow": "FCF",
    "num_analysts": "Analysts",
    "recommendation_mean": "Rec Mean",
    "next_earnings": "Earnings",
    "last_updated": "Updated",
}

display_df = df.rename(columns=COLUMN_MAP)
if "Sector" in display_df.columns:
    display_df["Sector"] = display_df["Sector"].fillna("Unknown").replace("", "Unknown")

# Sector-relative rank: percentile of buy score within its own sector, so a
# utility isn't judged on the same absolute scale as a semiconductor.
if "Buy Score" in display_df.columns and "Sector" in display_df.columns:
    _scores = pd.to_numeric(display_df["Buy Score"], errors="coerce")
    display_df["Sector %ile"] = (_scores.groupby(display_df["Sector"]).rank(pct=True) * 100).round(0)
    _sector_sizes = display_df.groupby("Sector")["Symbol"].transform("count")
    # A percentile is meaningless against 1-2 peers — blank it out there.
    display_df.loc[_sector_sizes < 3, "Sector %ile"] = float("nan")

# "All Metrics" is the default: every market/valuation/fundamental/technical
# metric, with the scoring internals (pillars, deltas, mode/coverage) left to
# the Scores view. Buy Score + Rating stay as the headline ranking.
VIEW_COLS = {
    "All Metrics": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating",
        "Price", "1W %", "1M %", "YTD %",
        "Market Cap", "DCF Value", "DCF Upside %", "DCF Verdict",
        "Target Upside %", "Trailing P/E", "Fwd P/E", "PEG",
        "Est Growth %", "Rev Growth %", "EPS Growth %",
        "ROE %", "Gross M %", "Op M %", "Net M %", "FCF", "D/E", "Current Ratio",
        "Beta", "Max DD %", "52W High", "52W Low",
        "RSI(14)", "Exhaustion", "vs 50MA %", "vs 200MA %", "MACD",
        "BB Position", "ROC 10d", "Vol 20d", "Vol 50d",
        "Analysts", "Rec Mean", "Earnings", "Updated",
    ],
    "Summary": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating", "Sector %ile",
        "DCF Upside %", "Target Upside %", "PEG", "Fwd P/E",
        "Est Growth %", "ROE %", "Max DD %",
        "Price", "1W %", "1M %", "YTD %", "Coverage %", "Earnings", "Updated",
    ],
    "Scores": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating", "Sector %ile",
        "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ", "Intrinsic Δ",
        "Mode", "Coverage %",
    ],
    "Fundamentals": [
        "Symbol", "Name", "Sector", "Market Cap",
        "ROE %", "Gross M %", "Op M %", "Net M %",
        "Rev Growth %", "EPS Growth %", "FCF",
        "D/E", "Current Ratio", "DCF Value", "DCF Upside %", "DCF Verdict",
        "Analysts", "Rec Mean", "Earnings",
    ],
    "Technicals": [
        "Symbol", "Name", "Sector", "Price", "1W %", "1M %", "YTD %",
        "RSI(14)", "Exhaustion", "Max DD %",
        "vs 50MA %", "vs 200MA %", "MACD", "BB Position", "ROC 10d",
        "Vol 20d", "Vol 50d", "Updated",
    ],
    "Full": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating", "Sector %ile", "Mode", "Coverage %",
        "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ", "Intrinsic Δ",
        "Price", "1W %", "1M %", "YTD %",
        "Market Cap", "DCF Value", "DCF Upside %", "DCF Verdict",
        "Trailing P/E", "Fwd P/E", "PEG", "Beta",
        "Est Growth %", "Target Upside %", "ROE %", "Gross M %", "Op M %", "Net M %",
        "Rev Growth %", "EPS Growth %", "FCF", "D/E", "Current Ratio",
        "52W High", "52W Low", "Max DD %",
        "RSI(14)", "Exhaustion", "vs 50MA %", "vs 200MA %", "MACD",
        "BB Position", "ROC 10d", "Vol 20d", "Vol 50d",
        "Analysts", "Rec Mean", "Earnings", "Updated",
    ],
}


def render_table(table_df: pd.DataFrame, held_symbols: set):
    """Color-coded table with click-to-sort column headers (numeric-aware,
    missing values always sort last). Rendered via a component iframe so the
    header clicks can run client-side without a Streamlit rerun."""
    cols = table_df.columns.tolist()
    head_parts = ["<tr>"]
    for col in cols:
        head_parts.append(f'<th title="Click to sort">{col}<span class="arrow"></span></th>')
    head_parts.append("</tr>")

    body_parts = []
    for _, row in table_df.iterrows():
        body_parts.append("<tr>")
        symbol = row.get("Symbol")
        for col in cols:
            val = row[col]
            style = cell_style(val, col)
            text = time_ago(val) if col == "Updated" else fmt(val, col)
            if col == "Symbol" and symbol in held_symbols:
                text = f"🎯 {text}"
            key = str(val) if col == "Updated" else sort_key(val, col)
            key = str(key).replace('"', "&quot;")
            body_parts.append(f'<td style="{style}" data-v="{key}">{text}</td>')
        body_parts.append("</tr>")

    inner_height = min(640, 46 + 34 * len(table_df))
    doc = sortable_table_doc("".join(head_parts), "".join(body_parts), inner_height)
    if hasattr(st, "iframe"):
        # st.iframe wants a file, so park the doc in a content-addressed temp file.
        doc_path = os.path.join(tempfile.gettempdir(), f"dash_table_{hashlib.md5(doc.encode()).hexdigest()}.html")
        if not os.path.exists(doc_path):
            with open(doc_path, "w") as fh:
                fh.write(doc)
        st.iframe(doc_path, height=inner_height + 18)
    else:
        components.html(doc, height=inner_height + 18, scrolling=False)


def render_cards(cards_df: pd.DataFrame, held_symbols: set):
    card_cols = st.columns(3)
    for idx, (_, row) in enumerate(cards_df.iterrows()):
        with card_cols[idx % 3]:
            symbol = row.get("Symbol", "")
            buy = row.get("Buy Score")
            tier = TIERS[score_tier(buy)]
            rating = row.get("Rating") or "—"
            held_mark = " 🎯" if symbol in held_symbols else ""

            pillar_html = ""
            for label in ("Valuation", "Growth", "Profit", "Momentum", "Risk"):
                value = row.get(label)
                if value is None or (isinstance(value, float) and value != value):
                    width, display_val, color = 0, "—", TIERS["neutral"]["fg"]
                else:
                    width = max(0, min(float(value) / 20 * 100, 100))
                    display_val = f"{float(value):.0f}/20"
                    color = TIERS[pillar_tier(value)]["fg"]
                pillar_html += (
                    f"<div class='pillar-row'><span>{label}</span><span>{display_val}</span></div>"
                    f"<div class='pillar-track'><div class='pillar-fill' style='width:{width:.0f}%;background:{color};'></div></div>"
                )

            st.markdown(
                f"""
                <div class="tcard">
                    <div class="head">
                        <div>
                            <div class="sym">{symbol}{held_mark}</div>
                            <div class="name">{row.get('Name') or ''}</div>
                        </div>
                        <div class="score" style="background:{tier['bg']};color:{tier['fg']};border:1px solid {tier['border']};">{fmt(buy, 'Buy Score')}</div>
                    </div>
                    <div>{badge(rating, RATING_TIER.get(rating, 'neutral'))} {badge(row.get('Mode') or '—')} {badge(f"Coverage {fmt(row.get('Coverage %'), 'Coverage %')}")}</div>
                    <div class="meta">
                        <span>Price <b>{fmt(row.get('Price'), 'Price')}</b></span>
                        <span>Mkt cap <b>{fmt_large_number(row.get('Market Cap'))}</b></span>
                        <span>Upside <b>{fmt(row.get('Target Upside %'), 'Target Upside %')}</b></span>
                    </div>
                    {pillar_html}
                </div>
                """,
                unsafe_allow_html=True,
            )


held_symbols = set(display_df.loc[display_df["is_held"] == 1, "Symbol"]) if "is_held" in display_df.columns else set()

tab_overview, tab_screener, tab_research, tab_detail = st.tabs(
    ["📊 Overview", "🔎 Screener", "🧪 Research Pack", "📈 Ticker Detail"]
)

# ---------------------------------------------------------------------------
# OVERVIEW
# ---------------------------------------------------------------------------

with tab_overview:
    scored = display_df.dropna(subset=["Buy Score"]) if "Buy Score" in display_df.columns else display_df.iloc[0:0]
    avg_buy = scored["Buy Score"].mean() if not scored.empty else None
    strong_buys = int((scored["Rating"] == "Strong Buy").sum()) if "Rating" in scored.columns else 0
    buys = int((scored["Rating"] == "Buy").sum()) if "Rating" in scored.columns else 0
    unsynced = len(display_df) - len(scored)
    total_mcap = display_df["Market Cap"].dropna().sum() if "Market Cap" in display_df.columns else None

    kpis = [
        ("Tracked tickers", f"{len(display_df):,}", f"{len(held_symbols)} holdings · {unsynced} awaiting sync"),
        ("Avg buy score", f"{avg_buy:.1f}" if avg_buy == avg_buy and avg_buy is not None else "—", f"{len(scored)} scored"),
        ("Buy-rated", f"{strong_buys + buys}", f"{strong_buys} strong buy · {buys} buy"),
        ("Combined mkt cap", fmt_large_number(total_mcap), "tracked universe"),
        ("Last sync", last_sync_label, f"{len(stale)} stale tickers"),
    ]
    kpi_cols = st.columns(len(kpis))
    for col, (label, value, sub) in zip(kpi_cols, kpis):
        col.markdown(
            f'<div class="kpi"><div class="label">{label}</div><div class="value">{value}</div><div class="sub">{sub}</div></div>',
            unsafe_allow_html=True,
        )

    # --- Top picks ---
    st.markdown('<div class="section-title">Top buy picks</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Highest composite buy scores across the tracked universe.</div>', unsafe_allow_html=True)
    top_picks = scored.nlargest(6, "Buy Score") if not scored.empty else scored
    if top_picks.empty:
        st.info("No scored tickers yet — run a sync from the sidebar.")
    else:
        pick_cols = st.columns(len(top_picks))
        for col, (_, row) in zip(pick_cols, top_picks.iterrows()):
            tier = TIERS[score_tier(row["Buy Score"])]
            rating = row.get("Rating") or "—"
            with col:
                st.markdown(
                    f"""
                    <div class="pick">
                        <div class="sym">{row['Symbol']}</div>
                        <div class="name">{row.get('Name') or ''}</div>
                        <div class="score" style="color:{tier['fg']};">{int(row['Buy Score'])}</div>
                        {badge(rating, RATING_TIER.get(rating, 'neutral'))}
                        <div class="sector">{row.get('Sector') or ''}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # --- Sector breakdown + score distribution ---
    chart_left, chart_right = st.columns([3, 2])
    with chart_left:
        st.markdown('<div class="section-title">Sector breakdown</div>', unsafe_allow_html=True)
        if not scored.empty and "Sector" in scored.columns:
            sector_stats = (
                scored.groupby("Sector")
                .agg(count=("Symbol", "count"), avg_buy=("Buy Score", "mean"))
                .reset_index()
                .sort_values("avg_buy", ascending=True)
            )
            fig = go.Figure(
                go.Bar(
                    y=sector_stats["Sector"],
                    x=sector_stats["avg_buy"],
                    orientation="h",
                    text=[f"{v:.0f} · {c} tickers" for v, c in zip(sector_stats["avg_buy"], sector_stats["count"])],
                    textposition="auto",
                    marker_color=[TIERS[score_tier(v)]["fg"] for v in sector_stats["avg_buy"]],
                    marker_opacity=0.85,
                )
            )
            fig.update_layout(title="Average buy score by sector", xaxis_title="", yaxis_title="")
            st.plotly_chart(_style_fig(fig, height=max(320, 26 * len(sector_stats) + 80)), use_container_width=True)
        else:
            st.info("No sector data yet.")
    with chart_right:
        st.markdown('<div class="section-title">Score distribution</div>', unsafe_allow_html=True)
        if not scored.empty:
            fig = go.Figure(
                go.Histogram(
                    x=scored["Buy Score"],
                    xbins=dict(start=0, end=100, size=5),
                    marker_color="#818cf8",
                    marker_line=dict(color="rgba(10,14,23,0.8)", width=1),
                )
            )
            fig.update_layout(title="Buy score histogram", xaxis_title="Buy score", yaxis_title="Tickers", bargap=0.05)
            st.plotly_chart(_style_fig(fig, height=380), use_container_width=True)

# ---------------------------------------------------------------------------
# SCREENER
# ---------------------------------------------------------------------------

with tab_screener:
    ctrl_cols = st.columns([1.1, 1.2, 1.1, 1.3, 1.3])
    with ctrl_cols[0]:
        view_mode = st.selectbox("Columns", list(VIEW_COLS.keys()), index=0)
    with ctrl_cols[1]:
        sort_options = [c for c in VIEW_COLS[view_mode] if c in display_df.columns and c != "Updated"]
        sort_by = st.selectbox("Sort by", sort_options, index=sort_options.index("Buy Score") if "Buy Score" in sort_options else 0)
    with ctrl_cols[2]:
        sort_dir = st.selectbox("Order", ["Descending", "Ascending"], index=0)
    with ctrl_cols[3]:
        all_sectors = sorted(display_df["Sector"].dropna().unique().tolist())
        sector_filter = st.multiselect("Sector", all_sectors, placeholder="All sectors")
    with ctrl_cols[4]:
        rating_filter = st.multiselect("Rating", RATING_ORDER, placeholder="All ratings")

    opt_cols = st.columns([1.1, 1.1, 2.8])
    with opt_cols[0]:
        view_type = st.radio("Display", ["Table", "Cards"], horizontal=True, label_visibility="collapsed")
    with opt_cols[1]:
        only_holdings = st.checkbox("🎯 Holdings only")
    with opt_cols[2]:
        mode_options = sorted(display_df["Mode"].dropna().unique().tolist()) if "Mode" in display_df.columns else []
        mode_filter = st.multiselect("Score mode", mode_options, placeholder="All score modes", label_visibility="collapsed")

    NUMERIC_FILTERS = [
        "Buy Score", "Sector %ile", "Coverage %", "DCF Upside %", "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "PEG", "Trailing P/E", "Fwd P/E", "Est Growth %", "Target Upside %",
        "ROE %", "Rev Growth %", "Max DD %", "D/E",
        "1W %", "1M %", "YTD %",
        "RSI(14)", "Beta", "Market Cap",
    ]
    numeric_ranges = {}
    with st.expander("Advanced numeric filters"):
        chosen = st.multiselect("Filter metrics", [c for c in NUMERIC_FILTERS if c in display_df.columns])
        for metric in chosen:
            clean = pd.to_numeric(display_df[metric], errors="coerce").dropna()
            if clean.empty:
                continue
            lo, hi = float(clean.min()), float(clean.max())
            if lo == hi:
                st.caption(f"{metric}: all values are {lo:.2f}")
                continue
            sel = st.slider(metric, lo, hi, (lo, hi), key=f"flt_{metric}")
            if sel != (lo, hi):
                numeric_ranges[metric] = sel

    filtered = display_df.copy()
    if only_holdings:
        filtered = filtered[filtered["Symbol"].isin(held_symbols)]
    if sector_filter:
        filtered = filtered[filtered["Sector"].isin(sector_filter)]
    if rating_filter and "Rating" in filtered.columns:
        filtered = filtered[filtered["Rating"].isin(rating_filter)]
    if mode_filter and "Mode" in filtered.columns:
        filtered = filtered[filtered["Mode"].isin(mode_filter)]
    for metric, (lo, hi) in numeric_ranges.items():
        series = pd.to_numeric(filtered[metric], errors="coerce")
        filtered = filtered[(series >= lo) & (series <= hi)]

    if sort_by in filtered.columns:
        filtered = filtered.sort_values(sort_by, ascending=(sort_dir == "Ascending"), na_position="last")

    active_cols = [c for c in VIEW_COLS[view_mode] if c in filtered.columns]

    info_col, export_col = st.columns([4, 1])
    info_col.caption(f"Showing {len(filtered)} of {len(display_df)} tickers")
    export_col.download_button(
        "📥 Export CSV",
        data=filtered[active_cols].to_csv(index=False),
        file_name=f"stock_dashboard_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    if filtered.empty:
        st.info("No tickers match the selected filters.")
    elif view_type == "Cards":
        render_cards(filtered, held_symbols)
    else:
        render_table(filtered[active_cols], held_symbols)

    # --- Compare ---
    compare_symbols = st.multiselect("🔍 Compare tickers", display_df["Symbol"].tolist(), placeholder="Pick 2-6 tickers to compare side by side")
    if compare_symbols:
        compare_cols = [
            "Symbol", "Name", "Buy Score", "Rating", "Mode", "Coverage %",
            "Valuation", "Growth", "Profit", "Momentum", "Risk",
            "Price", "Market Cap", "PEG", "Est Growth %", "Target Upside %",
        ]
        compare_df = display_df[display_df["Symbol"].isin(compare_symbols)]
        compare_df = compare_df[[c for c in compare_cols if c in compare_df.columns]]
        render_table(compare_df, held_symbols)

# ---------------------------------------------------------------------------
# RESEARCH PACK (Tier 2 — deterministic, free, no LLM)
# ---------------------------------------------------------------------------

def _research_metric_row(items):
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.metric(label, value)


with tab_research:
    r_symbols = display_df.sort_values("Buy Score", ascending=False, na_position="last")["Symbol"].tolist()
    research_symbol = st.selectbox("Ticker", r_symbols, key="research_symbol")

    raw_rows = df[df["symbol"] == research_symbol]
    raw_row = raw_rows.iloc[0].to_dict() if not raw_rows.empty else None

    if raw_row is None:
        st.info("Pick a ticker to build its research pack.")
    elif raw_row.get("buy_score") is None:
        st.warning(f"{research_symbol} hasn't been synced yet — run a sync from the sidebar first.")
    else:
        price = raw_row.get("price")
        buy = raw_row.get("buy_score")
        tier = TIERS[score_tier(buy)]
        rating = raw_row.get("rating_band") or "—"
        verdict = raw_row.get("dcf_verdict")
        verdict_tier = {"Undervalued": "strong_buy", "Fairly Valued": "hold", "Overvalued": "strong_sell"}.get(verdict, "neutral")

        sector_pct = None
        if "Sector %ile" in display_df.columns:
            pct_vals = display_df.loc[display_df["Symbol"] == research_symbol, "Sector %ile"]
            if not pct_vals.empty and pd.notna(pct_vals.iloc[0]):
                sector_pct = float(pct_vals.iloc[0])
        sector_pct_badge = (
            badge(f"Sector rank: {sector_pct:.0f}th %ile", score_tier(sector_pct))
            if sector_pct is not None else ""
        )

        head_l, head_r = st.columns([4, 1])
        with head_l:
            st.markdown(
                f"""
                <div style="display:flex;align-items:center;gap:14px;margin:6px 0 2px;">
                    <div style="font-family:'Space Grotesk',sans-serif;font-size:1.5rem;font-weight:700;">{research_symbol}</div>
                    <div style="color:#8b95a8;">{raw_row.get('name') or ''}</div>
                </div>
                <div style="margin-bottom:10px;">
                    {badge(rating, RATING_TIER.get(rating, 'neutral'))}
                    {badge(f"DCF: {verdict}" if verdict else "DCF: n/a", verdict_tier)}
                    {badge(raw_row.get('sector') or 'Unknown')}
                    {sector_pct_badge}
                    {badge(f"Earnings: {raw_row.get('next_earnings') or 'n/a'}")}
                </div>
                """,
                unsafe_allow_html=True,
            )
        with head_r:
            st.markdown(
                f"""
                <div style="text-align:center;background:{tier['bg']};border:1px solid {tier['border']};border-radius:14px;padding:8px;">
                    <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.12em;color:{tier['fg']};">Buy score</div>
                    <div style="font-family:'Space Grotesk',sans-serif;font-size:1.9rem;font-weight:700;color:{tier['fg']};">{fmt(buy, 'Buy Score')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # --- 1. Intrinsic value (DCF) ---
        st.markdown('<div class="section-title">💰 Intrinsic value (2-stage DCF)</div>', unsafe_allow_html=True)
        # Recompute live from stored fundamentals so we can show the assumptions;
        # falls back to the values stored at sync time.
        dcf = dcf_valuation(
            fcf=raw_row.get("free_cashflow"),
            shares=raw_row.get("shares_outstanding"),
            price=price,
            growth_pct=raw_row.get("projected_cagr"),
            beta=raw_row.get("beta"),
            cash=raw_row.get("total_cash"),
            debt=raw_row.get("total_debt"),
        )
        if dcf is None and raw_row.get("dcf_value") is not None:
            dcf = {
                "value": raw_row.get("dcf_value"), "upside": raw_row.get("dcf_upside"),
                "bull": raw_row.get("dcf_bull"), "bear": raw_row.get("dcf_bear"),
                "verdict": raw_row.get("dcf_verdict"), "growth_used": None, "discount_rate": None,
            }
        if dcf is None:
            st.info("DCF unavailable — requires positive free cash flow and shares outstanding. "
                    "For pre-profit or non-equity names, lean on the technical/momentum read instead.")
        else:
            _research_metric_row([
                ("Current price", fmt(price, "Price")),
                ("Intrinsic value", fmt(dcf["value"], "DCF Value")),
                ("DCF upside", fmt(dcf["upside"], "DCF Upside %")),
                ("Bull target", fmt(dcf["bull"], "DCF Value")),
                ("Bear target", fmt(dcf["bear"], "DCF Value")),
                ("Analyst upside", fmt(raw_row.get("target_upside"), "Target Upside %")),
            ])
            if dcf.get("growth_used") is not None:
                st.caption(
                    f"Assumptions: FCF grows {dcf['growth_used']}%/yr fading to 2.5% terminal · "
                    f"discount rate {dcf['discount_rate']}% (beta-scaled) · net cash included. "
                    "A deliberately conservative, fully mechanical model — treat it as a sanity check, not a price target."
                )

        scenarios = scenario_cagr(raw_row.get("projected_cagr"), raw_row.get("beta"), raw_row.get("data_coverage"))
        if scenarios:
            bear_b = badge(f"Bear {scenarios['bear']:.0f}%", "strong_sell")
            base_b = badge(f"Base {scenarios['base']:.0f}%", "hold")
            bull_b = badge(f"Bull {scenarios['bull']:.0f}%", "strong_buy")
            st.markdown(
                f"**Expected CAGR scenarios (3-4yr):** {bear_b} {base_b} {bull_b}",
                unsafe_allow_html=True,
            )

        # --- 2. Quality & balance sheet ---
        st.markdown('<div class="section-title">🏦 Quality & balance sheet</div>', unsafe_allow_html=True)
        _research_metric_row([
            ("ROE", fmt(raw_row.get("roe"), "ROE %")),
            ("Gross margin", fmt(raw_row.get("gross_margin"), "Gross M %")),
            ("Op margin", fmt(raw_row.get("operating_margin"), "Op M %")),
            ("Net margin", fmt(raw_row.get("profit_margin"), "Net M %")),
            ("FCF (ttm)", fmt(raw_row.get("free_cashflow"), "FCF")),
        ])
        _research_metric_row([
            ("Revenue growth", fmt(raw_row.get("revenue_growth"), "Rev Growth %")),
            ("Earnings growth", fmt(raw_row.get("earnings_growth"), "EPS Growth %")),
            ("Debt / equity", fmt(raw_row.get("debt_to_equity"), "D/E")),
            ("Current ratio", fmt(raw_row.get("current_ratio"), "Current Ratio")),
            ("Analysts", fmt(raw_row.get("num_analysts"), "Analysts")),
        ])

        # --- 3. Risk & stress ---
        st.markdown('<div class="section-title">⚠️ Risk & stress</div>', unsafe_allow_html=True)
        _research_metric_row([
            ("Beta", fmt(raw_row.get("beta"), "Beta")),
            ("Max drawdown (1y)", fmt(raw_row.get("max_drawdown_1y"), "Max DD %")),
            ("RSI(14)", fmt(raw_row.get("rsi_14"), "RSI(14)")),
            ("Exhaustion", raw_row.get("exhaustion_level") or "—"),
            ("52W high", fmt(raw_row.get("week_52_high"), "52W High")),
            ("52W low", fmt(raw_row.get("week_52_low"), "52W Low")),
        ])
        st.caption(
            "Recession stress rule of thumb: expect a drawdown of roughly beta × market decline. "
            "In a -25% market, a beta-{b} name sketches to ~{s}.".format(
                b=f"{raw_row.get('beta'):.1f}" if isinstance(raw_row.get("beta"), (int, float)) else "1.0",
                s=f"-{abs((raw_row.get('beta') or 1.0) * 25):.0f}%" if isinstance(raw_row.get("beta"), (int, float)) else "-25%",
            )
        )

        with st.expander("📐 Correlation vs my holdings (diversification check)"):
            corr_targets = sorted(h for h in held_symbols if h != research_symbol)
            if not corr_targets:
                st.info("Tag some holdings in the sidebar to enable the correlation check.")
            else:
                corr_key = f"corr_{research_symbol}"
                if st.button(f"Compute vs {len(corr_targets)} holdings (fetches 1y prices)", key="corr_btn"):
                    with st.spinner("Computing daily-return correlations…"):
                        base_hist = load_history(research_symbol, "1y")
                        rows = []
                        if base_hist is not None:
                            base_ret = base_hist["Close"].pct_change().dropna()
                            for h_sym in corr_targets:
                                h_hist = load_history(h_sym, "1y")
                                if h_hist is None:
                                    continue
                                joined = pd.concat(
                                    [base_ret, h_hist["Close"].pct_change().dropna()],
                                    axis=1, join="inner",
                                ).dropna()
                                if len(joined) > 40:
                                    rows.append({"Holding": h_sym, "Correlation": round(float(joined.iloc[:, 0].corr(joined.iloc[:, 1])), 2)})
                        st.session_state[corr_key] = pd.DataFrame(rows).sort_values("Correlation", ascending=False) if rows else None
                corr_df = st.session_state.get(corr_key)
                if corr_df is not None and isinstance(corr_df, pd.DataFrame) and not corr_df.empty:
                    avg_corr = corr_df["Correlation"].mean()
                    st.dataframe(corr_df, hide_index=True, use_container_width=True)
                    note = (
                        "high overlap — adds little diversification" if avg_corr > 0.6
                        else "moderate overlap" if avg_corr > 0.35
                        else "good diversifier vs the current book"
                    )
                    st.markdown(f"Average correlation **{avg_corr:.2f}** → {note}.")
                elif corr_key in st.session_state:
                    st.warning("Could not fetch enough overlapping price history to compute correlations.")

        # --- 4. Execution plan ---
        st.markdown('<div class="section-title">🎯 Execution plan</div>', unsafe_allow_html=True)
        plan = entry_plan(raw_row)
        sizing = position_plan(raw_row)
        exec_l, exec_r = st.columns(2)
        with exec_l:
            st.markdown("**Entry & stops**")
            if plan:
                if plan["entry_low"] and plan["entry_high"]:
                    st.markdown(f"- Entry zone: **${plan['entry_low']:,.2f} – ${plan['entry_high']:,.2f}**")
                ma50_text = f"${plan['ma50']:,.2f}" if plan["ma50"] else "—"
                ma200_text = f"${plan['ma200']:,.2f}" if plan["ma200"] else "—"
                st.markdown(f"- 50-day MA: {ma50_text} · 200-day MA: {ma200_text}")
                st.markdown(f"- Hard stop: **${plan['hard_stop']:,.2f}** ({(plan['hard_stop'] / price - 1) * 100:.0f}% from current)")
                st.caption(plan["note"])
            else:
                st.caption("Not enough data for an entry plan.")
        with exec_r:
            st.markdown("**Position sizing**")
            st.markdown(f"- Classification: **{sizing['bucket']}** · suggested weight **{sizing['weight']}**")
            st.caption(sizing["rationale"].capitalize() if sizing["rationale"] else "")
            st.caption(sizing["dca"])

        # --- 5. 22V idea-to-equity matrix row ---
        st.markdown('<div class="section-title">🧮 Idea-to-equity matrix (22V style)</div>', unsafe_allow_html=True)
        traj = raw_row.get("adj_pe_traj")
        revisions = "+" if isinstance(traj, (int, float)) and traj > 0 else ("-" if isinstance(traj, (int, float)) and traj < 0 else "")
        matrix = pd.DataFrame([{
            "Company": raw_row.get("name") or research_symbol,
            "Ticker": research_symbol,
            "Technical (0-4)": raw_row.get("technical_score"),
            "Commentary (0-4)": raw_row.get("commentary_score"),
            "Revisions": revisions,
            "Mkt Cap": fmt_large_number(raw_row.get("market_cap")),
            "Fwd P/E": fmt(raw_row.get("pe_forward"), "Fwd P/E"),
            "Trail P/E": fmt(raw_row.get("pe_trailing"), "Trailing P/E"),
            "PEG": fmt(raw_row.get("peg_ratio"), "PEG"),
            "Bear/Base/Bull CAGR": (f"{scenarios['bear']:.0f}% / {scenarios['base']:.0f}% / {scenarios['bull']:.0f}%" if scenarios else "—"),
            "Buy Score": buy,
        }])
        st.dataframe(matrix, hide_index=True, use_container_width=True)

        # --- 6. Recent headlines ---
        st.markdown('<div class="section-title">📰 Recent headlines</div>', unsafe_allow_html=True)
        ticker_news = load_news(research_symbol)
        render_news_list(ticker_news)

        # --- 7. LLM memo prompt export ---
        st.markdown('<div class="section-title">📋 Deep-dive memo prompt (for any LLM)</div>', unsafe_allow_html=True)
        st.caption(
            "The qualitative half of the memo (moat, systems map, second-order effects) needs an LLM. "
            "This prompt embeds the verified numbers above plus your current holdings, so the model "
            "analyzes real data instead of inventing it. Copy it into Claude / ChatGPT / Gemini (free tiers work)."
        )
        holdings_rows = df[df["is_held"] == 1][["symbol", "sector", "buy_score"]].to_dict("records") if "is_held" in df.columns else []
        memo_prompt = build_research_prompt(raw_row, holdings_rows, news=ticker_news)
        with st.expander("Show prompt", expanded=False):
            st.code(memo_prompt, language=None)
        st.download_button(
            "⬇️ Download prompt (.txt)",
            data=memo_prompt,
            file_name=f"research_prompt_{research_symbol}_{datetime.now().strftime('%Y%m%d')}.txt",
            mime="text/plain",
        )

# ---------------------------------------------------------------------------
# TICKER DETAIL
# ---------------------------------------------------------------------------

with tab_detail:
    symbols_sorted = display_df.sort_values("Buy Score", ascending=False, na_position="last")["Symbol"].tolist()
    _label_rows = display_df.set_index("Symbol")

    def _detail_label(sym: str) -> str:
        r = _label_rows.loc[sym]
        score = r.get("Buy Score")
        score_txt = f"{score:.0f}" if isinstance(score, (int, float)) and score == score else "—"
        name = str(r.get("Name") or "")[:26]
        return f"{sym} · {score_txt} · {name}"

    sel_col, period_col = st.columns([3, 1])
    with sel_col:
        selected_symbols = st.multiselect(
            "Tickers — pick one for a deep-dive, or 2-4 to compare",
            symbols_sorted,
            default=symbols_sorted[:1],
            format_func=_detail_label,
            max_selections=4,
            key="detail_symbols",
        )
    with period_col:
        period = st.selectbox("Period", ["6mo", "1y", "2y", "5y"], index=1)

    PALETTE = ["#22d3ee", "#a78bfa", "#fbbf24", "#34d399"]

    if not selected_symbols:
        st.info("Pick at least one ticker above.")
    elif len(selected_symbols) > 1:
        # ------------------------- COMPARISON MODE -------------------------
        fig = go.Figure()
        missing = []
        for i, sym in enumerate(selected_symbols):
            hist = load_history(sym, period)
            if hist is None or len(hist) < 2:
                missing.append(sym)
                continue
            rel = (hist["Close"] / hist["Close"].iloc[0] - 1) * 100
            fig.add_trace(go.Scatter(
                x=hist.index, y=rel, mode="lines", name=sym,
                line=dict(color=PALETTE[i % len(PALETTE)], width=2),
            ))
        fig.update_layout(title=f"Relative performance — {period}", yaxis_title="% change", hovermode="x unified")
        st.plotly_chart(_style_fig(fig, height=420), use_container_width=True)
        if missing:
            st.caption(f"No price history available for: {', '.join(missing)}")

        st.markdown('<div class="section-title">Side-by-side metrics</div>', unsafe_allow_html=True)
        COMPARE_METRICS = [
            "Buy Score", "Rating", "Sector", "Sector %ile",
            "Price", "1W %", "1M %", "YTD %",
            "Market Cap", "DCF Upside %", "DCF Verdict", "Target Upside %",
            "PEG", "Fwd P/E", "Trailing P/E", "Est Growth %", "Rev Growth %", "EPS Growth %",
            "ROE %", "Gross M %", "Net M %", "FCF", "D/E", "Beta",
            "Max DD %", "RSI(14)", "Exhaustion", "Earnings",
        ]
        parts = ['<div class="dash-table-wrap"><table class="dash-table"><thead><tr><th>Metric</th>']
        for sym in selected_symbols:
            parts.append(f"<th>{sym}</th>")
        parts.append("</tr></thead><tbody>")
        for metric in COMPARE_METRICS:
            if metric not in _label_rows.columns:
                continue
            parts.append(f"<tr><td>{metric}</td>")
            for sym in selected_symbols:
                val = _label_rows.loc[sym, metric] if sym in _label_rows.index else None
                parts.append(f'<td style="{cell_style(val, metric)}">{fmt(val, metric)}</td>')
            parts.append("</tr>")
        parts.append("</tbody></table></div>")
        st.markdown("".join(parts), unsafe_allow_html=True)

        st.markdown('<div class="section-title">Pillar comparison</div>', unsafe_allow_html=True)
        pillar_names = ["Valuation", "Growth", "Profit", "Momentum", "Risk"]
        fig2 = go.Figure()
        for i, sym in enumerate(selected_symbols):
            if sym not in _label_rows.index:
                continue
            vals = [_label_rows.loc[sym].get(p) for p in pillar_names]
            fig2.add_trace(go.Bar(
                name=sym, x=pillar_names, y=vals,
                marker_color=PALETTE[i % len(PALETTE)], marker_opacity=0.85,
            ))
        fig2.update_layout(barmode="group", yaxis_title="Pillar score (0-20)", yaxis_range=[0, 20])
        st.plotly_chart(_style_fig(fig2, height=340), use_container_width=True)
    else:
        # -------------------------- DEEP-DIVE MODE -------------------------
        selected_symbol = selected_symbols[0]
        row = display_df[display_df["Symbol"] == selected_symbol].iloc[0]
        buy = row.get("Buy Score")
        tier = TIERS[score_tier(buy)]
        rating = row.get("Rating") or "—"

        head_left, head_right = st.columns([3, 1])
        with head_left:
            st.markdown(
                f"""
                <div style="display:flex;align-items:center;gap:14px;margin:6px 0 2px;">
                    <div style="font-family:'Space Grotesk',sans-serif;font-size:1.5rem;font-weight:700;">{selected_symbol}</div>
                    <div style="color:#8b95a8;">{row.get('Name') or ''}</div>
                </div>
                <div style="margin-bottom:8px;">{badge(rating, RATING_TIER.get(rating, 'neutral'))} {badge(row.get('Mode') or '—')} {badge(row.get('Sector') or 'Unknown')} {badge(f"Coverage {fmt(row.get('Coverage %'), 'Coverage %')}")}</div>
                """,
                unsafe_allow_html=True,
            )
        with head_right:
            st.markdown(
                f"""
                <div style="text-align:center;background:{tier['bg']};border:1px solid {tier['border']};border-radius:14px;padding:10px;">
                    <div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:0.12em;color:{tier['fg']};">Buy score</div>
                    <div style="font-family:'Space Grotesk',sans-serif;font-size:2.2rem;font-weight:700;color:{tier['fg']};">{fmt(buy, 'Buy Score')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # --- Pillars & adjustments ---
        pillar_cols = st.columns(5)
        for col, label in zip(pillar_cols, ("Valuation", "Growth", "Profit", "Momentum", "Risk")):
            pv = row.get(label)
            with col:
                if pv is None or (isinstance(pv, float) and pv != pv):
                    st.metric(label, "—")
                else:
                    st.metric(label, f"{pv:.0f}/20")
                    st.progress(min(max(pv / 20, 0.0), 1.0))

        adj_items = [
            ("Value premium", row.get("Value Δ")),
            ("Analyst conviction", row.get("Analyst Δ")),
            ("Earnings trajectory", row.get("Trajectory Δ")),
            ("Trend exhaustion", row.get("Exhaust Δ")),
            ("Intrinsic value", row.get("Intrinsic Δ")),
        ]
        adj_html = " ".join(
            badge(
                f"{label} {av:+.0f}",
                "strong_buy" if av > 0 else ("strong_sell" if av < 0 else "neutral"),
            )
            for label, av in adj_items
            if isinstance(av, (int, float)) and not (isinstance(av, float) and av != av)
        )
        if adj_html:
            st.markdown(f'<div style="margin:4px 0 10px;">Conviction adjustments: {adj_html}</div>', unsafe_allow_html=True)

        # --- Key metrics ---
        metric_rows = [
            [
                ("Price", fmt(row.get("Price"), "Price")),
                ("Market cap", fmt_large_number(row.get("Market Cap"))),
                ("Trailing P/E", fmt(row.get("Trailing P/E"), "Trailing P/E")),
                ("Fwd P/E", fmt(row.get("Fwd P/E"), "Fwd P/E")),
                ("PEG", fmt(row.get("PEG"), "PEG")),
                ("Beta", fmt(row.get("Beta"), "Beta")),
            ],
            [
                ("Est growth", fmt(row.get("Est Growth %"), "Est Growth %")),
                ("Target upside", fmt(row.get("Target Upside %"), "Target Upside %")),
                ("52W high", fmt(row.get("52W High"), "52W High")),
                ("52W low", fmt(row.get("52W Low"), "52W Low")),
                ("RSI(14)", fmt(row.get("RSI(14)"), "RSI(14)")),
                ("Exhaustion", row.get("Exhaustion") or "—"),
            ],
        ]
        for metric_row in metric_rows:
            cols = st.columns(len(metric_row))
            for col, (label, value) in zip(cols, metric_row):
                col.metric(label, value)

        # --- Charts (price history only — cached, no full info fetch) ---
        hist = load_history(selected_symbol, period)
        if hist is None:
            st.warning("Could not load price history right now.")
        else:
            chart_left, chart_right = st.columns(2)
            with chart_left:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"], mode="lines", name="Close", line=dict(color="#22d3ee", width=2)))
                fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"].rolling(50).mean(), mode="lines", name="50 MA", line=dict(color="#fbbf24", width=1.4)))
                fig.add_trace(go.Scatter(x=hist.index, y=hist["Close"].rolling(200).mean(), mode="lines", name="200 MA", line=dict(color="#f472b6", width=1.4)))
                fig.update_layout(title=f"{selected_symbol} price", yaxis_title="Price")
                st.plotly_chart(_style_fig(fig, height=400), use_container_width=True)
            with chart_right:
                fig2 = go.Figure()
                fig2.add_trace(go.Bar(x=hist.index, y=hist["Volume"], name="Volume", marker_color="rgba(129, 140, 248, 0.55)"))
                fig2.add_trace(go.Scatter(x=hist.index, y=hist["Volume"].rolling(20).mean(), mode="lines", name="20d avg", line=dict(color="#fbbf24", width=1.6)))
                fig2.update_layout(title=f"{selected_symbol} volume", yaxis_title="Volume")
                st.plotly_chart(_style_fig(fig2, height=400), use_container_width=True)

        desc = row.get("description")
        if isinstance(desc, str) and desc.strip():
            with st.expander("Company description"):
                st.markdown(desc)

        with st.expander("📰 Recent headlines"):
            render_news_list(load_news(selected_symbol))

        detail_actions = st.columns([1, 5])
        if detail_actions[0].button("🗑️ Remove ticker", key="remove_detail"):
            remove_ticker(selected_symbol)
            invalidate_data()
            flash(f"Removed {selected_symbol}.")
            st.rerun()
