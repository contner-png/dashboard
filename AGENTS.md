# Repository Notes

## Architecture
- `app.py` — Streamlit UI only (header, sidebar management, Overview / Screener / Ticker Detail tabs). Reads come from SQLite via `load_metrics()` (`st.cache_data`, 2 min TTL); call `invalidate_data()` after any DB mutation.
- `src/database.py` — SQLite layer. `METRIC_COLUMNS` is the single source of truth for the metrics schema; `init_db()` auto-adds any missing column, so never hand-write ALTER TABLE migrations. DB path resolves from `STOCKS_DB_PATH` / `STOCKS_DB_DIR` / `RENDER_DISK_PATH`, falling back to `data/stocks.db`. WAL mode is enabled.
- `src/fetcher.py` — yfinance access (free data source — keep it that way). `fetch_ticker_data` returns info + 6mo history + statement-derived growth fields; `fetch_history` is the lightweight chart fetch.
- `src/scoring.py` — Buy Score v3 (see below).
- `src/research.py` — Tier-2 Research Pack: deterministic 2-stage DCF, CAGR scenario bands, max drawdown, entry/stop plans, position sizing, and the CIO memo prompt builder. No LLM, no paid data.
- `src/sync.py` — `add_and_sync` persists the ticker BEFORE fetching (a failed fetch never loses a ticker); `sync_many` runs syncs in a thread pool with a progress callback. There is no automatic sync on app launch — the UI offers "Sync stale" / "Sync all". History is fetched at 1y (needed for the 200-day MA and 1y max drawdown).
- `src/ui.py` — theme CSS, tier color palette, formatting helpers, HTML table cell styling.

## Buy Score v3 (coverage-aware)
- Five pillars scored 0-20 from available data: Valuation, Growth, Profitability, Momentum, Risk. Pillar functions return `(earned, possible)`.
- Pillars blend with fixed weights (V .22 / G .24 / P .20 / M .22 / R .12); pillars with no data are dropped and weights renormalize.
- Five conviction adjustments, total capped ±12: value premium (PEG) → `adj_peg`, analyst conviction (target upside) → `adj_target`, earnings trajectory (fwd vs trailing PE) → `adj_pe_traj`, trend exhaustion → `adj_exhaustion`, intrinsic value (DCF upside, only when FCF > 0) → `adj_dcf`. The old v2 adjustment columns (`adj_technical`, `adj_commentary`, `adj_surprise`, `adj_coverage`, `adj_growth`) are written as 0.
- Deliberately excluded from the score: correlation-to-holdings (portfolio construction, not stock quality), max drawdown (overlaps beta/52w-range/exhaustion), entry zones and sizing (execution decisions). These live in the Research Pack tab only.
- `data_coverage` (0-100) = weighted share of the model that had data. `score_mode` is "Technical" (momentum + risk only, no adjustments) for non-equities or coverage < 60, else "Equity".
- Rating bands: 80+ Strong Buy, 65+ Buy, 45+ Hold, 30+ Sell, else Strong Sell.
