import asyncio
import yaml
from pathlib import Path
from utils.logger import get_logger
from .fetch_prices import get_price_changes
from .fetch_news import get_all_news
from .market_overview import summarize_portfolio_news, generate_market_overview
from .async_ai import async_summarize, async_sentiment
from .report_builder import render_report

logger = get_logger("BriefingAgent")


# === Async-Helferfunktionen ===
async def process_article(symbol: str, article, semaphore: asyncio.Semaphore):
    """Fasst Artikel zusammen + bestimmt Sentiment asynchron."""
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
    """Verarbeitet alle Artikel (Portfolio + Watchlist) asynchron im selben Loop."""
    semaphore = asyncio.Semaphore(5)
    tasks = []

    # Kombinierte Verarbeitung
    for sym, articles in {**news_portfolio, **news_watchlist}.items():
        for a in articles[:2]:  # begrenze auf 2 Artikel pro Aktie
            tasks.append(process_article(sym, a, semaphore))

    results = await asyncio.gather(*tasks)
    output_portfolio, output_watchlist = {}, {}

    for sym, data in results:
        if sym in news_portfolio:
            output_portfolio.setdefault(sym, []).append(data)
        else:
            output_watchlist.setdefault(sym, []).append(data)

    return output_portfolio, output_watchlist


# === Hauptfunktion ===
def run_briefing_test():
    """Führt gesamten Agenten im Testmodus aus: Kurse, News, KI, Report."""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    portfolio = settings["portfolio"]
    watchlist = settings["watchlist"]

    logger.info("Hole Kursdaten...")
    portfolio_data, last_date = get_price_changes(portfolio)
    watchlist_data, _ = get_price_changes(watchlist)

    print(f"\n📅 Letzter Handelstag: {last_date}\n")

    # === News abrufen ===
    logger.info("Rufe aktuelle Nachrichten ab...")
    news_portfolio = get_all_news(portfolio)
    news_watchlist = get_all_news(watchlist)

    # === Parallele KI-Analyse starten ===
    logger.info("Starte parallele KI-Analyse...")
    portfolio_results, watchlist_results = asyncio.run(
        process_articles_async(news_portfolio, news_watchlist)
    )

    # === Ausgabe Portfolio ===
    print("\n## 📊 Portfolio")
    summaries = []  # <-- hier initialisieren
    for sym, articles in portfolio_results.items():
        print(f"\n### {sym}")
        for a in articles:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 [Artikel öffnen]({a['link']})\n")
            summaries.append(a["summary"])

    # === Ausgabe Watchlist ===
    print("\n## 👁️ Watchlist")
    for sym, articles in watchlist_results.items():
        print(f"\n### {sym}")
        for a in articles:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 [Artikel öffnen]({a['link']})\n")

    # === Marktüberblick mit GPT-Analyse ===
    logger.info("Erstelle Marktanalyse (Makro/Portfolio/Gesamteinschätzung)...")
    overview = generate_market_overview(portfolio_data, summaries)

    print("\n🧭 **KI-Marktanalyse:**")
    print(f"📊 Marktlage: {overview['macro']}\n")
    print(f"💡 Portfolioausblick: {overview['portfolio']}\n")
    print(f"**Gesamteinschätzung:** {overview['final']['emoji']} {overview['final']['text']}")


# === Kursdaten formatieren ===
    def format_stock(s):
        if s.change_percent > 0.3:
            emoji = "🟢"
        elif s.change_percent < -0.3:
            emoji = "🔴"
        else:
            emoji = "🟡"
        sentiment = (
            "Positiv" if emoji == "🟢" else "Negativ" if emoji == "🔴" else "Neutral"
        )
        return {
            "symbol": s.symbol,
            "change": f"{s.change_percent:+.2f}%",
            "sentiment": sentiment,
            "emoji": emoji,
        }

    # === Report-Datenstruktur für Markdown ===
    data_for_report = {
        "portfolio": [format_stock(s) for s in portfolio_data],
        "watchlist": [format_stock(s) for s in watchlist_data],
        "news": {
            # Einschätzung und Link jeweils eigene Zeile
            "portfolio": {
                sym: [
                    {
                        "summary": a["summary"],
                        "sentiment": a["sentiment"],
                        "emoji": a["emoji"],
                        "link": a["link"],
                    }
                    for a in articles
                ]
                for sym, articles in portfolio_results.items()
            },
            "watchlist": {
                sym: [
                    {
                        "summary": a["summary"],
                        "sentiment": a["sentiment"],
                        "emoji": a["emoji"],
                        "link": a["link"],
                    }
                    for a in articles
                ]
                for sym, articles in watchlist_results.items()
            },
        },
        "overview": overview,
    }

    render_report(data_for_report)

    logger.info("✅ Testmodus abgeschlossen.")
    return data_for_report
