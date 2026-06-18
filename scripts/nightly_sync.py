"""
Nightly data refresh, run by .github/workflows/nightly-sync.yml.

Hosting with ephemeral filesystems (e.g. Streamlit Community Cloud) resets
the SQLite file to the committed copy on every restart — so this job keeps
the committed copy fresh: sync everything, checkpoint WAL into the main db
file, and let the workflow commit the result.

Also merges data/watchlist.txt (one symbol per line, '#' comments allowed)
into the tracked tickers, so adding a line to that file on GitHub is a
permanent way to add a ticker.

Run locally the same way:  python scripts/nightly_sync.py
"""

import os
import sys
import sqlite3
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import DB_PATH, init_db, add_ticker, remove_ticker, get_tickers, seed_holdings_from_file  # noqa: E402
from src.sync import sync_many  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("nightly_sync")

WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watchlist.txt")


def load_watchlist() -> list:
    if not os.path.exists(WATCHLIST_PATH):
        return []
    symbols = []
    with open(WATCHLIST_PATH) as fh:
        for line in fh:
            sym = line.split("#", 1)[0].strip().upper()
            if sym:
                symbols.append(sym)
    return symbols


def main() -> int:
    init_db()

    # The watchlist is the authoritative universe: add everything in it and,
    # when it's non-empty, remove anything tracked that isn't (a custom sector
    # comes from src/fetcher.py SECTOR_MAP at sync time). An empty file is a
    # no-op so it can never wipe the universe.
    watchlist = load_watchlist()
    for sym in watchlist:
        add_ticker(sym)
    if watchlist:
        wl = {s.upper() for s in watchlist}
        for sym in get_tickers():
            if sym not in wl:
                remove_ticker(sym)

    # holdings.txt is authoritative in the committed DB
    seed_holdings_from_file(replace=True)

    tickers = get_tickers()
    logger.info(f"Syncing {len(tickers)} tickers…")
    results = sync_many(tickers)
    n_ok, n_fail = len(results["synced"]), len(results["failed"])
    logger.info(f"Synced {n_ok} OK, {n_fail} failed")
    if results["failed"]:
        logger.info("Failed: " + ", ".join(results["failed"]))

    # Fold the WAL journal into stocks.db itself so the committed file is complete.
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()

    print(f"::notice::Nightly sync: {n_ok} synced, {n_fail} failed")
    # Only hard-fail when nothing synced at all (likely a Yahoo outage) —
    # partial failures (delisted symbols etc.) shouldn't block the data commit.
    return 0 if n_ok > 0 or not tickers else 1


if __name__ == "__main__":
    raise SystemExit(main())
