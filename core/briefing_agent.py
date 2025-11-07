from .fetch_prices import get_price_changes
from .fetch_news import get_all_news
from utils.logger import get_logger
import yaml
from pathlib import Path

logger = get_logger("BriefingAgent")

def run_briefing_test():
    """Testmodus: Kursdaten + aktuelle Finanznachrichten"""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    portfolio = settings["portfolio"]
    watchlist = settings["watchlist"]

    logger.info("Hole Kursdaten...")
    portfolio_data, last_date = get_price_changes(portfolio)
    watchlist_data, _ = get_price_changes(watchlist)

    if last_date:
        print(f"\n📅 Letzter Handelstag: {last_date}\n")

    # Kursausgabe
    print("=== 💼 PORTFOLIO ===")
    for s in portfolio_data:
        emoji = "🟢" if s.change_percent > 0.3 else "🟡" if -0.3 <= s.change_percent <= 0.3 else "🔴"
        print(f"{s.symbol}: {s.change_percent:+.2f}% {emoji}")

    print("\n=== 👁️ WATCHLIST ===")
    for s in watchlist_data:
        emoji = "🟢" if s.change_percent > 0.3 else "🟡" if -0.3 <= s.change_percent <= 0.3 else "🔴"
        print(f"{s.symbol}: {s.change_percent:+.2f}% {emoji}")

    # Nachrichten
    print("\n📰 === NEUIGKEITEN ===")
    logger.info("Rufe aktuelle Nachrichten ab...")

    news_portfolio = get_all_news(portfolio)
    news_watchlist = get_all_news(watchlist)

    for section, data in [("Portfolio", news_portfolio), ("Watchlist", news_watchlist)]:
        print(f"\n## {section}")
        for sym, articles in data.items():
            print(f"\n### {sym}")
            if not articles:
                print("   Keine aktuellen News.")
                continue
            for a in articles:
                print(f"• {a.title} ({a.source})")
                print(f"  🔗 {a.link}")

    return {
        "portfolio": portfolio_data,
        "watchlist": watchlist_data,
        "news": {"portfolio": news_portfolio, "watchlist": news_watchlist},
        "last_trading_day": last_date
    }
