import asyncio
from datetime import datetime
import re
from typing import Any, Dict, List, Tuple

from loguru import logger

from config.settings_loader import load_settings
from core.async_ai import process_article
from core.fetch_news import fetch_all_sources
from core.fetch_prices import get_price_changes
from core.interpretation import build_stock_interpretation
from core.macro_linker import build_macro_overview
from core.news_novelty import filter_news_by_novelty
from core.news_ranking import rank_articles_for_stock
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


def _ranking_config(settings: Dict[str, Any], novelty_cfg: Dict[str, Any]) -> Dict[str, Any]:
    defaults = {
        "min_relevance_score": 35.0,
        "max_candidates_per_stock": 8,
        "top_news_per_stock": int(novelty_cfg.get("max_news_per_stock", 3)),
        "weights": {
            "recency": 0.35,
            "entity": 0.25,
            "source_quality": 0.2,
            "information_density": 0.1,
            "macro_signal": 0.1,
        },
    }
    cfg = settings.get("ranking", {})
    merged = {**defaults, **cfg}
    merged["weights"] = {**defaults["weights"], **cfg.get("weights", {})}
    return merged


def format_stock(s):
    try:
        change = float(s.change_percent)

        if change > 0.3:
            emoji = "🟢"
        elif change < -0.3:
            emoji = "🔴"
        else:
            emoji = "🟡"

        since_watchlist = getattr(s, "since_watchlist_percent", None)
        watchlist_added_at = str(getattr(s, "watchlist_added_at", "") or "").strip()
        since_watchlist_text = ""
        if since_watchlist is not None:
            try:
                short_date = ""
                if watchlist_added_at:
                    try:
                        dt = datetime.fromisoformat(watchlist_added_at.replace("Z", ""))
                        short_date = dt.strftime("%d.%m")
                    except Exception:
                        short_date = ""
                since_watchlist_text = f"{float(since_watchlist):+.2f}%"
                if short_date:
                    since_watchlist_text += f" ({short_date})"
            except Exception:
                since_watchlist_text = ""

        return {
            "symbol": getattr(s, "symbol", "Unknown"),
            "ticker": getattr(s, "ticker", ""),
            "change": f"{change:+.2f}%",
            "emoji": emoji,
            "since_watchlist": since_watchlist_text,
        }
    except Exception as e:
        logger.error(f"FormatStock Fehler: {e}")
        return {
            "symbol": getattr(s, "symbol", "Unknown"),
            "ticker": getattr(s, "ticker", ""),
            "change": "0.00%",
            "emoji": "🟡",
            "since_watchlist": "",
        }


def _empty_stock_news_status(raw_count: int = 0) -> Dict[str, Any]:
    return {
        "has_new_news": False,
        "new_count": 0,
        "known_count": raw_count,
        "message_if_none": "Keine inhaltlich neuen News seit dem letzten Briefing.",
    }


def _price_map(formatted_prices: List[Dict[str, Any]]) -> Dict[str, str]:
    return {str(x["symbol"]): str(x["change"]) for x in formatted_prices}


def _build_signal_item(
    stock_name: str,
    list_name: str,
    article: Dict[str, Any],
    signal: Dict[str, Any],
) -> Dict[str, Any]:
    relevance = signal.get("relevance_score", article.get("relevance_score", 0))
    out = dict(signal)
    out.update(
        {
            "stock_name": stock_name,
            "list_name": list_name,
            "title": article.get("title", ""),
            "link": article.get("link", ""),
            "source_name": article.get("source_name", ""),
            "source_url": article.get("source_url", ""),
            "published_at": article.get("published_at", ""),
            "relevance_score": int(round(float(relevance))),
            "portfolio_exposure": {
                "in_portfolio": list_name == "portfolio",
                "in_watchlist": list_name == "watchlist",
            },
        }
    )
    return out


def _fallback_novelty_stats(fetched_count: int) -> Dict[str, Any]:
    return {
        "fetched": fetched_count,
        "exact_dupes": 0,
        "semantic_dupes": 0,
        "new_count": fetched_count,
        "candidate_count": fetched_count,
        "ranked_count": fetched_count,
        "analyzed_count": 0,
    }


async def _analyze_single_stock(
    item: Dict[str, Any],
    memory: Dict[str, Any],
    novelty_cfg: Dict[str, Any],
    ranking_cfg: Dict[str, Any],
    list_name: str,
    price_change_map: Dict[str, str],
) -> Tuple[str, Dict[str, Any], List[Dict[str, Any]]]:
    stock_name = item["name"]
    logger.info(f"Hole News für {stock_name}…")
    raw_articles = await fetch_all_sources(stock_name)

    if not raw_articles:
        interpretation = build_stock_interpretation(stock_name, price_change_map.get(stock_name, "0.00%"), [])
        return (
            stock_name,
            {
                "items": [],
                "interpretation": interpretation,
                "news_status": _empty_stock_news_status(0),
                "novelty_stats": _fallback_novelty_stats(0),
                "suppressed_known_topics": [],
            },
            [],
        )

    novelty_enabled = bool(novelty_cfg.get("enabled", True))
    if novelty_enabled:
        novelty_result = await filter_news_by_novelty(stock_name, raw_articles, memory, novelty_cfg)
        candidate_articles = novelty_result["new_items"]
        suppressed_known_topics = novelty_result["suppressed_known_topics"]
        novelty_stats = novelty_result["stats"]
    else:
        candidate_articles = raw_articles
        suppressed_known_topics = []
        novelty_stats = _fallback_novelty_stats(len(raw_articles))

    ranked_candidates = rank_articles_for_stock(stock_name, candidate_articles, ranking_cfg)
    top_n = max(0, int(ranking_cfg.get("top_news_per_stock", novelty_cfg.get("max_news_per_stock", 3))))
    selected_articles = ranked_candidates[:top_n] if top_n > 0 else []

    novelty_stats = {
        **novelty_stats,
        "candidate_count": len(candidate_articles),
        "ranked_count": len(ranked_candidates),
        "analyzed_count": len(selected_articles),
    }

    if not selected_articles:
        interpretation = build_stock_interpretation(
            stock_name,
            price_change_map.get(stock_name, "0.00%"),
            [],
        )
        logger.info(
            f"{stock_name}: fetched={novelty_stats['fetched']} "
            f"candidates={novelty_stats['candidate_count']} ranked={novelty_stats['ranked_count']} analyzed=0"
        )
        return (
            stock_name,
            {
                "items": [],
                "interpretation": interpretation,
                "news_status": _empty_stock_news_status(len(raw_articles)),
                "novelty_stats": novelty_stats,
                "suppressed_known_topics": suppressed_known_topics,
            },
            [],
        )

    logger.info(f"Analysiere {len(selected_articles)} Top-Artikel kausal für {stock_name}…")
    tasks = [asyncio.create_task(process_article(article, stock_name=stock_name)) for article in selected_articles]
    analyzed = await asyncio.gather(*tasks)

    items: List[Dict[str, Any]] = []
    pending_entries: List[Dict[str, Any]] = []
    for article, signal in zip(selected_articles, analyzed):
        signal_item = _build_signal_item(stock_name, list_name, article, signal)
        items.append(signal_item)
        pending_entries.append(
            build_memory_entry(
                stock_name=stock_name,
                article=article,
                summary_text=signal_item.get("causal_chain", signal_item.get("stock_specific_impact", "")),
                topic_embedding=article.get("_novelty_embedding") or [],
            )
        )

    interpretation = build_stock_interpretation(stock_name, price_change_map.get(stock_name, "0.00%"), items)
    result = {
        "items": items,
        "interpretation": interpretation,
        "news_status": {
            "has_new_news": len(items) > 0,
            "new_count": len(items),
            "known_count": max(0, len(raw_articles) - len(items)),
            "message_if_none": "Keine inhaltlich neuen News seit dem letzten Briefing.",
        },
        "novelty_stats": novelty_stats,
        "suppressed_known_topics": suppressed_known_topics,
    }

    logger.info(
        f"{stock_name}: fetched={novelty_stats['fetched']} "
        f"candidates={novelty_stats['candidate_count']} "
        f"ranked={novelty_stats['ranked_count']} analyzed={novelty_stats['analyzed_count']}"
    )
    return stock_name, result, pending_entries


async def analyze_news_for_items(
    items: List[Dict[str, Any]],
    memory: Dict[str, Any],
    novelty_cfg: Dict[str, Any],
    ranking_cfg: Dict[str, Any],
    list_name: str,
    price_change_map: Dict[str, str],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if not items:
        return {}, []

    tasks = [
        asyncio.create_task(
            _analyze_single_stock(
                item=item,
                memory=memory,
                novelty_cfg=novelty_cfg,
                ranking_cfg=ranking_cfg,
                list_name=list_name,
                price_change_map=price_change_map,
            )
        )
        for item in items
    ]
    results = await asyncio.gather(*tasks)

    news_map: Dict[str, Any] = {}
    pending: List[Dict[str, Any]] = []
    for stock_name, data, mem_entries in results:
        news_map[stock_name] = data
        pending.extend(mem_entries)
    return news_map, pending


async def gather_news_parallel(
    portfolio_items: List[Dict[str, Any]],
    watchlist_items: List[Dict[str, Any]],
    memory: Dict[str, Any],
    novelty_cfg: Dict[str, Any],
    ranking_cfg: Dict[str, Any],
    price_change_map: Dict[str, str],
):
    return await asyncio.gather(
        asyncio.create_task(
            analyze_news_for_items(
                portfolio_items, memory, novelty_cfg, ranking_cfg, "portfolio", price_change_map
            )
        ),
        asyncio.create_task(
            analyze_news_for_items(
                watchlist_items, memory, novelty_cfg, ranking_cfg, "watchlist", price_change_map
            )
        ),
    )


def _news_section_to_text(section: Dict[str, Any]) -> str:
    def _clean_fragment(text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        return cleaned.rstrip(" .;:!?,")

    def _de_floskel(text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"\b(könnte|dürfte|wahrscheinlich|tendenziell)\b", "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.split())

    def _finalize_sentence(text: str, max_words: int = 0) -> str:
        out = " ".join(str(text or "").replace("...", ".").split()).strip()
        out = out.rstrip(" .;:!?,")
        if max_words > 0:
            words = out.split()
            if len(words) > max_words:
                out = " ".join(words[:max_words]).rstrip(" .;:!?,")
        dangling = (" was", " weil", " sodass", " sodass", " dies führt zu", " und", " oder", " dass")
        lower = out.lower()
        if any(lower.endswith(x) for x in dangling):
            out = out.rsplit(" ", 1)[0].rstrip(" .;:!?,")
        if not out:
            return "Keine belastbare Aussage verfügbar."
        return out + "."

    def _dedupe_key(item: Dict[str, Any]) -> str:
        event = _clean_fragment(_concrete_event(item)).lower()
        impact = _clean_fragment(
            item.get("stock_specific_impact", "") or item.get("direct_effect", "") or item.get("market_reaction", "")
        ).lower()
        raw = f"{event} {impact}"
        raw = re.sub(r"[^a-z0-9äöüß ]", " ", raw)
        return " ".join(raw.split())[:120]

    def _event_type_priority(event_type: str) -> int:
        et = str(event_type or "").lower()
        if et in {"geopolitical", "macro", "policy", "commodity"}:
            return 0
        if et in {"sector"}:
            return 1
        if et in {"earnings", "guidance", "company"}:
            return 2
        return 3

    def _driver_sort_key(item: Dict[str, Any]):
        return (
            _event_type_priority(item.get("event_type", "")),
            -(float(item.get("impact_score", 0)) * 0.6 + float(item.get("relevance_score", 0)) * 0.4),
        )

    def _is_generic_event(text: str) -> bool:
        lower = str(text or "").strip().lower()
        if not lower:
            return True
        if lower.startswith(("laut ", "bericht", "meldung", "news:")):
            return True
        generic_markers = (
            "marktstimmung",
            "optimismus",
            "pessimismus",
            "unsicherheit",
            "sorgen",
            "volatilität",
            "anleger",
            "märkte steigen",
            "märkte fallen",
            "aktie steigt",
            "aktie fällt",
            "kurs steigt",
            "kurs fällt",
            "risikoappetit",
            "risk-on",
            "risk-off",
            "erwartungen",
        )
        return any(marker in lower for marker in generic_markers)

    def _concrete_event(item: Dict[str, Any]) -> str:
        event = str(item.get("event", "")).strip()
        title = str(item.get("title", "")).strip()
        # Regel: Bullet muss mit einem konkreten, nachprüfbaren Event beginnen.
        if event and not _is_generic_event(event):
            return event
        if title:
            return title
        return event or "Konkretes Ereignis nicht eindeutig genannt"

    def _compact_signal_text(item: Dict[str, Any]) -> str:
        event = _de_floskel(_clean_fragment(_concrete_event(item)))
        direct = _de_floskel(_clean_fragment(item.get("direct_effect", "")))
        stock = _de_floskel(_clean_fragment(item.get("stock_specific_impact", "")))
        market = _de_floskel(_clean_fragment(item.get("market_reaction", "")))

        # Ziel: sehr kompakt (1 kurzer Satz), Event zuerst, ohne Doppelpunkt.
        if stock:
            text = f"{event}, {stock}"
        elif direct:
            text = f"{event}, {direct}"
        elif market:
            text = f"{event}, {market}"
        else:
            text = str(item.get("causal_chain", "")).strip() or "Kein klarer Grund ableitbar."
        return _finalize_sentence(_de_floskel(text))

    def _sentiment_label(sentiment: str) -> str:
        raw = str(sentiment or "").lower().strip()
        if raw == "positiv":
            return "Positiv"
        if raw == "negativ":
            return "Negativ"
        return "Neutral"

    text = ""
    all_empty = True
    for stock, stock_data in section.items():
        text += f"<b>{stock}</b>\n"
        items = stock_data.get("items", [])
        if not items:
            msg = stock_data.get("news_status", {}).get(
                "message_if_none",
                "Keine inhaltlich neuen News seit dem letzten Briefing.",
            )
            text += f"- {msg}\n\n"
            continue

        all_empty = False
        ranked_items = sorted(items, key=_driver_sort_key)
        unique_items: List[Dict[str, Any]] = []
        seen = set()
        for it in ranked_items:
            key = _dedupe_key(it)
            if not key or key in seen:
                continue
            seen.add(key)
            unique_items.append(it)
            if len(unique_items) >= 3:
                break
        ranked_items = unique_items
        if not ranked_items:
            text += "- Keine klaren neuen Aussagen.\n\n"
            continue

        first = ranked_items[0]
        first_text = _finalize_sentence(_compact_signal_text(first), max_words=15)
        first_sentiment = _sentiment_label(first.get("sentiment", "neutral"))
        first_emoji = first.get("emoji", "🟡")
        first_link = str(first.get("link", "")).strip()
        text += (
            "🔥 <b>Wichtigster Grund</b>\n"
            f"{first_text}\n"
            f"<i>({first_sentiment} {first_emoji})</i> <a href=\"{first_link}\">hier nachlesen</a>\n"
        )

        for source in ranked_items[1:]:
            compact = _finalize_sentence(_compact_signal_text(source))
            sentiment = _sentiment_label(source.get("sentiment", "neutral"))
            emoji = source.get("emoji", "🟡")
            link = str(source.get("link", "")).strip()
            text += (
                f"• {compact}\n"
                f"  <i>({sentiment} {emoji})</i> <a href=\"{link}\">hier nachlesen</a>\n"
            )
        text += "\n"

    if all_empty:
        text += "Heute keine inhaltlich neuen Nachrichten im Beobachtungsuniversum."
    return text.strip()


def _macro_section_to_text(macro_overview: Dict[str, Any]) -> str:
    def _clean_fragment(text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        return cleaned.rstrip(" .;:!?,")

    def _de_floskel(text: str) -> str:
        cleaned = str(text or "")
        cleaned = re.sub(r"\b(könnte|dürfte|wahrscheinlich|tendenziell)\b", "", cleaned, flags=re.IGNORECASE)
        return " ".join(cleaned.split())

    def _finalize_sentence(text: str) -> str:
        out = " ".join(str(text or "").replace("...", ".").split()).strip()
        out = out.rstrip(" .;:!?,")
        dangling = (" was", " weil", " sodass", " dies führt zu", " und", " oder", " dass")
        lower = out.lower()
        if any(lower.endswith(x) for x in dangling):
            out = out.rsplit(" ", 1)[0].rstrip(" .;:!?,")
        if not out:
            return "Keine belastbare Aussage verfügbar."
        return out + "."

    def _is_generic_factor(text: str) -> bool:
        lower = str(text or "").strip().lower()
        if not lower:
            return True
        generic_markers = (
            "makro",
            "marktstimmung",
            "risiko",
            "unsicherheit",
            "märkte steigen",
            "märkte fallen",
        )
        return any(marker in lower for marker in generic_markers)

    def _macro_sentiment_label_and_emoji(factor: Dict[str, Any]) -> tuple[str, str]:
        reaction = " ".join(
            [
                str(factor.get("market_reaction", "")),
                str(factor.get("macro_impact", "")),
                str(factor.get("mechanism", "")),
            ]
        ).lower()
        negative_markers = ("fällt", "abverkauf", "risk-off", "druck", "belast", "steigt inflation", "zins steigt")
        positive_markers = ("steigt", "erholt", "risk-on", "entlast", "sinkt inflation", "zins sinkt")
        if any(m in reaction for m in negative_markers):
            return "Negativ", "🔴"
        if any(m in reaction for m in positive_markers):
            return "Positiv", "🟢"
        return "Neutral", "🟡"

    def _macro_interpretation_sentence(
        factor: Dict[str, Any],
        event: str,
        mechanism: str,
        market_reaction: str,
        macro_impact: str,
    ) -> str:
        et = str(factor.get("event_type", "other")).lower()
        joined = " ".join([event, mechanism, macro_impact, market_reaction]).lower()
        holdings = factor.get("affected_holdings", []) or []
        holding_tail = ""
        if holdings:
            top = ", ".join(holdings[:2])
            holding_tail = f" und belastet {top}"

        if et in {"geopolitical", "policy"}:
            if any(k in joined for k in ("iran", "israel", "ukraine", "russia", "krieg", "konflikt", "sanktion")):
                if any(k in joined for k in ("öl", "oil", "gas", "energie")):
                    return f"{event}, das erhöht Energie- und Inflationsdruck{holding_tail}"
                return f"{event}, das erhöht das Risiko im Gesamtmarkt{holding_tail}"
            if any(k in joined for k in ("zoll", "tariff", "handelskonflikt", "trade")):
                return f"{event}, das erhöht Kosten und bremst Nachfrage{holding_tail}"

        if any(k in joined for k in ("zins", "rate", "yield")):
            return f"{event}, das verschärft Finanzierungsdruck und belastet Bewertung{holding_tail}"
        if any(k in joined for k in ("inflation", "preise", "price")):
            return f"{event}, das erhöht Margendruck und reduziert Kaufkraft{holding_tail}"
        if market_reaction:
            return f"{event}, {market_reaction}{holding_tail}"
        if mechanism:
            return f"{event}, {mechanism}{holding_tail}"
        if macro_impact:
            return f"{event}, {macro_impact}{holding_tail}"
        return event

    factors = macro_overview.get("factors", [])
    if not factors:
        return macro_overview.get("summary", "Keine dominanten neuen Marktfaktoren erkannt.")

    lines = []
    for factor in factors[:3]:
        event = _de_floskel(_clean_fragment(factor.get("factor", "")))
        mechanism = _de_floskel(_clean_fragment(factor.get("mechanism", "")))
        market_reaction = _de_floskel(_clean_fragment(factor.get("market_reaction", "")))
        macro_impact = _de_floskel(_clean_fragment(factor.get("macro_impact", "")))
        if _is_generic_factor(event):
            event = macro_impact or "Makroevent nicht eindeutig benannt"

        compact = _macro_interpretation_sentence(
            factor=factor,
            event=event,
            mechanism=mechanism,
            market_reaction=market_reaction,
            macro_impact=macro_impact,
        )
        compact = _finalize_sentence(_de_floskel(compact))

        source_links = factor.get("sources", []) or []
        source_url = str(source_links[0]).strip() if source_links else ""
        source_part = f' <a href="{source_url}">hier nachlesen</a>' if source_url else ""
        sentiment, emoji = _macro_sentiment_label_and_emoji(factor)
        lines.append(
            f"• {compact}\n"
            f"  <i>({sentiment} {emoji})</i>{source_part}"
        )
    return "\n".join(lines).strip()


def _aggregate_novelty_stats(news_map: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "fetched",
        "exact_dupes",
        "semantic_dupes",
        "new_count",
        "candidate_count",
        "ranked_count",
        "analyzed_count",
    ]
    totals = {k: 0 for k in keys}
    by_stock = {}

    for stock, data in news_map.items():
        stats = data.get("novelty_stats", {})
        by_stock[stock] = stats
        for key in keys:
            totals[key] += int(stats.get(key, 0))
    return {"by_stock": by_stock, "totals": totals}


def build_telegram_blocks(date, pf, wl, news, macro_overview):
    blocks = []
    pf_content = "\n".join(f"{x['symbol']} {x['change']} {x['emoji']}" for x in pf)
    blocks.append({"title": f"Deine Aktien ({date})", "emoji": "🧠", "content": pf_content})

    wl_lines = []
    for x in wl:
        line = f"{x['symbol']} {x['change']} {x['emoji']}"
        if x.get("since_watchlist"):
            line += f" | {x['since_watchlist']}"
        wl_lines.append(line)
    wl_content = "\n".join(wl_lines)
    blocks.append({"title": f"Beobachtung ({date})", "emoji": "👀", "content": wl_content})

    blocks.append({"title": "🧠 Portfolio-Analyse", "emoji": "", "content": _news_section_to_text(news["portfolio"])})
    blocks.append({"title": "👀 Watchlist-Analyse", "emoji": "", "content": _news_section_to_text(news["watchlist"])})
    blocks.append({"title": "🌍 Marktumfeld", "emoji": "", "content": _macro_section_to_text(macro_overview)})
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
    ranking_cfg = _ranking_config(settings, novelty_cfg)

    memory = load_memory()
    memory = prune_memory(memory, int(novelty_cfg.get("memory_retention_days", 90)))

    pf_items = settings["portfolio"]
    wl_items = settings["watchlist"]

    logger.info("💹 Hole Kursdaten…")
    pf_data, date = get_price_changes(pf_items)
    wl_data, _ = get_price_changes(wl_items)
    pf_fmt = [format_stock(s) for s in pf_data]
    wl_fmt = [format_stock(s) for s in wl_data]
    change_map = _price_map(pf_fmt + wl_fmt)

    logger.info("📰 Starte News-Pipeline (Fetch -> Ranking -> Analyse)…")
    (news_pf, pending_pf), (news_wl, pending_wl) = asyncio.run(
        gather_news_parallel(
            portfolio_items=pf_items,
            watchlist_items=wl_items,
            memory=memory,
            novelty_cfg=novelty_cfg,
            ranking_cfg=ranking_cfg,
            price_change_map=change_map,
        )
    )

    news_bundle = {"portfolio": news_pf, "watchlist": news_wl}
    macro_overview = build_macro_overview(pf_items, wl_items, news_bundle)

    blocks = build_telegram_blocks(date, pf_fmt, wl_fmt, news_bundle, macro_overview)
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
        "macro_overview": macro_overview,
        "novelty_stats": novelty_stats,
        "ranking_config": ranking_cfg,
    }

    archive_entry = {
        "date": date,
        "portfolio": pf_fmt,
        "watchlist": wl_fmt,
        "news": news_bundle,
        "macro_overview": macro_overview,
        "novelty_stats": novelty_stats,
        "ranking_config": ranking_cfg,
        "version": "2.0.0",
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
