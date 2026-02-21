import re
from typing import Dict, List, Tuple

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


def suggest_name_from_yfinance(ticker: str) -> str:
    try:
        y_ticker = yf.Ticker(ticker)
        info = {}
        try:
            info = y_ticker.get_info() or {}
        except Exception:
            try:
                info = y_ticker.info or {}
            except Exception:
                info = {}

        for key in ("shortName", "longName", "displayName", "name"):
            value = info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass
    return ticker


def _normalize_quote(quote: Dict) -> Dict:
    symbol = str(quote.get("symbol") or "").strip().upper()
    if not symbol:
        return {}

    name = (
        quote.get("shortname")
        or quote.get("longname")
        or quote.get("name")
        or quote.get("displayName")
        or symbol
    )
    exchange = (
        quote.get("exchange")
        or quote.get("exchDisp")
        or quote.get("fullExchangeName")
        or ""
    )
    qtype = (quote.get("quoteType") or quote.get("typeDisp") or "").upper()

    return {
        "symbol": symbol,
        "name": str(name).strip() or symbol,
        "exchange": str(exchange).strip(),
        "type": qtype,
    }


def search_ticker_candidates(query: str, limit: int = 5) -> List[Dict]:
    q = (query or "").strip()
    if not q:
        return []

    raw_quotes = []
    try:
        try:
            search_obj = yf.Search(query=q, max_results=max(limit * 2, 10))
        except TypeError:
            search_obj = yf.Search(q)

        for attr in ("quotes", "results"):
            value = getattr(search_obj, attr, None)
            if isinstance(value, list):
                raw_quotes = value
                break
    except Exception:
        raw_quotes = []

    normalized: List[Dict] = []
    seen = set()
    for quote in raw_quotes:
        if not isinstance(quote, dict):
            continue
        item = _normalize_quote(quote)
        symbol = item.get("symbol", "")
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(item)

    equities = [x for x in normalized if x.get("type") == "EQUITY"]
    ranked = equities if equities else normalized
    return ranked[:limit]
