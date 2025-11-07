import asyncio
from .fetch_prices import get_price_changes
from .fetch_news import get_all_news
from .market_overview import summarize_portfolio_news
from utils.logger import get_logger
from .async_ai import async_summarize, async_sentiment
import yaml
from pathlib import Path

logger = get_logger("BriefingAgent")


async def process_article(symbol: str, article, semaphore: asyncio.Semaphore):
    """Hilfsfunktion: fasst Artikel zusammen + bestimmt Sentiment."""
    summary = await async_summarize(article.title, semaphore)
    sentiment = await async_sentiment(summary, semaphore)
    emoji = {"Positiv": "🟢", "Neutral": "🟡", "Negativ": "🔴"}[sentiment]
    return symbol, {
        "summary": summary,
        "sentiment": sentiment,
        "emoji": emoji,
        "title": article.title,
        "link": article.link,
    }


async def process_articles_async(news_portfolio, news_watchlist):
    """Verarbeitet alle Artikel (Portfolio + Watchlist) im selben Loop."""
    semaphore = asyncio.Semaphore(5)
    tasks = []

    # Portfolio & Watchlist zusammen
    for sym, articles in {**news_portfolio, **news_watchlist}.items():
        for a in articles[:2]:
            tasks.append(process_article(sym, a, semaphore))

    results = await asyncio.gather(*tasks)
    output_portfolio, output_watchlist = {}, {}

    for sym, data in results:
        # Zuordnung in Portfolio oder Watchlist
        if sym in news_portfolio:
            output_portfolio.setdefault(sym, []).append(data)
        else:
            output_watchlist.setdefault(sym, []).append(data)

    return output_portfolio, output_watchlist


def run_briefing_test():
    """Asynchrone KI-News-Analyse im Testmodus."""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    portfolio = settings["portfolio"]
    watchlist = settings["watchlist"]

    logger.info("Hole Kursdaten...")
    portfolio_data, last_date = get_price_changes(portfolio)
    watchlist_data, _ = get_price_changes(watchlist)
    print(f"\n📅 Letzter Handelstag: {last_date}\n")

    logger.info("Rufe aktuelle Nachrichten ab...")
    news_portfolio = get_all_news(portfolio)
    news_watchlist = get_all_news(watchlist)

    # === Parallele KI-Analyse starten ===
    logger.info("Starte parallele KI-Analyse...")
    portfolio_results, watchlist_results = asyncio.run(
        process_articles_async(news_portfolio, news_watchlist)
    )

    # === Ausgabe ===
    print("\n## 📊 Portfolio")
    summaries = []
    for sym, articles in portfolio_results.items():
        print(f"\n### {sym}")
        for a in articles:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 [Artikel öffnen]({a['link']})\n")
            summaries.append(a["summary"])

    print("\n## 👁️ Watchlist")
    for sym, articles in watchlist_results.items():
        print(f"\n### {sym}")
        for a in articles:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 [Artikel öffnen]({a['link']})\n")

    # === Gesamtzusammenfassung ===
    logger.info("Erstelle Gesamtzusammenfassung...")
    overall_summary = summarize_portfolio_news(summaries)

    print("\n---\n")
    print("🔍 **Gesamtzusammenfassung:**")
    print(overall_summary)

    return {
        "portfolio": portfolio_data,
        "watchlist": watchlist_data,
        "news": {"portfolio": portfolio_results, "watchlist": watchlist_results},
        "summary": overall_summary,
        "last_trading_day": last_date,
    }
