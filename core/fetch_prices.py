import yfinance as yf
from loguru import logger
from pydantic import BaseModel
from typing import List, Tuple, Optional


class StockChange(BaseModel):
    symbol: str
    change_percent: float
    last_trading_day: str


def get_price_changes(symbols: List[str]) -> Tuple[List[StockChange], Optional[str]]:
    """
    Holt Kursänderungen (in %) für Aktien, immer basierend auf dem letzten verfügbaren Handelstag.
    Gibt zusätzlich das verwendete Handelsdatum zurück.
    """
    results = []
    last_trading_day = None

    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            data = ticker.history(period="10d", interval="1d").dropna(subset=["Close"])

            if len(data) < 2:
                logger.warning(f"Keine ausreichenden Daten für {sym}")
                continue

            # Letzter und vorletzter Handelstag
            last_close = data["Close"].iloc[-1]
            prev_close = data["Close"].iloc[-2]
            last_date = data.index[-1].strftime("%Y-%m-%d")

            change = ((last_close - prev_close) / prev_close) * 100

            # Setze das Handelsdatum (nur einmal, falls mehrfach abgefragt)
            if not last_trading_day:
                last_trading_day = last_date

            results.append(
                StockChange(
                    symbol=sym,
                    change_percent=round(change, 2),
                    last_trading_day=last_date
                )
            )
        except Exception as e:
            logger.error(f"Fehler beim Abruf von {sym}: {e}")

    if not last_trading_day:
        logger.warning("Konnte kein Handelsdatum bestimmen.")
    return results, last_trading_day
