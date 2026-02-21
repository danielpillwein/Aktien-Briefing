import asyncio
from datetime import datetime
from typing import Any, Dict, List, Tuple

from loguru import logger

from config.settings_loader import load_settings
from core.async_ai import process_article
from core.fetch_news import fetch_all_sources
from core.fetch_prices import get_price_changes
from core.market_overview import generate_market_overview
from core.news_novelty import filter_news_by_novelty
from core.report_builder import render_report
from utils.archive_manager import archive_briefing
from utils.news_memory import (
    build_memory_entry,
    load_memory,
    prune_memory,
    record_sent_news,
    save_memory,
)
from utils.notifications import send_briefing_blocks


def _novelty_config(settings: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "enabled": True,
        "lookback_days": 14,
        "memory_retention_days": 90,
        "semantic_threshold": 0.86,
        "max_news_per_stock": 3,
        "min_news_per_stock": 0,
        "exact_url_dedupe": True,
        "exact_title_dedupe": True,
        "include_known_news_reason_in_report": True,
    }
    cfg = settings.get("novelty", {})
    return {**defaults, **cfg}


def _fallback_overview(date: str) -> Dict[str, Any]:
    return {
        "macro": f"Für den {date} liegen keine inhaltlich neuen News vor. Fokus heute auf Kursentwicklung und bestehende Trends.",
        "portfolio": "Es wurden keine neuen Themen gegenüber den letzten Briefings erkannt.",
        "final": {
            "text": "Neutral: Heute keine inhaltlich neuen Nachrichten.",
            "emoji": "🟡",
        },
    }


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


def _empty_stock_news_status(raw_count: int = 0) -> Dict[str, Any]:
    return {
        "has_new_news": False,
        "new_count": 0,
        "known_count": raw_count,
        "message_if_none": "Keine inhaltlich neuen News seit dem letzten Briefing.",
    }


# ---------------------------------------
# News-Analyse
# ---------------------------------------
async def analyze_news_for_items(
    items: List[Dict[str, Any]],
    memory: Dict[str, Any],
    novelty_cfg: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    results: Dict[str, Any] = {}
    pending_memory_entries: List[Dict[str, Any]] = []
    max_news = int(novelty_cfg.get("max_news_per_stock", 3))
    novelty_enabled = bool(novelty_cfg.get("enabled", True))

    for item in items:
        name = item["name"]
        logger.info(f"Hole News für {name}…")
        raw_articles = await fetch_all_sources(name)

        if not raw_articles:
            results[name] = {
                "items": [],
                "news_status": _empty_stock_news_status(0),
                "novelty_stats": {
                    "fetched": 0,
                    "exact_dupes": 0,
                    "semantic_dupes": 0,
                    "new_count": 0,
                },
                "suppressed_known_topics": [],
            }
            continue

        if novelty_enabled:
            novelty_result = await filter_news_by_novelty(
                name,
                raw_articles,
                memory,
                novelty_cfg,
            )
            candidate_articles = novelty_result["new_items"]
            suppressed_known_topics = novelty_result["suppressed_known_topics"]
            novelty_stats = novelty_result["stats"]
        else:
            candidate_articles = raw_articles
            suppressed_known_topics = []
            novelty_stats = {
                "fetched": len(raw_articles),
                "exact_dupes": 0,
                "semantic_dupes": 0,
                "new_count": len(raw_articles),
            }

        if max_news >= 0:
            candidate_articles = candidate_articles[:max_news]

        if not candidate_articles:
            results[name] = {
                "items": [],
                "news_status": _empty_stock_news_status(len(raw_articles)),
                "novelty_stats": novelty_stats,
                "suppressed_known_topics": suppressed_known_topics,
            }
            logger.info(
                f"{name}: fetched={novelty_stats['fetched']} "
                f"exact={novelty_stats['exact_dupes']} "
                f"semantic={novelty_stats['semantic_dupes']} new=0"
            )
            continue

        logger.info(f"Analysiere {len(candidate_articles)} neue Artikel für {name}…")
        tasks = [asyncio.create_task(process_article(article)) for article in candidate_articles]
        processed = await asyncio.gather(*tasks)

        structured = []
        for raw, ai in zip(candidate_articles, processed):
            structured.append(
                {
                    "title": raw["title"],
                    "summary": ai["summary"],
                    "sentiment": f"{ai['sentiment'].capitalize()} {ai['emoji']}",
                    "link": raw["link"],
                }
            )
            pending_memory_entries.append(
                build_memory_entry(
                    stock_name=name,
                    article=raw,
                    summary_text=ai["summary"],
                    topic_embedding=raw.get("_novelty_embedding") or [],
                )
            )

        results[name] = {
            "items": structured,
            "news_status": {
                "has_new_news": len(structured) > 0,
                "new_count": len(structured),
                "known_count": len(raw_articles) - len(structured),
                "message_if_none": "Keine inhaltlich neuen News seit dem letzten Briefing.",
            },
            "novelty_stats": novelty_stats,
            "suppressed_known_topics": suppressed_known_topics,
        }
        logger.info(
            f"{name}: fetched={novelty_stats['fetched']} "
            f"exact={novelty_stats['exact_dupes']} "
            f"semantic={novelty_stats['semantic_dupes']} new={len(structured)}"
        )

    return results, pending_memory_entries


async def gather_news_parallel(
    portfolio_items: List[Dict[str, Any]],
    watchlist_items: List[Dict[str, Any]],
    memory: Dict[str, Any],
    novelty_cfg: Dict[str, Any],
):
    return await asyncio.gather(
        asyncio.create_task(analyze_news_for_items(portfolio_items, memory, novelty_cfg)),
        asyncio.create_task(analyze_news_for_items(watchlist_items, memory, novelty_cfg)),
    )


def _news_section_to_text(section: Dict[str, Any], section_title: str) -> str:
    text = ""
    all_empty = True
    for stock, stock_data in section.items():
        text += f"<b>{stock}:</b>\n"
        items = stock_data.get("items", [])
        if items:
            all_empty = False
            for n in items:
                text += (
                    f"- {n['summary']}\n"
                    f"({n['sentiment']}) <a href=\"{n['link']}\">hier nachlesen</a>\n"
                )
        else:
            msg = stock_data.get("news_status", {}).get(
                "message_if_none",
                "Keine inhaltlich neuen News seit dem letzten Briefing.",
            )
            text += f"- {msg}\n"
        text += "\n"

    if all_empty:
        text += "Heute keine inhaltlich neuen Nachrichten im Beobachtungsuniversum."

    return text.strip()


def _collect_summaries(news_section: Dict[str, Any]) -> List[str]:
    summaries: List[str] = []
    for stock_data in news_section.values():
        for item in stock_data.get("items", []):
            summaries.append(item.get("summary", ""))
    return summaries


def _aggregate_novelty_stats(news_map: Dict[str, Any]) -> Dict[str, Any]:
    stats_by_stock = {}
    totals = {
        "fetched": 0,
        "exact_dupes": 0,
        "semantic_dupes": 0,
        "new_count": 0,
    }
    for stock, data in news_map.items():
        s = data.get("novelty_stats", {})
        stats_by_stock[stock] = s
        for key in totals:
            totals[key] += int(s.get(key, 0))

    return {
        "by_stock": stats_by_stock,
        "totals": totals,
    }


# ---------------------------------------
# Telegram Block Builder
# ---------------------------------------
def build_telegram_blocks(date, pf, wl, news, overview):
    blocks = []

    pf_content = "\n".join(f"{x['symbol']}: {x['change']} {x['emoji']}" for x in pf)
    blocks.append({"title": f"Portfolio ({date})", "emoji": "📈", "content": pf_content})

    wl_content = "\n".join(f"{x['symbol']}: {x['change']} {x['emoji']}" for x in wl)
    blocks.append({"title": f"Watchlist ({date})", "emoji": "👀", "content": wl_content})

    pf_news = _news_section_to_text(news["portfolio"], "Portfolio-News")
    blocks.append({"title": "Portfolio-News", "emoji": "📰", "content": pf_news})

    wl_news = _news_section_to_text(news["watchlist"], "Watchlist-News")
    blocks.append({"title": "Watchlist-News", "emoji": "🗞️", "content": wl_news})

    market_text = (
        f"<b>Makro:</b>\n{overview['macro']}\n\n"
        f"<b>Portfolio:</b>\n{overview['portfolio']}\n\n"
        f"<b>Fazit:</b>\n{overview['final']['emoji']} {overview['final']['text']}"
    )
    blocks.append({"title": "Marktanalyse", "emoji": "🌍", "content": market_text})

    return blocks


def _persist_memory_updates(memory: Dict[str, Any], pending_entries: List[Dict[str, Any]], novelty_cfg: Dict[str, Any]):
    if not novelty_cfg.get("enabled", True):
        return
    if not pending_entries:
        return

    memory = record_sent_news(memory, pending_entries)
    memory = prune_memory(memory, int(novelty_cfg.get("memory_retention_days", 90)))
    save_memory(memory)
    logger.info(f"News-Memory aktualisiert: {len(pending_entries)} neue Themen gespeichert.")


def prepare_briefing_payload() -> Dict[str, Any]:
    settings = load_settings()
    novelty_cfg = _novelty_config(settings)

    memory = load_memory()
    memory = prune_memory(memory, int(novelty_cfg.get("memory_retention_days", 90)))

    pf_items = settings["portfolio"]
    wl_items = settings["watchlist"]

    logger.info("💹 Hole Kursdaten…")
    pf_data, date = get_price_changes(pf_items)
    wl_data, _ = get_price_changes(wl_items)

    logger.info("📰 Starte parallele News-Analyse…")
    (news_pf, pending_pf), (news_wl, pending_wl) = asyncio.run(
        gather_news_parallel(pf_items, wl_items, memory, novelty_cfg)
    )

    all_summaries = _collect_summaries(news_pf)
    all_summaries.extend(_collect_summaries(news_wl))

    logger.info("🌍 Erstelle Marktanalyse…")
    if all_summaries:
        overview = generate_market_overview(pf_data, all_summaries)
    else:
        overview = _fallback_overview(date)

    pf_fmt = [format_stock(s) for s in pf_data]
    wl_fmt = [format_stock(s) for s in wl_data]

    news_bundle = {"portfolio": news_pf, "watchlist": news_wl}
    blocks = build_telegram_blocks(date, pf_fmt, wl_fmt, news_bundle, overview)
    pending_memory_entries = pending_pf + pending_wl

    novelty_stats = {
        "portfolio": _aggregate_novelty_stats(news_pf),
        "watchlist": _aggregate_novelty_stats(news_wl),
    }

    suppressed_known_topics = {
        "portfolio": {stock: v.get("suppressed_known_topics", []) for stock, v in news_pf.items()},
        "watchlist": {stock: v.get("suppressed_known_topics", []) for stock, v in news_wl.items()},
    }

    report_data = {
        "date": date,
        "portfolio": pf_fmt,
        "watchlist": wl_fmt,
        "news": news_bundle,
        "overview": overview,
        "novelty_stats": novelty_stats,
    }

    archive_entry = {
        "date": date,
        "portfolio": pf_fmt,
        "watchlist": wl_fmt,
        "news": news_bundle,
        "market_overview": overview,
        "novelty_stats": novelty_stats,
        "version": "1.1.0",
    }

    if novelty_cfg.get("include_known_news_reason_in_report", True):
        archive_entry["suppressed_known_topics"] = suppressed_known_topics
        report_data["suppressed_known_topics"] = suppressed_known_topics

    return {
        "date": date,
        "blocks": blocks,
        "report_data": report_data,
        "archive_entry": archive_entry,
        "pending_memory_entries": pending_memory_entries,
        "memory": memory,
        "novelty_cfg": novelty_cfg,
    }


def persist_prepared_memory(payload: Dict[str, Any]):
    _persist_memory_updates(
        payload.get("memory", {}),
        payload.get("pending_memory_entries", []),
        payload.get("novelty_cfg", {}),
    )


# ---------------------------------------
# Main Pipeline
# ---------------------------------------
def run_briefing_test(send_telegram=True):
    logger.info("📊 Starte Aktienbriefing…")
    payload = prepare_briefing_payload()

    if send_telegram:
        send_briefing_blocks(payload["blocks"])
        persist_prepared_memory(payload)

    render_report(payload["report_data"])
    archive_briefing(payload["archive_entry"])

    logger.info("✅ Briefing abgeschlossen.")
    return True
