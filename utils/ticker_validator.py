import re
from typing import Tuple

import yfinance as yf

TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")


def normalize_ticker(ticker: str) -> str:
    if ticker is None:
        return ""
    return ticker.strip().upper()


def validate_ticker_syntax(ticker: str) -> Tuple[bool, str]:
    if not ticker:
        return False, "Ticker fehlt."
    if not TICKER_PATTERN.match(ticker):
        return False, "Ungültiges Ticker-Format."
    return True, ""


def validate_ticker_exists_yfinance(ticker: str) -> Tuple[bool, str]:
    try:
        data = yf.Ticker(ticker).history(period="5d", interval="1d")
        if data is None or data.empty:
            return False, f"Ticker {ticker} ist über yfinance nicht verfügbar."
        return True, ""
    except Exception:
        return False, "Ticker-Validierung derzeit nicht möglich (yfinance nicht erreichbar)."
