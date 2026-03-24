import yfinance as yf
from loguru import logger
from pydantic import BaseModel
from typing import List, Tuple, Optional
from datetime import datetime


class StockChange(BaseModel):
    symbol: str      # Name für die Ausgabe
    ticker: str
    change_percent: float
    last_trading_day: str
    since_watchlist_percent: Optional[float] = None
    watchlist_added_at: Optional[str] = None


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None


def _safe_date(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", ""))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def _resolve_watchlist_entry_close(ticker_obj, item: dict, recent_data) -> Optional[float]:
    """
    Einstiegskurs für Watchlist-Performance:
    1) explizit gespeicherter watchlist_added_close
    2) erster Schlusskurs ab watchlist_added_at
    """
    explicit = _safe_float(item.get("watchlist_added_close"))
    if explicit not in (None, 0.0):
        return explicit

    added_date = _safe_date(str(item.get("watchlist_added_at", "")))
    if not added_date:
        return None

    try:
        # Falls der Zeitraum bereits im recent_data liegt, diesen zuerst nutzen.
        if len(recent_data) > 0:
            sliced = recent_data[recent_data.index >= added_date]
            sliced = sliced.dropna(subset=["Close"])
            if len(sliced) > 0:
                return _safe_float(sliced["Close"].iloc[0])

        hist = ticker_obj.history(start=added_date, interval="1d").dropna(subset=["Close"])
        if len(hist) > 0:
            return _safe_float(hist["Close"].iloc[0])
    except Exception:
        return None

    return None


def get_price_changes(items: List[dict]) -> Tuple[List[StockChange], Optional[str]]:
    """
    Holt Kursänderungen (in %) basierend auf dem TICKER.
    items = [{ticker: "...", name: "..."}]
    """
    results = []
    last_trading_day = None

    for item in items:
        ticker_symbol = item["ticker"]
        name = item["name"]
        try:
            ticker = yf.Ticker(ticker_symbol)
            data = ticker.history(period="10d", interval="1d").dropna(subset=["Close"])
            watchlist_added_close = _resolve_watchlist_entry_close(ticker, item, data)

            if len(data) < 2:
                logger.warning(f"Keine ausreichenden Daten für {ticker_symbol}")
                continue

            last_close = data["Close"].iloc[-1]
            prev_close = data["Close"].iloc[-2]
            last_date = data.index[-1].strftime("%Y-%m-%d")
            change = ((last_close - prev_close) / prev_close) * 100

            if not last_trading_day:
                last_trading_day = last_date

            results.append(
                StockChange(
                    symbol=name,                   # Name statt ticker für Anzeige
                    ticker=ticker_symbol,
                    change_percent=round(change, 2),
                    last_trading_day=last_date,
                    since_watchlist_percent=(
                        round(((last_close - watchlist_added_close) / watchlist_added_close) * 100, 2)
                        if watchlist_added_close not in (None, 0.0)
                        else None
                    ),
                    watchlist_added_at=str(item.get("watchlist_added_at", "")).strip() or None,
                )
            )

        except Exception as e:
            logger.error(f"Fehler beim Abruf von {ticker_symbol}: {e}")

    if not last_trading_day:
        logger.warning("Konnte kein Handelsdatum bestimmen.")

    return results, last_trading_day
