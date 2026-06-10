import streamlit as st
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
)
from src.sync import add_and_sync, sync_many
from src.fetcher import fetch_history
from src.ui import (
    inject_css,
    fmt,
    fmt_large_number,
    time_ago,
    cell_style,
    badge,
    score_tier,
    pillar_tier,
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


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol: str, period: str = "1y"):
    return fetch_history(symbol, period)


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

st.markdown(
    f"""
    <div class="app-header">
        <div>
            <h1>📈 Stock Dashboard</h1>
            <div class="sub">Coverage-aware 5-pillar buy scores · free Yahoo Finance data</div>
        </div>
        <div class="meta">
            {len(df) if not df.empty else 0} tickers tracked<br>
            Last sync: {last_sync_label}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

if df.empty:
    st.info("No tickers tracked yet — add some from the sidebar to get started.")
    st.stop()

if stale and len(stale) == len(all_symbols):
    st.warning(f"All data is older than {STALE_HOURS}h (or never synced). Use **Sync stale** in the sidebar to refresh — the dashboard stays usable while you decide.")

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
    "last_updated": "Updated",
}

display_df = df.rename(columns=COLUMN_MAP)
if "Sector" in display_df.columns:
    display_df["Sector"] = display_df["Sector"].fillna("Unknown").replace("", "Unknown")

VIEW_COLS = {
    "Summary": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating", "Mode", "Coverage %",
        "Price", "Market Cap", "Est Growth %", "Target Upside %", "Updated",
    ],
    "Scores": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating",
        "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ",
        "Mode", "Coverage %",
    ],
    "Technicals": [
        "Symbol", "Name", "Sector", "Price", "RSI(14)", "Exhaustion",
        "vs 50MA %", "vs 200MA %", "MACD", "BB Position", "ROC 10d",
        "Vol 20d", "Vol 50d", "Updated",
    ],
    "Full": [
        "Symbol", "Name", "Sector", "Buy Score", "Rating", "Mode", "Coverage %",
        "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ",
        "Price", "Market Cap", "Trailing P/E", "Fwd P/E", "PEG", "Beta",
        "Est Growth %", "Target Upside %", "52W High", "52W Low",
        "RSI(14)", "Exhaustion", "vs 50MA %", "vs 200MA %", "MACD",
        "BB Position", "ROC 10d", "Vol 20d", "Vol 50d", "Updated",
    ],
}


def render_table(table_df: pd.DataFrame, held_symbols: set):
    cols = table_df.columns.tolist()
    parts = ['<div class="dash-table-wrap"><table class="dash-table"><thead><tr>']
    for col in cols:
        parts.append(f"<th>{col}</th>")
    parts.append("</tr></thead><tbody>")
    for _, row in table_df.iterrows():
        parts.append("<tr>")
        symbol = row.get("Symbol")
        for col in cols:
            val = row[col]
            style = cell_style(val, col)
            text = time_ago(val) if col == "Updated" else fmt(val, col)
            if col == "Symbol" and symbol in held_symbols:
                text = f"🎯 {text}"
            parts.append(f'<td style="{style}">{text}</td>')
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


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

tab_overview, tab_screener, tab_detail = st.tabs(["📊 Overview", "🔎 Screener", "📈 Ticker Detail"])

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
        "Buy Score", "Coverage %", "Valuation", "Growth", "Profit", "Momentum", "Risk",
        "PEG", "Trailing P/E", "Fwd P/E", "Est Growth %", "Target Upside %",
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
# TICKER DETAIL
# ---------------------------------------------------------------------------

with tab_detail:
    symbols_sorted = display_df.sort_values("Buy Score", ascending=False, na_position="last")["Symbol"].tolist()
    sel_col, period_col = st.columns([3, 1])
    with sel_col:
        selected_symbol = st.selectbox("Ticker", symbols_sorted, key="chart_symbol")
    with period_col:
        period = st.selectbox("Period", ["6mo", "1y", "2y", "5y"], index=1)

    if selected_symbol:
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

        detail_actions = st.columns([1, 5])
        if detail_actions[0].button("🗑️ Remove ticker", key="remove_detail"):
            remove_ticker(selected_symbol)
            invalidate_data()
            flash(f"Removed {selected_symbol}.")
            st.rerun()
