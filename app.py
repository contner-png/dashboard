import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

from src.database import init_db, add_ticker, remove_ticker, get_tickers, get_all_metrics, init_holdings, toggle_holding, get_holdings, is_held
from src.sync import sync_ticker, sync_all
from src.fetcher import fetch_ticker_data

st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")

# Initialize database
init_db()
init_holdings()

st.title("📈 Stock Dashboard")
st.markdown("Track your stocks with auto-syncing metrics, exhaustion signals, and scoring.")

# Sidebar
st.sidebar.header("Controls")

# Add ticker
new_ticker = st.sidebar.text_input("Add Ticker", placeholder="e.g., AAPL").strip().upper()
if st.sidebar.button("Add") and new_ticker:
    with st.spinner(f"Fetching {new_ticker}..."):
        if sync_ticker(new_ticker):
            st.sidebar.success(f"Added {new_ticker}")
            st.rerun()
        else:
            st.sidebar.error(f"Could not fetch {new_ticker}")

# Bulk add
bulk_tickers = st.sidebar.text_area("Bulk Add (comma-separated)", placeholder="AAPL, MSFT, NVDA, TSLA")
if st.sidebar.button("Bulk Add") and bulk_tickers:
    symbols = [s.strip().upper() for s in bulk_tickers.split(",") if s.strip()]
    progress = st.sidebar.progress(0)
    for i, sym in enumerate(symbols):
        sync_ticker(sym)
        progress.progress((i + 1) / len(symbols))
    st.sidebar.success(f"Added {len(symbols)} tickers")
    st.rerun()

# Sync controls
st.sidebar.markdown("---")
if st.sidebar.button("🔄 Sync All Now"):
    with st.spinner("Syncing all tickers..."):
        synced = sync_all()
    st.sidebar.success(f"Synced {len(synced)} tickers")
    st.rerun()

# Auto-refresh
auto_refresh = st.sidebar.checkbox("Auto-refresh every 5 min", value=False)
if auto_refresh:
    st.sidebar.markdown("*(Manual refresh recommended for now)*")

# Remove ticker
st.sidebar.markdown("---")
st.sidebar.subheader("Remove Ticker")
to_remove = st.sidebar.selectbox("Select ticker", [""] + get_tickers())
if st.sidebar.button("Remove") and to_remove:
    remove_ticker(to_remove)
    st.sidebar.success(f"Removed {to_remove}")
    st.rerun()

# Portfolio / Holdings
st.sidebar.markdown("---")
st.sidebar.subheader("🎯 My Holdings")
all_symbols = get_tickers()
current_holdings = get_holdings()

# Initialize session state for batched selections
if "pending_holdings" not in st.session_state:
    st.session_state.pending_holdings = set(current_holdings)

with st.sidebar.expander(f"Select Holdings ({len(current_holdings)} selected)", expanded=False):
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("✅ Select All", use_container_width=True, key="btn_select_all"):
            st.session_state.pending_holdings = set(all_symbols)
            st.rerun()
    with col_b:
        if st.button("❌ Clear All", use_container_width=True, key="btn_clear_all"):
            st.session_state.pending_holdings = set()
            st.rerun()

    st.markdown("---")
    # Build a 3-column checkbox grid for rapid multi-select
    cols_per_row = 3
    for i in range(0, len(all_symbols), cols_per_row):
        row_symbols = all_symbols[i:i + cols_per_row]
        cols = st.columns(cols_per_row)
        for j, sym in enumerate(row_symbols):
            with cols[j]:
                is_checked = st.checkbox(
                    sym,
                    value=sym in st.session_state.pending_holdings,
                    key=f"hold_{sym}",
                )
                if is_checked:
                    st.session_state.pending_holdings.add(sym)
                else:
                    st.session_state.pending_holdings.discard(sym)

    # Apply button — only writes to DB when clicked
    pending = st.session_state.pending_holdings
    changed = pending != set(current_holdings)
    st.markdown("---")
    apply_col, count_col = st.columns([1, 2])
    with apply_col:
        apply_btn = st.button(
            "🔄 Apply",
            type="primary",
            use_container_width=True,
            disabled=not changed,
            key="btn_apply_holdings",
        )
    with count_col:
        st.caption(f"**{len(pending)}** selected")

    if apply_btn:
        # Write pending selections to DB
        for sym in pending:
            if sym not in current_holdings:
                toggle_holding(sym, True)
        for sym in current_holdings:
            if sym not in pending:
                toggle_holding(sym, False)
        st.session_state.pending_holdings = set(get_holdings())
        st.success(f"Saved: {len(pending)} holdings")
        st.rerun()

# Main dashboard
metrics = get_all_metrics()

if not metrics:
    st.info("No tickers tracked yet. Add some from the sidebar!")
    st.stop()

# Format for display
df = pd.DataFrame(metrics)

# Rename columns for display
column_map = {
    "symbol": "Symbol",
    "name": "Name",
    "sector": "Sector",
    "price": "Price",
    "pe_trailing": "Trailing P/E",
    "pe_forward": "Fwd PE",
    "peg_ratio": "PEG",
    "projected_cagr": "Analyst Est Growth %",
    "beta": "Beta",
    "target_upside": "Target Upside %",
    "week_52_high": "52W High",
    "week_52_low": "52W Low",
    "rsi_14": "RSI(14)",
    "volume_20d_avg": "Vol 20d",
    "volume_50d_avg": "Vol 50d",
    "price_vs_50ma": "vs 50MA (%)",
    "price_vs_200ma": "vs 200MA (%)",
    "macd_signal": "MACD",
    "bb_position": "BB Position",
    "roc_10d": "ROC(10d)",
    "exhaustion_level": "Exhaustion",
    "technical_score": "Tech Score",
    "commentary_score": "Comm Score",
    "buy_score": "Buy Score",
    "rating_band": "Rating",
    "score_valuation": "Valuation",
    "score_growth": "Growth",
    "score_profitability": "Profit",
    "score_momentum": "Momentum",
    "score_risk": "Risk",
    "adj_technical": "Tech Δ",
    "adj_commentary": "Comm Δ",
    "adj_target": "Target Δ",
    "adj_surprise": "Surprise Δ",
    "adj_coverage": "Coverage Δ",
    "adj_peg": "PEG Δ",
    "adj_growth": "CAGR Δ",
    "adj_pe_traj": "PE Trj Δ",
    "adj_exhaustion": "Exhaust Δ",
    "last_updated": "Updated",
}

display_df = df.rename(columns=column_map)

# Reorder columns: ticker, name, key score + growth metrics first
desired_cols = [
    "Sector", "Symbol", "Name",
    # Key headline metrics
    "Buy Score", "Analyst Est Growth %", "Target Upside %", "Rating",
    # 5 Pillars
    "Valuation", "Growth", "Profit", "Momentum", "Risk",
    # Key Adjustment Deltas
    "PEG Δ", "CAGR Δ", "PE Trj Δ", "Exhaust Δ", "Target Δ",
    # Legacy Scores
    "Tech Score", "Comm Score",
    # Core Financial Metrics
    "Price", "Trailing P/E", "Fwd PE", "PEG", "Beta",
    "52W High", "52W Low",
    "RSI(14)", "Exhaustion",
    "vs 50MA (%)", "vs 200MA (%)", "MACD", "BB Position", "ROC(10d)",
    "Vol 20d", "Vol 50d", "Updated"
]

# Preserve is_held for filtering/sorting even though we don't display it as a column
preserve_cols = [c for c in desired_cols if c in display_df.columns]
if "is_held" in display_df.columns and "is_held" not in preserve_cols:
    preserve_cols.append("is_held")
display_df = display_df[preserve_cols]

# Fill empty sectors
if "Sector" in display_df.columns:
    display_df["Sector"] = display_df["Sector"].fillna("Unknown").replace("", "Unknown")

# ---- SORT & FILTER CONTROLS ----
st.subheader("📊 Portfolio Overview")

# Holdings filter
show_only_holdings = st.checkbox("🎯 Show only my holdings", value=False)

sort_col1, sort_col2, filter_col = st.columns([2, 1, 2])
with sort_col1:
    sort_options = [c for c in display_df.columns if c != "Updated"]
    sort_by = st.selectbox("Sort by", sort_options, index=sort_options.index("Buy Score") if "Buy Score" in sort_options else 0)
with sort_col2:
    sort_asc = st.radio("Order", ["↓ Descending", "↑ Ascending"], index=0)
with filter_col:
    all_sectors = ["All"] + sorted(display_df["Sector"].dropna().unique().tolist()) if "Sector" in display_df.columns else ["All"]
    sector_filter = st.selectbox("Filter by Sector", all_sectors, index=0)

# Rating band filter
rating_filter = "All"
if "Rating" in display_df.columns:
    rating_col = st.columns([1, 1])[1] if 'rating_col' not in locals() else None
    all_ratings = ["All"] + ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]
    rating_filter = st.selectbox("Filter by Rating", all_ratings, index=0, key="rating_filter")

# Apply filters
filtered_df = display_df.copy()
if show_only_holdings and "is_held" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["is_held"] == 1].copy()
if sector_filter != "All" and "Sector" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["Sector"] == sector_filter].copy()
if rating_filter != "All" and "Rating" in filtered_df.columns:
    filtered_df = filtered_df[filtered_df["Rating"] == rating_filter].copy()

# Apply sort — if holdings exist, always sort held tickers first, then by selected column
ascending = sort_asc == "↑ Ascending"
if "is_held" in filtered_df.columns:
    filtered_df = filtered_df.sort_values(
        by=["is_held", sort_by],
        ascending=[False, ascending],
        na_position="last"
    )
else:
    if sort_by in filtered_df.columns:
        filtered_df = filtered_df.sort_values(sort_by, ascending=ascending, na_position="last")

# ---- COLOR HELPER ----
def _cell_style(val, col):
    """Return CSS style string for a cell value."""
    if col == "Buy Score":
        if val and val >= 80: return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val and val >= 65: return "background:#2e8b2e;color:#fff"
        elif val and val >= 45: return "background:#daa520;color:#000"
        elif val and val >= 30: return "background:#cd853f;color:#000"
        else: return "background:#b22222;color:#fff"
    elif col == "Rating":
        if val == "Strong Buy": return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val == "Buy": return "background:#2e8b2e;color:#fff"
        elif val == "Hold": return "background:#daa520;color:#000"
        elif val == "Sell": return "background:#cd853f;color:#000"
        elif val == "Strong Sell": return "background:#b22222;color:#fff"
    elif col in ("Valuation", "Growth", "Profit", "Momentum", "Risk"):
        if val and val >= 15: return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val and val >= 10: return "background:#2e8b2e;color:#fff"
        elif val and val >= 6: return "background:#daa520;color:#000"
        elif val and val >= 3: return "background:#cd853f;color:#000"
        else: return "background:#b22222;color:#fff"
    elif col in ("PEG Δ", "CAGR Δ", "PE Trj Δ", "Exhaust Δ", "Target Δ",
                  "Tech Δ", "Comm Δ", "Surprise Δ", "Coverage Δ"):
        # Adjustment deltas: positive = green (good for score), negative = red
        if val and val >= 3: return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val and val > 0: return "background:#2e8b2e;color:#fff"
        elif val == 0: return "background:#555;color:#fff"
        elif val and val > -3: return "background:#cd853f;color:#000"
        else: return "background:#b22222;color:#fff"
    elif col == "Tech Score":
        if val == 4: return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val == 3: return "background:#2e8b2e;color:#fff"
        elif val == 2: return "background:#daa520;color:#000"
        elif val == 1: return "background:#cd853f;color:#000"
        else: return "background:#b22222;color:#fff"
    elif col == "Comm Score":
        if val == 4: return "background:#1a5f1a;color:#fff;font-weight:bold"
        elif val == 3: return "background:#2e8b2e;color:#fff"
        elif val == 2: return "background:#daa520;color:#000"
        else: return "background:#b22222;color:#fff"
    elif col == "Exhaustion":
        if val == "Extreme": return "background:#8b0000;color:#fff;font-weight:bold"
        elif val == "High": return "background:#cd5c5c;color:#fff"
        elif val == "Building": return "background:#f0e68c;color:#000"
        else: return "background:#90ee90;color:#000"
    elif col == "RSI(14)":
        if val and val > 70: return "color:#ff6b6b;font-weight:bold"
        elif val and val < 30: return "color:#69db7c;font-weight:bold"
    elif col == "Analyst Est Growth %":
        if val and val > 20: return "color:#69db7c;font-weight:bold"
        elif val and val > 0: return "color:#69db7c"
        elif val and val < 0: return "color:#ff6b6b"
    elif col == "Target Upside %":
        if val and val > 30: return "color:#69db7c;font-weight:bold"
        elif val and val > 15: return "color:#69db7c"
        elif val and val < -10: return "color:#ff6b6b"
    elif col == "Beta":
        if val and val > 2.0: return "color:#ff6b6b;font-weight:bold"
        elif val and val > 1.5: return "color:#ffa94d"
        elif val and val < 0.8: return "color:#69db7c"
    elif col in ("vs 50MA (%)", "vs 200MA (%)", "ROC(10d)"):
        if val and val > 0: return "color:#69db7c"
        elif val and val < 0: return "color:#ff6b6b"
    elif col == "Sector":
        return "font-weight:600;white-space:nowrap"
    return ""

def _fmt(val, col):
    """Format a value for display."""
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    if col in ("Price", "52W High", "52W Low"):
        return f"${val:,.2f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Trailing P/E", "Fwd PE", "PEG", "Beta", "RSI(14)"):
        return f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Analyst Est Growth %", "Target Upside %", "vs 50MA (%)", "vs 200MA (%)", "ROC(10d)"):
        return f"{val:.1f}%" if isinstance(val, (int, float)) else str(val)
    if col in ("Buy Score", "Tech Score", "Comm Score"):
        return str(int(val)) if isinstance(val, (int, float)) else str(val)
    if col in ("Valuation", "Growth", "Profit", "Momentum", "Risk"):
        return f"{val:.0f}" if isinstance(val, (int, float)) else str(val)
    if col in ("PEG Δ", "CAGR Δ", "PE Trj Δ", "Exhaust Δ", "Target Δ",
                "Tech Δ", "Comm Δ", "Surprise Δ", "Coverage Δ"):
        return f"{val:+.0f}" if isinstance(val, (int, float)) else str(val)
    if col == "Vol 20d" or col == "Vol 50d":
        return f"{val:,.0f}" if isinstance(val, (int, float)) else str(val)
    return str(val)

# ---- CUSTOM HTML TABLE WITH STICKY COLUMNS ----
if len(filtered_df) > 0:
    cols = filtered_df.columns.tolist()
    
    # Build HTML table
    html = """
    <style>
    .dash-table-wrap {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        border-radius: 8px;
        border: 1px solid #333;
        max-height: 600px;
        overflow-y: auto;
    }
    .dash-table {
        border-collapse: separate;
        border-spacing: 0;
        font-size: 13px;
        width: max-content;
        min-width: 100%;
    }
    .dash-table thead th {
        position: sticky;
        top: 0;
        background: #0e1117;
        color: #fafafa;
        font-weight: 600;
        padding: 10px 12px;
        border-bottom: 2px solid #333;
        white-space: nowrap;
        z-index: 10;
        text-align: left;
    }
    .dash-table tbody td {
        padding: 8px 12px;
        border-bottom: 1px solid #262730;
        white-space: nowrap;
        background: #0e1117;
        color: #fafafa;
    }
    .dash-table tbody tr:hover td {
        background: #1a1d29;
    }
    /* Sticky first column (Sector) */
    .dash-table thead th:first-child,
    .dash-table tbody td:first-child {
        position: sticky;
        left: 0;
        min-width: 130px;
        max-width: 130px;
        z-index: 20;
        background: #0e1117;
        border-right: 2px solid #333;
    }
    .dash-table thead th:first-child {
        z-index: 30;
        background: #0e1117;
    }
    /* Sticky second column (Symbol) */
    .dash-table thead th:nth-child(2),
    .dash-table tbody td:nth-child(2) {
        position: sticky;
        left: 130px;
        min-width: 75px;
        max-width: 75px;
        z-index: 20;
        background: #0e1117;
        border-right: 2px solid #333;
    }
    .dash-table thead th:nth-child(2) {
        z-index: 30;
        background: #0e1117;
    }
    </style>
    <div class="dash-table-wrap">
    <table class="dash-table">
    <thead>
    <tr>
    """
    
    for col in cols:
        html += f"<th>{col}</th>"
    html += "</tr></thead><tbody>"
    
    for _, row in filtered_df.iterrows():
        html += "<tr>"
        held = row.get("is_held", 0) == 1
        for col in cols:
            val = row[col]
            style = _cell_style(val, col)
            text = _fmt(val, col)
            # Add 🎯 badge to Symbol column for held tickers
            if col == "Symbol" and held:
                text = f"🎯 {text}"
            html += f'<td style="{style}">{text}</td>'
        html += "</tr>"
    
    html += "</tbody></table></div>"
    
    st.markdown(html, unsafe_allow_html=True)
    st.caption(f"Showing {len(filtered_df)} of {len(display_df)} tickers")
else:
    st.info("No tickers match the selected filter.")

# ---- TOP PICKS SECTION ----
if "buy_score" in df.columns:
    st.subheader("🎯 Top Buy Picks")
    top_picks = df.nlargest(5, "buy_score")[["symbol", "name", "sector", "buy_score", "technical_score", "commentary_score", "exhaustion_level", "price"]]
    top_picks = top_picks.rename(columns={
        "symbol": "Symbol",
        "name": "Name",
        "sector": "Sector",
        "buy_score": "Buy Score",
        "technical_score": "Tech",
        "commentary_score": "Comm",
        "exhaustion_level": "Exhaustion",
        "price": "Price",
    })
    # Fill empty sectors
    if "Sector" in top_picks.columns:
        top_picks["Sector"] = top_picks["Sector"].fillna("Unknown").replace("", "Unknown")
    
    pick_cols = st.columns(min(5, len(top_picks)))
    for idx, (_, row) in enumerate(top_picks.iterrows()):
        with pick_cols[idx]:
            score = row["Buy Score"]
            color = "#1a5f1a" if score >= 80 else "#2e8b2e" if score >= 65 else "#daa520" if score >= 50 else "#cd853f"
            sector_label = row.get("Sector", "")
            sector_html = f'<p style="margin: 3px 0; font-size: 0.7em; opacity: 0.8;">{sector_label}</p>' if sector_label else ''
            st.markdown(f"""
            <div style="background-color: {color}; padding: 15px; border-radius: 10px; text-align: center; color: white;">
                <p style="margin: 0; font-size: 0.75em; opacity: 0.85; font-weight: 600;">{sector_label}</p>
                <h3 style="margin: 2px 0; font-size: 1.2em;">{row['Symbol']}</h3>
                <p style="margin: 5px 0; font-size: 0.85em; opacity: 0.9;">{row['Name'][:20]}</p>
                <h2 style="margin: 0; font-size: 2em;">{score}</h2>
                <p style="margin: 5px 0; font-size: 0.75em;">Tech {row['Tech']}/4 · Comm {row['Comm']}/4</p>
                <p style="margin: 0; font-size: 0.75em;">{row['Exhaustion']}</p>
            </div>
            """, unsafe_allow_html=True)

# ---- SECTOR SUMMARY ----
if "sector" in df.columns and "buy_score" in df.columns:
    st.markdown("---")
    st.subheader("🏛️ Sector Breakdown")
    
    # Compute sector stats
    sector_stats = df.groupby("sector").agg(
        count=("symbol", "count"),
        avg_buy=("buy_score", "mean"),
        top_symbol=("symbol", lambda x: x.iloc[0]),
        top_score=("buy_score", "max"),
    ).reset_index().sort_values("avg_buy", ascending=False)
    
    # Bar chart: sector avg Buy Score
    fig_sector = go.Figure()
    fig_sector.add_trace(go.Bar(
        x=sector_stats["sector"],
        y=sector_stats["avg_buy"],
        text=[f"{v:.1f}" for v in sector_stats["avg_buy"]],
        textposition="auto",
        marker_color=["#1a5f1a" if v >= 65 else "#2e8b2e" if v >= 50 else "#daa520" if v >= 35 else "#b22222" for v in sector_stats["avg_buy"]],
        name="Avg Buy Score",
    ))
    fig_sector.update_layout(
        title="Average Buy Score by Sector",
        xaxis_title="",
        yaxis_title="Avg Buy Score",
        template="plotly_dark",
        height=350,
        showlegend=False,
    )
    st.plotly_chart(fig_sector, use_container_width=True)
    
    # Sector cards
    sec_cols = st.columns(min(6, len(sector_stats)))
    for idx, (_, row) in enumerate(sector_stats.iterrows()):
        with sec_cols[idx % len(sec_cols)]:
            score = row["avg_buy"]
            color = "#1a5f1a" if score >= 65 else "#2e8b2e" if score >= 50 else "#daa520" if score >= 40 else "#cd853f"
            st.markdown(f"""
            <div style="background-color: {color}; padding: 12px; border-radius: 8px; text-align: center; color: white; margin-bottom: 8px;">
                <p style="margin: 0; font-size: 0.8em; opacity: 0.9; font-weight: 600;">{row['sector']}</p>
                <p style="margin: 4px 0; font-size: 1.4em; font-weight: bold;">{score:.1f}</p>
                <p style="margin: 0; font-size: 0.7em; opacity: 0.85;">{row['count']} tickers · Top: {row['top_symbol']} ({row['top_score']})</p>
            </div>
            """, unsafe_allow_html=True)

# Summary stats
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.metric("Total Tickers", len(df))
with col2:
    avg_buy = df["buy_score"].mean() if "buy_score" in df.columns else 0
    st.metric("Avg Buy Score", f"{avg_buy:.0f}/100")
with col3:
    strong_buy = df[df["rating_band"] == "Strong Buy"].shape[0] if "rating_band" in df.columns else 0
    st.metric("Strong Buys (80+)", strong_buy)
with col4:
    avg_prof = df["score_profitability"].mean() if "score_profitability" in df.columns else 0
    st.metric("Avg Profitability", f"{avg_prof:.1f}/20")
with col5:
    extreme = df[df["exhaustion_level"] == "Extreme"].shape[0] if "exhaustion_level" in df.columns else 0
    st.metric("Extreme Exhaustion", extreme)

# Charts section
st.markdown("---")
st.subheader("Detailed View")

selected_symbol = st.selectbox("Select ticker for charts", df["symbol"].tolist())

if selected_symbol:
    ticker_data = fetch_ticker_data(selected_symbol)
    if ticker_data:
        hist = ticker_data["history"]

        col_left, col_right = st.columns(2)

        with col_left:
            # Price chart
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=hist.index,
                y=hist["Close"],
                mode="lines",
                name="Close",
                line=dict(color="#00bcd4", width=2),
            ))
            fig.add_trace(go.Scatter(
                x=hist.index,
                y=hist["Close"].rolling(50).mean(),
                mode="lines",
                name="50 MA",
                line=dict(color="#ff9800", width=1.5),
            ))
            fig.add_trace(go.Scatter(
                x=hist.index,
                y=hist["Close"].rolling(200).mean(),
                mode="lines",
                name="200 MA",
                line=dict(color="#e91e63", width=1.5),
            ))
            fig.update_layout(
                title=f"{selected_symbol} Price",
                xaxis_title="Date",
                yaxis_title="Price ($)",
                template="plotly_dark",
                height=400,
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            # Volume chart
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                x=hist.index,
                y=hist["Volume"],
                name="Volume",
                marker_color="#00bcd4",
            ))
            fig2.add_trace(go.Scatter(
                x=hist.index,
                y=hist["Volume"].rolling(20).mean(),
                mode="lines",
                name="20d Avg",
                line=dict(color="#ff9800", width=2),
            ))
            fig2.update_layout(
                title=f"{selected_symbol} Volume",
                xaxis_title="Date",
                yaxis_title="Volume",
                template="plotly_dark",
                height=400,
            )
            st.plotly_chart(fig2, use_container_width=True)

        # Key metrics cards
        row = df[df["symbol"] == selected_symbol].iloc[0]

        # Company description
        desc = row.get('description', '')
        if desc:
            with st.expander("Company Description", expanded=False):
                st.markdown(desc)

        st.markdown("#### Key Metrics")
        mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
        with mcol1:
            st.metric("Price", f"${row.get('price', 'N/A')}")
        with mcol2:
            st.metric("Trailing P/E", f"{row.get('pe_trailing', 'N/A')}")
        with mcol3:
            st.metric("Fwd PE", f"{row.get('pe_forward', 'N/A')}")
        with mcol4:
            st.metric("PEG", f"{row.get('peg_ratio', 'N/A')}")
        with mcol5:
            cagr = row.get('projected_cagr')
            if cagr is None or (isinstance(cagr, float) and cagr != cagr):
                st.metric("Analyst Est Growth", "N/A")
            else:
                st.metric("Analyst Est Growth", f"{cagr}%")

        mcol6, mcol7, mcol8, mcol9, mcol10 = st.columns(5)
        with mcol6:
            upside = row.get('target_upside')
            if upside is None or (isinstance(upside, float) and upside != upside):
                st.metric("Target Upside", "N/A")
            else:
                st.metric("Target Upside", f"{upside}%")
        with mcol7:
            beta = row.get('beta')
            if beta is None or (isinstance(beta, float) and beta != beta):
                st.metric("Beta", "N/A")
            else:
                st.metric("Beta", f"{beta}")
        with mcol8:
            w52h = row.get('week_52_high')
            if w52h is None or (isinstance(w52h, float) and w52h != w52h):
                st.metric("52W High", "N/A")
            else:
                st.metric("52W High", f"${w52h}")
        with mcol9:
            w52l = row.get('week_52_low')
            if w52l is None or (isinstance(w52l, float) and w52l != w52l):
                st.metric("52W Low", "N/A")
            else:
                st.metric("52W Low", f"${w52l}")
        with mcol10:
            st.metric("RSI(14)", f"{row.get('rsi_14', 'N/A')}")

        st.markdown("#### Scores")
        
        # Big buy score at the top
        buy = row.get('buy_score')
        if buy is not None:
            bcol = st.columns([1, 2, 1])[1]
            with bcol:
                score_color = "#1a5f1a" if buy >= 80 else "#2e8b2e" if buy >= 65 else "#daa520" if buy >= 45 else "#cd853f" if buy >= 30 else "#b22222"
                st.markdown(f"""
                <div style="background-color: {score_color}; padding: 20px; border-radius: 15px; text-align: center; color: white; margin-bottom: 20px;">
                    <p style="margin: 0; font-size: 1em; opacity: 0.9;">Composite Buy Score</p>
                    <h1 style="margin: 0; font-size: 3em;">{buy}</h1>
                    <p style="margin: 0; font-size: 0.9em; opacity: 0.9;">out of 100</p>
                </div>
                """, unsafe_allow_html=True)
        
        # 5-Pillar breakdown
        st.markdown("**5-Pillar Breakdown** (Valuation · Growth · Profitability · Momentum · Risk)")
        pcols = st.columns(5)
        pillar_map = [
            ("Valuation", "score_valuation"),
            ("Growth", "score_growth"),
            ("Profitability", "score_profitability"),
            ("Momentum", "score_momentum"),
            ("Risk", "score_risk"),
        ]
        for pcol, (label, key) in zip(pcols, pillar_map):
            with pcol:
                pv = row.get(key, 0) or 0
                st.metric(label, f"{pv:.0f}/20")
                st.progress(pv / 20)

        # Adjustment Deltas
        st.markdown("**Reality-Check Adjustments**")
        adj_cols = st.columns(5)
        adj_map = [
            ("PEG Δ", "adj_peg"),
            ("CAGR Δ", "adj_growth"),
            ("PE Trj Δ", "adj_pe_traj"),
            ("Exhaust Δ", "adj_exhaustion"),
            ("Target Δ", "adj_target"),
        ]
        for acol, (label, key) in zip(adj_cols, adj_map):
            with acol:
                av = row.get(key, 0) or 0
                color = "#1a5f1a" if av > 0 else "#b22222" if av < 0 else "#555"
                st.metric(label, f"{av:+.0f}")

        adj_cols2 = st.columns(5)
        adj_map2 = [
            ("Tech Δ", "adj_technical"),
            ("Comm Δ", "adj_commentary"),
            ("Surprise Δ", "adj_surprise"),
            ("Coverage Δ", "adj_coverage"),
        ]
        for acol, (label, key) in zip(adj_cols2, adj_map2):
            with acol:
                av = row.get(key, 0) or 0
                st.metric(label, f"{av:+.0f}")

        st.markdown("---")
        st.markdown("**Legacy Scores** (for reference)")
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            st.metric("Buy Score", f"{buy}/100" if buy is not None else "N/A")
            st.progress(buy / 100 if buy is not None else 0)
        with scol2:
            st.metric("Technical Score", f"{row.get('technical_score', 'N/A')}/4")
            st.progress(row.get('technical_score', 0) / 4 if row.get('technical_score') else 0)
        with scol3:
            st.metric("Commentary Score", f"{row.get('commentary_score', 'N/A')}/4")
            st.progress(row.get('commentary_score', 0) / 4 if row.get('commentary_score') else 0)

# Export
st.markdown("---")
if st.button("📥 Export to CSV"):
    csv = display_df.to_csv(index=False)
    st.download_button(
        label="Download CSV",
        data=csv,
        file_name=f"stock_dashboard_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )
