import yfinance as yf
import pandas as pd
from typing import Optional, Dict
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fetch_ticker_data(symbol: str) -> Optional[Dict]:
    """Fetch all data for a single ticker from Yahoo Finance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        hist = ticker.history(period="6mo")

        if hist.empty:
            logger.warning(f"No price history for {symbol}")
            return None

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
}


def get_sector(info: Dict, symbol: str = "") -> str:
    # Prefer AI supply chain bucket; fall back to Yahoo Finance sector
    bucket = _AI_BUCKETS.get(symbol.upper(), "")
    if bucket:
        return bucket
    return info.get("sector", "")
