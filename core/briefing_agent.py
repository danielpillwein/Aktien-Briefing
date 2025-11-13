import asyncio
import yaml
from pathlib import Path
from utils.logger import get_logger
from .fetch_prices import get_price_changes
from .fetch_news import get_all_news
from .market_overview import summarize_portfolio_news, generate_market_overview
from .async_ai import async_summarize, async_sentiment
from .report_builder import render_report
from utils.notifications import send_briefing_blocks
from utils.archive_manager import archive_report

logger = get_logger("BriefingAgent")


async def process_article(ticker: str, article, semaphore: asyncio.Semaphore):
    """Fasst Artikel zusammen + bestimmt Sentiment asynchron."""
    summary = await async_summarize(article.title, semaphore)
    sentiment = await async_sentiment(summary, semaphore)
    emoji = {"Positiv": "🟢", "Neutral": "🟡", "Negativ": "🔴"}[sentiment]

    return ticker, {
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

    combined = {**news_portfolio, **news_watchlist}

    for ticker, articles in combined.items():
        for a in articles[:2]:
            tasks.append(process_article(ticker, a, semaphore))

    results = await asyncio.gather(*tasks)
    out_portfolio, out_watchlist = {}, {}

    for ticker, data in results:
        if ticker in news_portfolio:
            out_portfolio.setdefault(ticker, []).append(data)
        else:
            out_watchlist.setdefault(ticker, []).append(data)

    return out_portfolio, out_watchlist


def run_briefing_test(send_telegram: bool = True):
    """Führt gesamten Agenten im Testmodus aus: Kurse, News, KI, Report, Telegram."""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)

    portfolio_items = settings["portfolio"]
    watchlist_items = settings["watchlist"]

    logger.info("Hole Kursdaten.")
    portfolio_data, last_date = get_price_changes(portfolio_items)
    watchlist_data, _ = get_price_changes(watchlist_items)

    print(f"\n📅 Letzter Handelstag: {last_date}\n")

    logger.info("Rufe aktuelle Nachrichten ab.")
    news_portfolio_raw = get_all_news(portfolio_items)
    news_watchlist_raw = get_all_news(watchlist_items)

    logger.info("Starte parallele KI-Analyse.")
    portfolio_results_raw, watchlist_results_raw = asyncio.run(
        process_articles_async(news_portfolio_raw, news_watchlist_raw)
    )

    # ---------------------------------------------------------
    #  STAGE-4: Ticker-Keys → Name-Keys für Report & Telegram
    # ---------------------------------------------------------

    name_map_portfolio = {item["ticker"]: item["name"] for item in portfolio_items}
    name_map_watchlist = {item["ticker"]: item["name"] for item in watchlist_items}

    # Convert news dicts to NAME-keys
    news_portfolio = {
        name_map_portfolio[ticker]: articles
        for ticker, articles in portfolio_results_raw.items()
    }

    news_watchlist = {
        name_map_watchlist[ticker]: articles
        for ticker, articles in watchlist_results_raw.items()
    }

    # ---------------------------------------------------------

    print("\n## 📊 Portfolio")
    summaries = []

    for item in portfolio_items:
        name = item["name"]
        ticker = item["ticker"]
        arts = portfolio_results_raw.get(ticker, [])

        print(f"\n### {name}")
        for a in arts:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 {a['link']}\n")
            summaries.append(a["summary"])

    print("\n## 👁‍🗨 Watchlist")
    for item in watchlist_items:
        name = item["name"]
        ticker = item["ticker"]
        arts = watchlist_results_raw.get(ticker, [])

        print(f"\n### {name}")
        for a in arts:
            print(f"- {a['summary']}")
            print(f"  Einschätzung: {a['emoji']} {a['sentiment']}")
            print(f"  🔗 {a['link']}\n")

    logger.info("Erstelle Gesamtzusammenfassung.")
    overall_summary = summarize_portfolio_news(summaries)
    print("\n---\n")
    print("🔍 **Gesamtzusammenfassung:**")
    print(overall_summary)

    logger.info("Erstelle Marktanalyse.")
    overview = generate_market_overview(portfolio_data, summaries)

    def format_stock(s):
        if s.change_percent > 0.3:
            emoji = "🟢"
        elif s.change_percent < -0.3:
            emoji = "🔴"
        else:
            emoji = "🟡"

        return {
            "symbol": s.symbol,       # Name-only (Stage-4)
            "change": f"{s.change_percent:+.2f}%",
            "emoji": emoji,
        }

    # ---------------------------------------------------------
    # STAGE-4: Report-Daten NUR mit Name-Keys
    # ---------------------------------------------------------
    data_for_report = {
        "portfolio": [format_stock(s) for s in portfolio_data],
        "watchlist": [format_stock(s) for s in watchlist_data],
        "news": {
            "portfolio": news_portfolio,   # Name-based
            "watchlist": news_watchlist,   # Name-based
        },
        "overview": overview,
    }
    # ---------------------------------------------------------

    render_report(data_for_report)

    if send_telegram:
        logger.info("📨 Sende Telegram-Blöcke (Testmodus).")
        send_briefing_blocks(data_for_report)

    logger.info("📦 Archiviere Report.")
    archive_report()

    logger.info("✓ Briefing abgeschlossen.")
    return data_for_report
