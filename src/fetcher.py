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


def get_sector(info: Dict) -> str:
    return info.get("sector", "")
