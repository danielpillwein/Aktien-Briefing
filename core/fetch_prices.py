import yfinance as yf
from loguru import logger
from pydantic import BaseModel
from typing import List, Tuple, Optional


class StockChange(BaseModel):
    symbol: str      # Name für die Ausgabe
    change_percent: float
    last_trading_day: str


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
                    change_percent=round(change, 2),
                    last_trading_day=last_date
                )
            )

        except Exception as e:
            logger.error(f"Fehler beim Abruf von {ticker_symbol}: {e}")

    if not last_trading_day:
        logger.warning("Konnte kein Handelsdatum bestimmen.")

    return results, last_trading_day
