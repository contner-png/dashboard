import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

from src.database import init_db, add_ticker, remove_ticker, get_tickers, get_all_metrics
from src.sync import sync_ticker, sync_all
from src.fetcher import fetch_ticker_data

st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")

# Initialize database
init_db()

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
    "pe_trailing": "PE (TTM)",
    "pe_forward": "Fwd PE",
    "peg_ratio": "PEG",
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
    "last_updated": "Updated",
}

display_df = df.rename(columns=column_map)

# Reorder columns
desired_cols = [
    "Symbol", "Name", "Price", "PE (TTM)", "Fwd PE", "PEG",
    "RSI(14)", "Exhaustion", "Tech Score", "Comm Score",
    "vs 50MA (%)", "vs 200MA (%)", "MACD", "BB Position", "ROC(10d)",
    "Vol 20d", "Vol 50d", "Updated"
]

display_cols = [c for c in desired_cols if c in display_df.columns]
display_df = display_df[display_cols]

# Style function
def style_df(df):
    def _style(val, col):
        if col == "Tech Score":
            if val == 4:
                return "background-color: #1a5f1a; color: white; font-weight: bold"
            elif val == 3:
                return "background-color: #2e8b2e; color: white"
            elif val == 2:
                return "background-color: #daa520; color: black"
            elif val == 1:
                return "background-color: #cd853f; color: black"
            else:
                return "background-color: #b22222; color: white"
        elif col == "Comm Score":
            if val == 4:
                return "background-color: #1a5f1a; color: white; font-weight: bold"
            elif val == 3:
                return "background-color: #2e8b2e; color: white"
            elif val == 2:
                return "background-color: #daa520; color: black"
            else:
                return "background-color: #b22222; color: white"
        elif col == "Exhaustion":
            if val == "Extreme":
                return "background-color: #8b0000; color: white; font-weight: bold"
            elif val == "High":
                return "background-color: #cd5c5c; color: white"
            elif val == "Building":
                return "background-color: #f0e68c; color: black"
            else:
                return "background-color: #90ee90; color: black"
        elif col == "RSI(14)":
            if val and val > 70:
                return "color: #ff4444; font-weight: bold"
            elif val and val < 30:
                return "color: #44ff44; font-weight: bold"
        elif col in ("vs 50MA (%)", "vs 200MA (%)", "ROC(10d)"):
            if val and val > 0:
                return "color: #44ff44"
            elif val and val < 0:
                return "color: #ff4444"
        return ""

    styled = df.copy()
    for col in styled.columns:
        styled[col] = styled[col].apply(lambda x, c=col: _style(x, c))
    return styled

st.subheader("Portfolio Overview")
st.dataframe(
    display_df.style.apply(style_df, axis=None),
    use_container_width=True,
    hide_index=True,
    height=min(50 + len(display_df) * 35, 600),
)

# Summary stats
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Tickers", len(df))
with col2:
    avg_tech = df["technical_score"].mean() if "technical_score" in df.columns else 0
    st.metric("Avg Tech Score", f"{avg_tech:.1f}/4")
with col3:
    avg_comm = df["commentary_score"].mean() if "commentary_score" in df.columns else 0
    st.metric("Avg Comm Score", f"{avg_comm:.1f}/4")
with col4:
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
        st.markdown("#### Key Metrics")
        mcol1, mcol2, mcol3, mcol4, mcol5, mcol6 = st.columns(6)
        with mcol1:
            st.metric("Price", f"${row.get('price', 'N/A')}")
        with mcol2:
            st.metric("PE (TTM)", f"{row.get('pe_trailing', 'N/A')}")
        with mcol3:
            st.metric("Fwd PE", f"{row.get('pe_forward', 'N/A')}")
        with mcol4:
            st.metric("PEG", f"{row.get('peg_ratio', 'N/A')}")
        with mcol5:
            st.metric("RSI(14)", f"{row.get('rsi_14', 'N/A')}")
        with mcol6:
            st.metric("Exhaustion", row.get('exhaustion_level', 'N/A'))

        st.markdown("#### Scores")
        scol1, scol2 = st.columns(2)
        with scol1:
            st.metric("Technical Score", f"{row.get('technical_score', 'N/A')}/4")
            st.progress(row.get('technical_score', 0) / 4 if row.get('technical_score') else 0)
        with scol2:
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
