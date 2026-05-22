import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stocks.db")
ENV_DB_PATH = os.environ.get("STOCKS_DB_PATH")
ENV_DB_DIR = os.environ.get("STOCKS_DB_DIR") or os.environ.get("RENDER_DISK_PATH")
if ENV_DB_PATH:
    DB_PATH = ENV_DB_PATH
elif ENV_DB_DIR:
    DB_PATH = os.path.join(ENV_DB_DIR, "stocks.db")
else:
    DB_PATH = DEFAULT_DB_PATH

DB_PATH = os.path.expanduser(DB_PATH)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


def get_conn() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickers (
            symbol TEXT PRIMARY KEY,
            name TEXT,
            sector TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS metrics (
            symbol TEXT PRIMARY KEY,
            price REAL,
            market_cap REAL,
            pe_trailing REAL,
            pe_forward REAL,
            peg_ratio REAL,
            projected_cagr REAL,
            beta REAL,
            target_mean REAL,
            target_high REAL,
            target_low REAL,
            target_upside REAL,
            week_52_high REAL,
            week_52_low REAL,
            rsi_14 REAL,
            volume_20d_avg REAL,
            volume_50d_avg REAL,
            price_vs_50ma REAL,
            price_vs_200ma REAL,
            macd_signal TEXT,
            bb_position TEXT,
            roc_10d REAL,
            exhaustion_level TEXT,
            technical_score INTEGER,
            commentary_score INTEGER,
            buy_score INTEGER,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES tickers(symbol)
        )
    """)


    cursor.execute("PRAGMA table_info(metrics)")
    metric_cols = {row[1] for row in cursor.fetchall()}
    if "market_cap" not in metric_cols:
        cursor.execute("ALTER TABLE metrics ADD COLUMN market_cap REAL")

    conn.commit()
    conn.close()


def add_ticker(symbol: str, name: str = "", sector: str = ""):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO tickers (symbol, name, sector) VALUES (?, ?, ?)",
        (symbol.upper(), name, sector),
    )
    conn.commit()
    conn.close()


def remove_ticker(symbol: str):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tickers WHERE symbol = ?", (symbol.upper(),))
    cursor.execute("DELETE FROM metrics WHERE symbol = ?", (symbol.upper(),))
    conn.commit()
    conn.close()


def get_tickers() -> List[str]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol FROM tickers ORDER BY symbol")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_ticker_info(symbol: str) -> Optional[Dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t.symbol, t.name, t.sector, m.*
        FROM tickers t
        LEFT JOIN metrics m ON t.symbol = m.symbol
        WHERE t.symbol = ?
        """,
        (symbol.upper(),),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    cols = [desc[0] for desc in cursor.description]
    return dict(zip(cols, row))


def upsert_metrics(symbol: str, metrics: Dict):
    conn = get_conn()
    cursor = conn.cursor()

    fields = list(metrics.keys())
    values = list(metrics.values())

    placeholders = ", ".join(["?"] * len(fields))
    updates = ", ".join([f"{f} = excluded.{f}" for f in fields])

    sql = f"""
        INSERT INTO metrics (symbol, {', '.join(fields)})
        VALUES (?, {placeholders})
        ON CONFLICT(symbol) DO UPDATE SET
            {updates},
            last_updated = CURRENT_TIMESTAMP
    """

    cursor.execute(sql, (symbol.upper(), *values))
    conn.commit()
    conn.close()


def get_all_metrics() -> List[Dict]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT t.symbol, t.name, t.sector, m.*, COALESCE(h.is_held, 0) as is_held
        FROM tickers t
        LEFT JOIN metrics m ON t.symbol = m.symbol
        LEFT JOIN holdings h ON t.symbol = h.symbol
        ORDER BY t.symbol
        """
    )
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]


def init_holdings():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            symbol TEXT PRIMARY KEY,
            is_held INTEGER DEFAULT 0,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES tickers(symbol)
        )
    """)
    conn.commit()
    conn.close()


def toggle_holding(symbol: str, is_held: bool):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO holdings (symbol, is_held) VALUES (?, ?)",
        (symbol.upper(), 1 if is_held else 0),
    )
    conn.commit()
    conn.close()


def get_holdings() -> List[str]:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT symbol FROM holdings WHERE is_held = 1 ORDER BY symbol")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def is_held(symbol: str) -> bool:
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_held FROM holdings WHERE symbol = ?", (symbol.upper(),)
    )
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0])
