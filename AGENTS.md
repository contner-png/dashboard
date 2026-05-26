# Repository Notes

- Buy score is coverage-aware: pillar functions return earned/possible points and `calculate_buy_score_v2` normalizes by total possible points. Coverage percent is stored as `data_coverage` (0-100).
- `score_mode` is "Technical" for non-equity tickers (ETF/MUTUALFUND/INDEX/etc.) or coverage < 60; otherwise "Equity".
- `metrics` table now includes `data_coverage` and `score_mode` columns, populated during sync.
- The UI exposes `Score Mode` and `Data Coverage %` columns, filters, and card metadata.
- App auto-syncs tracked tickers on first load via `sync_all()`.
