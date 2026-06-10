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


# AI Supply Chain bucket overrides
# Replaces generic Yahoo Finance "Technology" with granular AI layer classification
_AI_BUCKETS = {
    # Compute / Semiconductors
    "NVDA": "Compute / Semiconductors",
    "LSCC": "Compute / Semiconductors",
    "QCOM": "Compute / Semiconductors",
    "NXPI": "Compute / Semiconductors",
    "IFX.DE": "Compute / Semiconductors",
    "MPWR": "Compute / Semiconductors",
    "MXL": "Compute / Semiconductors",
    "CRDO": "Compute / Semiconductors",
    "SIVEF": "Compute / Semiconductors",
    "NVTS": "Compute / Semiconductors",
    "AMBA": "Compute / Semiconductors",
    "ENSI.L": "Compute / Semiconductors",
    "VPG": "Compute / Semiconductors",
    # Memory / Storage
    "MU": "Memory / Storage",
    # Photonics / Optics
    "LITE": "Photonics / Optics",
    "COHR": "Photonics / Optics",
    "AAOI": "Photonics / Optics",
    "POET": "Photonics / Optics",
    "GLW": "Photonics / Optics",
    # OSAT / Packaging
    "AMKR": "OSAT / Packaging",
    "ASX": "OSAT / Packaging",
    "IMOS": "OSAT / Packaging",
    "067310.KQ": "OSAT / Packaging",
    "2317.TW": "OSAT / Packaging",
    "SANM": "OSAT / Packaging",
    "FN": "OSAT / Packaging",
    # Equipment / Manufacturing
    "AMAT": "Equipment / Manufacturing",
    "TER": "Equipment / Manufacturing",
    "ONTO": "Equipment / Manufacturing",
    "MKSI": "Equipment / Manufacturing",
    "VECO": "Equipment / Manufacturing",
    "ACLS": "Equipment / Manufacturing",
    "ATEYY": "Equipment / Manufacturing",
    "AEHR": "Equipment / Manufacturing",
    "KEYS": "Equipment / Manufacturing",
    "CAMT": "Equipment / Manufacturing",
    "FORM": "Equipment / Manufacturing",
    "PLAB": "Equipment / Manufacturing",
    "TRT": "Equipment / Manufacturing",
    "AIXXF": "Equipment / Manufacturing",
    "ALRIB.PA": "Equipment / Manufacturing",
    "6315.T": "Equipment / Manufacturing",
    # Chemicals / Materials
    "ENTG": "Chemicals / Materials",
    "ESI": "Chemicals / Materials",
    "CC": "Chemicals / Materials",
    "MP": "Chemicals / Materials",
    "ATOM": "Chemicals / Materials",
    "AXTI": "Chemicals / Materials",
    "ROG": "Chemicals / Materials",
    "SOI.PA": "Chemicals / Materials",
    "AJINF": "Chemicals / Materials",
    # Power / Infrastructure
    "VST": "Power / Infrastructure",
    "FLNC": "Power / Infrastructure",
    "HMDPF": "Power / Infrastructure",
    "POWL": "Power / Infrastructure",
    "MRN.PA": "Power / Infrastructure",
    "P9U.F": "Power / Infrastructure",
    "VICR": "Power / Infrastructure",
    "267260.KS": "Power / Infrastructure",
    "ETN": "Power / Infrastructure",
    # Networking / Connectivity
    "NOK": "Networking / Connectivity",
    "FSLY": "Networking / Connectivity",
    "HUBN.SW": "Networking / Connectivity",
    "PRYMF": "Networking / Connectivity",
    # Data Center / Infrastructure
    "SMCI": "Data Center / Infrastructure",
    "DELL": "Data Center / Infrastructure",
    "MSFT": "Data Center / Infrastructure",
    "GOOGL": "Data Center / Infrastructure",
    "VRT": "Data Center / Infrastructure",
    "3017.TW": "Data Center / Infrastructure",
    # Edge Devices / End Products
    "AAPL": "Edge Devices / End Products",
    "TSLA": "Edge Devices / End Products",
    "PL": "Edge Devices / End Products",
    "RKLB": "Edge Devices / End Products",
    "P": "Edge Devices / End Products",
    # Broad Market / ETFs
    "COPX": "Broad Market / ETFs",
    "EWZ": "Broad Market / ETFs",
    "GLDM": "Broad Market / ETFs",
    "GRID": "Broad Market / ETFs",
    "IHE": "Broad Market / ETFs",
    "IVV": "Broad Market / ETFs",
    "IWM": "Broad Market / ETFs",
    "KOID": "Broad Market / ETFs",
    "NLR": "Broad Market / ETFs",
    "XBI": "Broad Market / ETFs",
    "XLP": "Broad Market / ETFs",
    # Crypto
    "ETH-USD": "Crypto",
    "ONDO-USD": "Crypto",
    "TON11419-USD": "Crypto",
    "WTAO-USD": "Crypto",
    "ZEC-USD": "Crypto",
    "CYPH": "Crypto",
    "IREN": "Crypto",
    # Healthcare
    "IBRX": "Healthcare",
    "ABCL": "Healthcare",
    # New from image uploads
    "011790.KS": "Chemicals / Materials",
    "3363.TWO": "Photonics / Optics",
    "6268.T": "Equipment / Manufacturing",
    "6324.T": "Equipment / Manufacturing",
    "6503.T": "Power / Infrastructure",
    "6981.T": "Chemicals / Materials",
    "AMBQ": "Compute / Semiconductors",
    "APH": "Networking / Connectivity",
    "CSCO": "Networking / Connectivity",
    "HSAI": "Edge Devices / End Products",
    "K3R.SG": "Equipment / Manufacturing",
    "LPTH": "Photonics / Optics",
    "LWLG": "Photonics / Optics",
    "MBLY": "Edge Devices / End Products",
    "MRVL": "Compute / Semiconductors",
    "NIPNF": "Compute / Semiconductors",
    "OUST": "Edge Devices / End Products",
    "OZPV.IL": "Photonics / Optics",
    "PENG": "Data Center / Infrastructure",
    "RMBS": "Compute / Semiconductors",
    "TEL": "Networking / Connectivity",
    "VIAV": "Networking / Connectivity",
}


def get_sector(info: Dict, symbol: str = "") -> str:
    # Prefer AI supply chain bucket; fall back to Yahoo Finance sector
    bucket = _AI_BUCKETS.get(symbol.upper(), "")
    if bucket:
        return bucket
    return info.get("sector", "")
