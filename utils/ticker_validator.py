import re
from typing import Dict, List, Tuple

import yfinance as yf

TICKER_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,14}$")
NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")


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


def _compact(value: str) -> str:
    return NON_ALNUM_PATTERN.sub("", (value or "").lower())


def _score_candidate(item: Dict, query: str) -> int:
    q = (query or "").strip().lower()
    q_compact = _compact(q)
    q_tokens = [t for t in re.split(r"\s+", q) if t]

    symbol = str(item.get("symbol") or "").strip()
    name = str(item.get("name") or "").strip()
    qtype = str(item.get("type") or "").upper()
    exchange = str(item.get("exchange") or "").upper()

    symbol_l = symbol.lower()
    name_l = name.lower()
    symbol_compact = _compact(symbol_l)
    name_compact = _compact(name_l)

    score = 0

    if qtype == "EQUITY":
        score += 140
    elif qtype in {"ETF", "FUND"}:
        score += 30

    if q_compact and symbol_compact == q_compact:
        score += 260
    if q_compact and name_compact == q_compact:
        score += 220
    if q_compact and symbol_compact.startswith(q_compact):
        score += 180
    if q_compact and name_compact.startswith(q_compact):
        score += 140
    if q_compact and q_compact in symbol_compact:
        score += 100
    if q_compact and q_compact in name_compact:
        score += 80

    for token in q_tokens:
        token_compact = _compact(token)
        if len(token_compact) < 2:
            continue
        if token_compact in symbol_compact:
            score += 36
        if token_compact in name_compact:
            score += 22

    if exchange in {"NASDAQ", "NMS", "NYSE", "XETRA", "FWB"}:
        score += 12

    return score


def search_ticker_candidates(query: str, limit: int = 5) -> List[Dict]:
    q = (query or "").strip()
    if not q:
        return []

    raw_quotes = []
    try:
        max_results = max(limit * 5, 25)
        try:
            search_obj = yf.Search(query=q, max_results=max_results)
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

    ranked = sorted(
        normalized,
        key=lambda item: (
            _score_candidate(item, q),
            1 if item.get("type") == "EQUITY" else 0,
            -len(str(item.get("symbol", ""))),
        ),
        reverse=True,
    )
    return ranked[:limit]
