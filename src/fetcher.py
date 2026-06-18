import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, Dict, List
import logging


def _sort_stmt_series(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return series
    try:
        if isinstance(series.index[0], (pd.Timestamp, pd.Period)):
            return series.sort_index(ascending=False)
    except Exception:
        pass
    return series


def _extract_stmt_series(stmt: Optional[pd.DataFrame], row_names: list[str]) -> Optional[pd.Series]:
    if stmt is None or getattr(stmt, "empty", True):
        return None
    for name in row_names:
        if name in stmt.index:
            series = stmt.loc[name].dropna()
            if not series.empty:
                return _sort_stmt_series(series)
    return None


def _extract_latest_value(stmt: Optional[pd.DataFrame], row_names: list[str]):
    series = _extract_stmt_series(stmt, row_names)
    if series is None or series.empty:
        return None
    return series.iloc[0]


def _extract_growth_pct(stmt: Optional[pd.DataFrame], row_names: list[str]) -> Optional[float]:
    series = _extract_stmt_series(stmt, row_names)
    if series is None or len(series) < 2:
        return None
    latest = series.iloc[0]
    previous = series.iloc[1]
    if previous is None or previous == 0 or (isinstance(previous, float) and previous != previous):
        return None
    return round(((latest - previous) / abs(previous)) * 100, 1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_news(symbol: str, limit: int = 8) -> List[Dict]:
    """
    Recent headlines from Yahoo Finance (free). Normalizes both yfinance news
    shapes (new nested `content` dict and the older flat dict) to:
        {title, publisher, url, published}
    Returns [] on any failure — headlines are nice-to-have, never blocking.
    """
    try:
        items = yf.Ticker(symbol).news or []
    except Exception as e:
        logger.error(f"Error fetching news for {symbol}: {e}")
        return []

    news = []
    for item in items:
        if not isinstance(item, dict):
            continue
        content = item.get("content") if isinstance(item.get("content"), dict) else item
        title = content.get("title")
        if not title:
            continue

        url = ""
        canonical = content.get("canonicalUrl") or content.get("clickThroughUrl")
        if isinstance(canonical, dict):
            url = canonical.get("url") or ""
        url = url or content.get("link") or item.get("link") or ""

        provider = content.get("provider")
        publisher = provider.get("displayName") if isinstance(provider, dict) else content.get("publisher")

        published = content.get("pubDate") or content.get("displayTime") or ""
        if not published and content.get("providerPublishTime"):
            try:
                published = datetime.fromtimestamp(
                    int(content["providerPublishTime"]), tz=timezone.utc
                ).isoformat()
            except (TypeError, ValueError, OSError):
                published = ""

        news.append({
            "title": str(title).strip(),
            "publisher": str(publisher or "").strip(),
            "url": str(url),
            "published": str(published),
        })
        if len(news) >= limit:
            break
    return news


def fetch_history(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """Price history only — much faster than fetch_ticker_data for charting."""
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            return None
        return hist
    except Exception as e:
        logger.error(f"Error fetching history for {symbol}: {e}")
        return None


def fetch_ticker_data(symbol: str) -> Optional[Dict]:
    """Fetch all data for a single ticker from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        # 1y gives the 200-day MA enough data (6mo left it permanently NaN)
        # and supports the research pack's 1y max-drawdown stat.
        hist = ticker.history(period="1y")

        if hist.empty:
            logger.warning(f"No price history for {symbol}")
            return None

        income_stmt = getattr(ticker, "income_stmt", None)
        if income_stmt is None or getattr(income_stmt, "empty", True):
            income_stmt = getattr(ticker, "financials", None)
        cashflow = getattr(ticker, "cashflow", None)
        if cashflow is None or getattr(cashflow, "empty", True):
            cashflow = getattr(ticker, "cash_flow", None)

        net_income_rows = [
            "Net Income",
            "Net Income Common Stockholders",
            "Net Income Applicable To Common Shares",
        ]
        net_income = _extract_latest_value(income_stmt, net_income_rows)
        net_income_growth = _extract_growth_pct(income_stmt, net_income_rows)
        fcf_growth = _extract_growth_pct(cashflow, ["Free Cash Flow"])

        if net_income is not None:
            info["netIncome"] = float(net_income)
        if net_income_growth is not None:
            info["netIncomeGrowth"] = float(net_income_growth)
        if fcf_growth is not None:
            info["freeCashflowGrowth"] = float(fcf_growth)

        return {
            "info": info,
            "history": hist,
        }
    except Exception as e:
        logger.error(f"Error fetching {symbol}: {e}")
        return None


def get_company_name(info: Dict) -> str:
    return info.get("longName") or info.get("shortName") or ""


# Custom sector taxonomy — authoritative per-ticker labels for the tracked
# universe. Edit SECTOR_GROUPS to re-bucket; data/watchlist.txt should match.
SECTOR_GROUPS = {
    "Semiconductors — chips, memory & IP": [
        "NVDA", "ARM", "MRVL", "NXPI", "STM", "AMBQ", "MXL", "RMBS",
        "SMTC", "ALAB", "KXIAY", "ADEA", "LSCC", "INTC", "MTSI",
    ],
    "Power semiconductors & conversion": [
        "POWI", "MPWR", "IPWR", "AOSL", "NVTS",
    ],
    "Semiconductor equipment, test & materials": [
        "TER", "ATEYY", "AEHR", "ACLS", "CAMT", "VECO", "MKSI", "PLAB",
        "ATOM", "AXTI", "IMOS", "ASX", "IBIDY", "KEYS", "TRT", "AMAT",
        "AIXA.DE",
    ],
    "Software, AI & computing": [
        "CRWD", "PANW", "SAIL", "CDNS", "SNPS", "PATH", "TWLO", "INOD",
        "REKR", "TASK", "NBIS", "IONQ", "SVCO", "BSY", "BBAI", "VEEV",
    ],
    "Communications, networking & optical": [
        "CSCO", "ERIC", "ATEN", "VIAV", "LITE", "AAOI", "POET", "LWLG",
        "LPTH", "CLFD", "HLIT", "AMPG", "CIEN",
    ],
    "IT hardware & electronic components": [
        "IBM", "HPQ", "HPE", "SMCI", "SANM", "CRSR", "P", "PENG",
        "TEL", "KOPN",
    ],
    "Aerospace, defense, space & industrials": [
        "PH", "EMR", "TDY", "ELMT", "BWA", "RKLB", "SPIR", "BKSY",
        "RDW", "PL", "SATS", "MOD",
    ],
    "Physical AI — autonomy, robotics & humanoid components": [
        "MOG-A", "YASKY", "MBLY", "OUST", "HSAI", "VPG",
    ],
    "Energy, power & electrification": [
        "ENPH", "SEDG", "FLNC", "NRG", "ETN", "POWL", "FPS", "CGEH",
        "HYLN", "PUMP", "VST", "2GB.DE",
    ],
    "Chemicals & specialty materials": [
        "ROG", "SOLS", "MP",
    ],
    "Healthcare & biotech": [
        "LLY", "RXRX", "ABCL", "IBRX", "TEM", "TWST", "MDT", "SDGR",
        "BFLY", "AKTS",
    ],
    "Financials & fintech": [
        "JPM", "HOOD", "IBKR", "DLO",
    ],
    "Crypto / digital assets": [
        "GLXY", "CRCL", "CYPH", "IREN", "ONDO",
    ],
    "Consumer, gaming & leisure": [
        "MGM",
    ],
    "ETFs / funds": [
        "XLE", "XLP", "GLDM", "TAN", "NLR", "EWZ", "SLV",
    ],
    "Real estate / holding companies": [
        "HHH",
    ],
}

# Flattened ticker -> sector lookup.
SECTOR_MAP = {sym: sector for sector, syms in SECTOR_GROUPS.items() for sym in syms}


def get_sector(info: Dict, symbol: str = "") -> str:
    """Authoritative custom sector for tracked tickers; Yahoo's sector as fallback."""
    sector = SECTOR_MAP.get(symbol.upper())
    if sector:
        return sector
    return info.get("sector", "")
