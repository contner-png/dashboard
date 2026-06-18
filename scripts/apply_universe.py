"""
Sync the tracked ticker set to the SECTOR_GROUPS taxonomy in src/fetcher.py.

Adds every taxonomy ticker (with its custom sector), removes anything not in
the taxonomy, and regenerates data/watchlist.txt. No network — metrics for new
tickers populate on the next sync. Run after editing SECTOR_GROUPS:

    python scripts/apply_universe.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import init_db, add_ticker, remove_ticker, get_tickers  # noqa: E402
from src.fetcher import SECTOR_GROUPS, SECTOR_MAP  # noqa: E402

WATCHLIST_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "watchlist.txt")


def write_watchlist():
    lines = [
        "# Tracked universe — the authoritative ticker list (one per line).",
        "# Generated from SECTOR_GROUPS in src/fetcher.py by scripts/apply_universe.py.",
        "# The nightly sync treats this as the universe: tickers not listed here are removed.",
        "",
    ]
    for sector, syms in SECTOR_GROUPS.items():
        lines.append(f"# {sector} ({len(syms)})")
        lines.extend(syms)
        lines.append("")
    with open(WATCHLIST_PATH, "w") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


def main() -> int:
    init_db()
    wanted = set(SECTOR_MAP)

    for sym, sector in SECTOR_MAP.items():
        add_ticker(sym, sector=sector)

    removed = [s for s in get_tickers() if s not in wanted]
    for sym in removed:
        remove_ticker(sym)

    write_watchlist()

    tracked = get_tickers()
    print(f"Universe applied: {len(tracked)} tickers ({len(wanted)} wanted), removed {len(removed)}")
    assert set(tracked) == wanted, "ticker set does not match taxonomy"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
