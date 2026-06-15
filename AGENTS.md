# Repository Notes

## Deployment & data persistence
- Hosting is assumed ephemeral (Streamlit Community Cloud): the SQLite file resets to the committed copy on every restart, so in-app syncs/ticker-adds do not survive restarts.
- `.github/workflows/nightly-sync.yml` runs `scripts/nightly_sync.py` on weekday evenings: merges `data/watchlist.txt` into tickers, syncs everything, WAL-checkpoints, and commits the refreshed `data/stocks.db`. The committed DB is the durable source of truth.
- To add a ticker permanently, add a line to `data/watchlist.txt` (UI adds are session-scoped on ephemeral hosts).
- Holdings persist the same way: `data/holdings.txt` is the durable source. App startup seeds the holdings table from it only when empty (`seed_holdings_from_file()`); the nightly sync applies it authoritatively (`replace=True`); the Save button also writes the file (durable only where the FS persists). An empty file never wipes existing holdings.

## Architecture
- `app.py` — Streamlit UI only (header, sidebar management, Overview / Screener / Ticker Detail tabs). Reads come from SQLite via `load_metrics()` (`st.cache_data`, 2 min TTL); call `invalidate_data()` after any DB mutation.
- `src/database.py` — SQLite layer. `METRIC_COLUMNS` is the single source of truth for the metrics schema; `init_db()` auto-adds any missing column, so never hand-write ALTER TABLE migrations. DB path resolves from `STOCKS_DB_PATH` / `STOCKS_DB_DIR` / `RENDER_DISK_PATH`, falling back to `data/stocks.db`. WAL mode is enabled.
- `src/fetcher.py` — yfinance access (free data source — keep it that way). `fetch_ticker_data` returns info + 1y history + statement-derived growth fields; `fetch_history` is the lightweight chart fetch; `fetch_news` normalizes both yfinance news shapes and never raises.
- Price cache: sync writes daily close/volume into the `prices` table (`store_prices`/`get_prices`). The app's `load_history` serves charts and correlation checks from this cache when it's fresh (<7 days) and covers the requested period, falling back to network, then to stale cache. This also accumulates history for future backtesting.
- `Sector %ile` is computed at render time in `app.py` (percentile of buy score within sector, blanked for sectors with <3 tickers) — it is not a DB column.
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
- Within-pillar evidence floor (`_normalize_pillar_floored`): after normalizing a pillar to 0-20, the score is shrunk toward neutral (10) when the pillar rested on thin within-pillar data (possible < 50% of the ~20 nominal), so one lone signal can't mint a perfect 20 and scores stay comparable across peers. Applied to the five top-level pillars only (profitability's internal efficiency sub-score still uses plain `_normalize_pillar`).
- Analyst conviction in the growth pillar requires `recommendationMean > 0` (Yahoo returns 0 as a "no rating" sentinel) AND `numberOfAnalystOpinions >= 2` (single-analyst means are too noisy).
- Rating bands: 80+ Strong Buy, 65+ Buy, 45+ Hold, 30+ Sell, else Strong Sell.
