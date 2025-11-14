import asyncio
from loguru import logger

from config.settings_loader import load_settings
from core.fetch_news import fetch_all_sources
from core.async_ai import process_article
from core.market_overview import generate_market_overview
from core.fetch_prices import get_price_changes
from core.report_builder import render_report
from utils.archive_manager import archive_report
from utils.notifications import send_briefing_blocks


# ---------------------------------------
# Kursformatierung
# ---------------------------------------
def format_stock(s):
    try:
        change = float(s.change_percent)

        if change > 0.3:
            emoji = "🟢"
        elif change < -0.3:
            emoji = "🔴"
        else:
            emoji = "🟡"

        return {
            "symbol": getattr(s, "symbol", "Unknown"),
            "change": f"{change:+.2f}%",
            "emoji": emoji,
        }
    except Exception as e:
        logger.error(f"FormatStock Fehler: {e}")
        return {
            "symbol": getattr(s, "symbol", "Unknown"),
            "change": "0.00%",
            "emoji": "🟡",
        }


# ---------------------------------------
# News-Analyse
# ---------------------------------------
async def analyze_news_for_items(items):
    results = {}

    for item in items:
        name = item["name"]

        logger.info(f"Hole News für {name}…")
        raw_articles = await fetch_all_sources(name)

        if not raw_articles:
            results[name] = []
            continue

        logger.info(f"Analysiere {len(raw_articles)} Artikel für {name}…")

        tasks = [asyncio.create_task(process_article(a)) for a in raw_articles]
        processed = await asyncio.gather(*tasks)

        structured = []
        for raw, ai in zip(raw_articles, processed):
            structured.append({
                "title": raw["title"],
                "summary": ai["summary"],
                "sentiment": f"{ai['sentiment'].capitalize()} {ai['emoji']}",
                "link": raw["link"],
            })

        results[name] = structured

    return results


async def gather_news_parallel(portfolio_items, watchlist_items):
    return await asyncio.gather(
        asyncio.create_task(analyze_news_for_items(portfolio_items)),
        asyncio.create_task(analyze_news_for_items(watchlist_items))
    )


# ---------------------------------------
# Telegram Block Builder
# ---------------------------------------
def build_telegram_blocks(date, pf, wl, news, overview):
    blocks = []

    # ==== PORTFOLIO ====
    pf_title = f"Portfolio ({date})"
    pf_content = "\n".join(
        f"{x['symbol']}: {x['change']} {x['emoji']}" for x in pf
    )
    blocks.append({
        "title": pf_title,
        "emoji": "📈",
        "content": pf_content
    })

    # ==== WATCHLIST ====
    wl_title = f"Watchlist ({date})"
    wl_content = "\n".join(
        f"{x['symbol']}: {x['change']} {x['emoji']}" for x in wl
    )
    blocks.append({
        "title": wl_title,
        "emoji": "👀",
        "content": wl_content
    })

    # ==== PORTFOLIO NEWS ====
    pf_news = ""
    for stock, items in news["portfolio"].items():
        pf_news += f"<b>{stock}:</b>\n"
        for n in items[:3]:
            pf_news += (
                f"- {n['summary']}\n"
                f"({n['sentiment']}) "
                f"<a href=\"{n['link']}\">hier nachlesen</a>\n"
            )
        pf_news += "\n"

    blocks.append({
        "title": "Portfolio-News",
        "emoji": "📰",
        "content": pf_news.strip()
    })

    # ==== WATCHLIST NEWS ====
    wl_news = ""
    for stock, items in news["watchlist"].items():
        wl_news += f"<b>{stock}:</b>\n"
        for n in items[:3]:
            wl_news += (
                f"- {n['summary']}\n"
                f"({n['sentiment']}) "
                f"<a href=\"{n['link']}\">hier nachlesen</a>\n"
            )
        wl_news += "\n"

    blocks.append({
        "title": "Watchlist-News",
        "emoji": "🗞️",
        "content": wl_news.strip()
    })

    # ==== MARKTANALYSE ====
    market_text = (
        f"<b>Makro:</b>\n{overview['macro']}\n\n"
        f"<b>Portfolio:</b>\n{overview['portfolio']}\n\n"
        f"<b>Fazit:</b>\n{overview['final']['emoji']} {overview['final']['text']}"
    )

    blocks.append({
        "title": "Marktanalyse",
        "emoji": "🌍",
        "content": market_text
    })

    return blocks


# ---------------------------------------
# Main Pipeline
# ---------------------------------------
def run_briefing_test(send_telegram=True):
    logger.info("📊 Starte Aktienbriefing…")

    settings = load_settings()
    pf_items = settings["portfolio"]
    wl_items = settings["watchlist"]

    # 1 PRICES
    logger.info("💹 Hole Kursdaten…")
    pf_data, date = get_price_changes(pf_items)
    wl_data, _ = get_price_changes(wl_items)

    # 2 NEWS
    logger.info("📰 Starte parallele News-Analyse…")
    news_pf, news_wl = asyncio.run(gather_news_parallel(pf_items, wl_items))

    all_summaries = [
        ai["summary"]
        for arr in news_pf.values()
        for ai in arr
    ]

    # 3 MARKET OVERVIEW
    logger.info("🌍 Erstelle Marktanalyse…")
    overview = generate_market_overview(pf_data, all_summaries)

    # Formatieren
    pf_fmt = [format_stock(s) for s in pf_data]
    wl_fmt = [format_stock(s) for s in wl_data]

    # Telegram-Blöcke
    if send_telegram:
        blocks = build_telegram_blocks(
            date, pf_fmt, wl_fmt,
            {"portfolio": news_pf, "watchlist": news_wl},
            overview
        )
        send_briefing_blocks(blocks)

    # Datei rendern
    render_report({
        "date": date,
        "portfolio": pf_fmt,
        "watchlist": wl_fmt,
        "news": {"portfolio": news_pf, "watchlist": news_wl},
        "overview": overview,
    })

    # Archivieren
    archive_report()

    logger.info("✅ Briefing abgeschlossen.")
    return True
