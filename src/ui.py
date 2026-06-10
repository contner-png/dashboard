"""Shared UI helpers: theme CSS, score colors, value formatting."""

import pandas as pd

# ---------------------------------------------------------------------------
# Design tokens — single consistent score palette across the whole app
# ---------------------------------------------------------------------------

TIERS = {
    "strong_buy": {"fg": "#34d399", "bg": "rgba(16, 185, 129, 0.16)", "border": "rgba(52, 211, 153, 0.45)"},
    "buy":        {"fg": "#a3e635", "bg": "rgba(132, 204, 22, 0.14)", "border": "rgba(163, 230, 53, 0.40)"},
    "hold":       {"fg": "#fbbf24", "bg": "rgba(245, 158, 11, 0.14)", "border": "rgba(251, 191, 36, 0.40)"},
    "sell":       {"fg": "#fb923c", "bg": "rgba(249, 115, 22, 0.14)", "border": "rgba(251, 146, 60, 0.40)"},
    "strong_sell": {"fg": "#f87171", "bg": "rgba(239, 68, 68, 0.15)", "border": "rgba(248, 113, 113, 0.42)"},
    "neutral":    {"fg": "#94a3b8", "bg": "rgba(148, 163, 184, 0.10)", "border": "rgba(148, 163, 184, 0.25)"},
}

RATING_TIER = {
    "Strong Buy": "strong_buy",
    "Buy": "buy",
    "Hold": "hold",
    "Sell": "sell",
    "Strong Sell": "strong_sell",
}

RATING_ORDER = ["Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"]

GOOD = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"


def score_tier(score) -> str:
    if score is None or (isinstance(score, float) and score != score):
        return "neutral"
    if score >= 80:
        return "strong_buy"
    if score >= 65:
        return "buy"
    if score >= 45:
        return "hold"
    if score >= 30:
        return "sell"
    return "strong_sell"


def pillar_tier(value) -> str:
    """Tier for a 0-20 pillar score."""
    if value is None or (isinstance(value, float) and value != value):
        return "neutral"
    return score_tier(value * 5)


def tier_css(tier: str, bold: bool = False) -> str:
    t = TIERS.get(tier, TIERS["neutral"])
    weight = "font-weight:700;" if bold else ""
    return f"background:{t['bg']};color:{t['fg']};{weight}"


def badge(text: str, tier: str = "neutral") -> str:
    t = TIERS.get(tier, TIERS["neutral"])
    return (
        f"<span style=\"display:inline-block;padding:2px 10px;border-radius:999px;"
        f"background:{t['bg']};color:{t['fg']};border:1px solid {t['border']};"
        f"font-size:0.74rem;font-weight:600;letter-spacing:0.02em;\">{text}</span>"
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_large_number(val):
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    try:
        val = float(val)
    except (TypeError, ValueError):
        return str(val)
    abs_val = abs(val)
    if abs_val >= 1_000_000_000_000:
        return f"${val / 1_000_000_000_000:.2f}T"
    if abs_val >= 1_000_000_000:
        return f"${val / 1_000_000_000:.1f}B"
    if abs_val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if abs_val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:,.0f}"


def fmt(val, col):
    """Format a value for display based on its display-column name."""
    if val is None or (isinstance(val, float) and val != val):
        return "—"
    if col in ("Market Cap", "FCF"):
        return fmt_large_number(val)
    if col in ("Price", "52W High", "52W Low", "DCF Value"):
        return f"${val:,.2f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Trailing P/E", "Fwd P/E", "PEG", "Beta", "RSI(14)", "Current Ratio", "Rec Mean"):
        return f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Est Growth %", "Target Upside %", "vs 50MA %", "vs 200MA %", "ROC 10d", "Coverage %",
               "DCF Upside %", "Max DD %", "ROE %", "Gross M %", "Op M %", "Net M %",
               "Rev Growth %", "EPS Growth %"):
        return f"{val:.1f}%" if isinstance(val, (int, float)) else str(val)
    if col in ("Buy Score", "Analysts"):
        return str(int(val)) if isinstance(val, (int, float)) else str(val)
    if col == "Sector %ile":
        return f"{val:.0f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Valuation", "Growth", "Profit", "Momentum", "Risk", "D/E"):
        return f"{val:.0f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ", "Intrinsic Δ"):
        return f"{val:+.0f}" if isinstance(val, (int, float)) else str(val)
    if col in ("Vol 20d", "Vol 50d"):
        return f"{val:,.0f}" if isinstance(val, (int, float)) else str(val)
    return str(val)


def time_ago(ts) -> str:
    """Human-readable age for a UTC timestamp string."""
    parsed = pd.to_datetime(ts, errors="coerce", utc=True)
    if parsed is pd.NaT or parsed is None:
        return "never"
    delta = pd.Timestamp.now(tz="UTC") - parsed
    seconds = delta.total_seconds()
    if seconds < 0:
        seconds = 0
    if seconds < 90:
        return "just now"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f}m ago"
    hours = minutes / 60
    if hours < 36:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


# ---------------------------------------------------------------------------
# Table cell styling (display-column names)
# ---------------------------------------------------------------------------

def cell_style(val, col) -> str:
    is_num = isinstance(val, (int, float)) and not (isinstance(val, float) and val != val)

    if col == "Buy Score" and is_num:
        return tier_css(score_tier(val), bold=True)
    if col == "Rating":
        return tier_css(RATING_TIER.get(val, "neutral"), bold=True)
    if col in ("Valuation", "Growth", "Profit", "Momentum", "Risk") and is_num:
        return tier_css(pillar_tier(val))
    if col in ("Value Δ", "Analyst Δ", "Trajectory Δ", "Exhaust Δ", "Intrinsic Δ") and is_num:
        if val > 0:
            return f"color:{GOOD};"
        if val < 0:
            return f"color:{BAD};"
        return "color:#64748b;"
    if col == "Sector %ile" and is_num:
        if val >= 80:
            return f"color:{GOOD};font-weight:600;"
        if val >= 60:
            return f"color:{GOOD};"
        if val <= 20:
            return f"color:{BAD};"
        return "color:#94a3b8;"
    if col == "DCF Upside %" and is_num:
        if val > 20:
            return f"color:{GOOD};font-weight:600;"
        if val < -20:
            return f"color:{BAD};font-weight:600;"
        return "color:#94a3b8;"
    if col == "DCF Verdict":
        styles = {
            "Undervalued": tier_css("strong_buy", bold=True),
            "Fairly Valued": tier_css("hold"),
            "Overvalued": tier_css("strong_sell"),
        }
        return styles.get(val, "")
    if col == "Max DD %" and is_num:
        if val < -50:
            return f"color:{BAD};font-weight:600;"
        if val < -30:
            return f"color:{WARN};"
        return f"color:{GOOD};"
    if col in ("ROE %", "Gross M %", "Op M %", "Net M %", "Rev Growth %", "EPS Growth %") and is_num:
        if val > 0:
            return f"color:{GOOD};"
        if val < 0:
            return f"color:{BAD};"
    if col == "D/E" and is_num:
        if val > 150:
            return f"color:{BAD};"
        if val > 80:
            return f"color:{WARN};"
    if col == "Exhaustion":
        styles = {
            "Extreme": tier_css("strong_sell", bold=True),
            "High": tier_css("sell"),
            "Building": tier_css("hold"),
            "None": tier_css("strong_buy"),
        }
        return styles.get(val, "")
    if col == "RSI(14)" and is_num:
        if val > 70:
            return f"color:{BAD};font-weight:600;"
        if val < 30:
            return f"color:{GOOD};font-weight:600;"
    if col in ("Est Growth %", "Target Upside %", "vs 50MA %", "vs 200MA %", "ROC 10d") and is_num:
        if val > 0:
            return f"color:{GOOD};"
        if val < 0:
            return f"color:{BAD};"
    if col == "Coverage %" and is_num:
        if val < 60:
            return f"color:{BAD};"
        if val < 80:
            return f"color:{WARN};"
        return f"color:{GOOD};"
    if col == "Beta" and is_num:
        if val > 2.0:
            return f"color:{BAD};font-weight:600;"
        if val > 1.5:
            return f"color:{WARN};"
    if col == "Sector":
        return "font-weight:600;white-space:nowrap;color:#a5b4fc;"
    if col == "Symbol":
        return "font-weight:700;"
    return ""


# ---------------------------------------------------------------------------
# Global CSS
# ---------------------------------------------------------------------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Space+Grotesk:wght@500;600;700&display=swap');

:root {
    --bg: #0a0e17;
    --surface: #121826;
    --surface-2: #161e30;
    --border: rgba(148, 163, 184, 0.14);
    --text: #e6eaf2;
    --muted: #8b95a8;
    --accent: #818cf8;
    --accent-2: #22d3ee;
}

html, body, .stApp {
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', sans-serif;
}

.stApp {
    background:
        radial-gradient(900px 420px at 85% -10%, rgba(99, 102, 241, 0.13), transparent 60%),
        radial-gradient(700px 380px at 0% 0%, rgba(34, 211, 238, 0.07), transparent 55%),
        var(--bg);
}

h1, h2, h3, h4 {
    font-family: 'Space Grotesk', sans-serif;
    letter-spacing: -0.02em;
    color: var(--text);
}

.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1400px; }

/* Streamlit's built-in top toolbar renders as a white strip on the light
   base theme — blend it into the dark background instead. */
header[data-testid="stHeader"] {
    background: transparent;
}
header[data-testid="stHeader"] button,
header[data-testid="stHeader"] svg {
    color: var(--muted);
    fill: var(--muted);
}
div[data-testid="stDecoration"] { display: none; }

section[data-testid="stSidebar"] {
    background: #0d1220;
    border-right: 1px solid var(--border);
}

/* App header — compact single strip, stays out of the way */
.app-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding: 10px 18px;
    border-radius: 12px;
    background: linear-gradient(135deg, rgba(99, 102, 241, 0.08), rgba(18, 24, 38, 0.55) 45%);
    border: 1px solid var(--border);
    margin-bottom: 10px;
}
.app-header h1 { margin: 0; font-size: 1.2rem; display: inline; }
.app-header .sub { color: var(--muted); font-size: 0.78rem; margin-top: 1px; }
.app-header .meta { text-align: right; color: var(--muted); font-size: 0.78rem; line-height: 1.45; white-space: nowrap; }

/* KPI cards */
.kpi {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 14px 16px;
    height: 100%;
}
.kpi .label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--muted);
}
.kpi .value {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.5rem;
    font-weight: 700;
    margin-top: 4px;
}
.kpi .sub { font-size: 0.74rem; color: var(--muted); margin-top: 4px; }

/* Section titles */
.section-title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.05rem;
    font-weight: 700;
    margin: 18px 0 4px;
}
.section-sub { color: var(--muted); font-size: 0.82rem; margin-bottom: 10px; }

/* Buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
    border-radius: 10px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    color: var(--text);
    font-weight: 600;
    transition: border-color 0.15s ease, background 0.15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
    border-color: var(--accent);
    color: var(--text);
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
    background: linear-gradient(135deg, #6366f1, #4f46e5);
    border: none;
    color: #fff;
}

/* Inputs */
div[data-baseweb="input"] input, div[data-baseweb="textarea"] textarea {
    background: var(--surface) !important;
    color: var(--text) !important;
}
div[data-baseweb="select"] > div {
    background: var(--surface) !important;
    border-color: var(--border) !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    border-bottom: 1px solid var(--border);
}
.stTabs [data-baseweb="tab"] {
    font-weight: 600;
    color: var(--muted);
    padding: 8px 14px;
}
.stTabs [aria-selected="true"] { color: var(--text); }

/* Metric widgets */
div[data-testid="stMetric"] {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px 14px;
}

/* Ticker cards */
.tcard {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 14px;
}
.tcard .head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
.tcard .sym { font-family: 'Space Grotesk', sans-serif; font-size: 1.06rem; font-weight: 700; }
.tcard .name { font-size: 0.76rem; color: var(--muted); margin-top: 1px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tcard .score {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.2rem;
    font-weight: 700;
    padding: 4px 12px;
    border-radius: 10px;
    text-align: center;
}
.tcard .meta { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.76rem; color: var(--muted); margin: 10px 0; }
.tcard .meta b { color: var(--text); font-weight: 600; }

.pillar-row { display: flex; justify-content: space-between; font-size: 0.7rem; color: var(--muted); margin-bottom: 3px; }
.pillar-track { background: rgba(148, 163, 184, 0.14); border-radius: 4px; height: 5px; overflow: hidden; margin-bottom: 7px; }
.pillar-fill { height: 5px; border-radius: 4px; }

/* Data table */
.dash-table-wrap {
    overflow: auto;
    border-radius: 14px;
    border: 1px solid var(--border);
    max-height: 640px;
    background: var(--surface);
}
.dash-table {
    border-collapse: separate;
    border-spacing: 0;
    font-size: 12.8px;
    width: max-content;
    min-width: 100%;
}
.dash-table thead th {
    position: sticky;
    top: 0;
    background: #1a2235;
    color: var(--text);
    font-weight: 600;
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    z-index: 10;
    text-align: left;
}
.dash-table tbody td {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(148, 163, 184, 0.08);
    white-space: nowrap;
    color: var(--text);
}
.dash-table tbody tr:hover td { background: rgba(129, 140, 248, 0.07); }
.dash-table thead th:first-child,
.dash-table tbody td:first-child {
    position: sticky;
    left: 0;
    min-width: 84px;
    z-index: 20;
    background: var(--surface);
    border-right: 1px solid var(--border);
}
.dash-table thead th:first-child { z-index: 30; background: #1a2235; }

/* Top pick cards */
.pick {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 14px;
    text-align: center;
}
.pick .sym { font-family: 'Space Grotesk', sans-serif; font-weight: 700; font-size: 1.05rem; }
.pick .name { font-size: 0.72rem; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pick .score { font-family: 'Space Grotesk', sans-serif; font-size: 2rem; font-weight: 700; margin: 6px 0 2px; }
.pick .sector { font-size: 0.7rem; color: var(--muted); margin-top: 6px; }

hr { border-color: var(--border); }
</style>
"""


def inject_css(st):
    st.markdown(CSS, unsafe_allow_html=True)
