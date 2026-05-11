import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "stocks.db")
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
            pe_trailing REAL,
            pe_forward REAL,
            peg_ratio REAL,
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
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (symbol) REFERENCES tickers(symbol)
        )
    """)

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
        SELECT t.symbol, t.name, t.sector, m.*
        FROM tickers t
        LEFT JOIN metrics m ON t.symbol = m.symbol
        ORDER BY t.symbol
        """
    )
    rows = cursor.fetchall()
    cols = [desc[0] for desc in cursor.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]
