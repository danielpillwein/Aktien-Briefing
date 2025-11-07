from .fetch_prices import get_price_changes
from utils.logger import get_logger
import yaml
from pathlib import Path

logger = get_logger("BriefingAgent")


def run_briefing_test():
    """Führt einen Testlauf des Agenten durch und zeigt Kursveränderungen."""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    portfolio = settings["portfolio"]
    watchlist = settings["watchlist"]

    logger.info("Hole Kursdaten für Portfolio und Watchlist...")

    portfolio_data, last_date = get_price_changes(portfolio)
    watchlist_data, _ = get_price_changes(watchlist)

    if last_date:
        print(f"\n📅 Letzter Handelstag: {last_date}\n")
    else:
        print("\n⚠️ Kein gültiges Handelsdatum gefunden!\n")

    # Ausgabe
    if portfolio_data:
        print("=== 💼 PORTFOLIO ===")
        for s in portfolio_data:
            emoji = "🟢" if s.change_percent > 0.3 else "🟡" if -0.3 <= s.change_percent <= 0.3 else "🔴"
            print(f"{s.symbol}: {s.change_percent:+.2f}% {emoji}")
    else:
        print("Keine Kursdaten im Portfolio.")

    if watchlist_data:
        print("\n=== 👁️ WATCHLIST ===")
        for s in watchlist_data:
            emoji = "🟢" if s.change_percent > 0.3 else "🟡" if -0.3 <= s.change_percent <= 0.3 else "🔴"
            print(f"{s.symbol}: {s.change_percent:+.2f}% {emoji}")
    else:
        print("Keine Kursdaten in der Watchlist.")

    return {
        "portfolio": portfolio_data,
        "watchlist": watchlist_data,
        "last_trading_day": last_date
    }
