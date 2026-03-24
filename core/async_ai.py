import asyncio
import hashlib
import json
import os
import re
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

from utils.cache import get_cache, set_cache
from utils.preprocess import clean_text
from utils.prompt_loader import load_prompt

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_client = None
_client_loop = None

MAX_CONCURRENT_OPENAI_CALLS = 5
_semaphore = None
_semaphore_loop = None

SENTIMENT_TO_EMOJI = {
    "positiv": "🟢",
    "neutral": "🟡",
    "negativ": "🔴",
}

ALLOWED_EVENT_TYPES = {
    "geopolitical",
    "macro",
    "policy",
    "commodity",
    "earnings",
    "guidance",
    "company",
    "sector",
    "other",
}
ALLOWED_SENTIMENTS = {"positiv", "neutral", "negativ"}
ALLOWED_HORIZONS = {"short", "medium", "long"}
ALLOWED_CONFIDENCE = {"low", "medium", "high"}

DEFAULT_SIGNAL = {
    "event": "Kein klarer Treiber erkannt",
    "event_type": "other",
    "direct_effect": "Direkter wirtschaftlicher Mechanismus unklar.",
    "macro_impact": "Makroeffekt im Artikel nicht belastbar beschrieben.",
    "market_reaction": "Marktreaktion bleibt unklar.",
    "affected_sectors": [],
    "stock_specific_impact": "Aktienspezifische Wirkung nicht eindeutig ableitbar.",
    "sentiment": "neutral",
    "sentiment_reason": "Unzureichende Evidenz für klare positive oder negative Dominanz.",
    "time_horizon": "short",
    "confidence": "low",
    "relevance_score": 30,
    "impact_score": 30,
    "causal_chain": "",
    "emoji": "🟡",
}


def _get_client() -> AsyncOpenAI:
    global _client, _client_loop
    current_loop = asyncio.get_running_loop()

    if _client is None or _client_loop is not current_loop:
        _client = AsyncOpenAI(api_key=OPENAI_API_KEY)
        _client_loop = current_loop

    return _client


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore, _semaphore_loop
    current_loop = asyncio.get_running_loop()

    if _semaphore is None or _semaphore_loop is not current_loop:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_OPENAI_CALLS)
        _semaphore_loop = current_loop

    return _semaphore


def _build_prompt(article: Dict[str, Any], stock_name: str) -> str:
    prompt = load_prompt("article_signal")
    mapping = {
        "stock_name": stock_name or article.get("stock_name", "") or "Unbekannt",
        "source_name": str(article.get("source_name", "")),
        "published_at": str(article.get("published_at", "")),
        "article_title": str(article.get("title", "")),
        "article_text": str(article.get("content", "")),
    }
    for key, value in mapping.items():
        prompt = prompt.replace(f"{{{key}}}", value)
    return prompt


def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s*```$", "", candidate)

    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    clipped = candidate[start : end + 1]
    try:
        data = json.loads(clipped)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _norm_choice(raw: Any, allowed: set, default: str, aliases: Optional[Dict[str, str]] = None) -> str:
    value = str(raw or "").strip().lower()
    if aliases and value in aliases:
        value = aliases[value]
    return value if value in allowed else default


def _norm_score(raw: Any, default: int = 30) -> int:
    try:
        score = int(round(float(raw)))
        return max(0, min(100, score))
    except Exception:
        return default


def _norm_sectors(raw: Any) -> list:
    if isinstance(raw, list):
        vals = [str(x).strip() for x in raw if str(x).strip()]
    elif isinstance(raw, str):
        vals = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        vals = []

    deduped = []
    seen = set()
    for val in vals:
        key = val.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(val)
    return deduped[:8]


def _normalize_signal(payload: Optional[Dict[str, Any]], article: Dict[str, Any]) -> Dict[str, Any]:
    p = payload or {}
    sentiment_aliases = {
        "positive": "positiv",
        "negative": "negativ",
        "neg": "negativ",
        "pos": "positiv",
    }

    sentiment = _norm_choice(p.get("sentiment"), ALLOWED_SENTIMENTS, "neutral", sentiment_aliases)
    confidence = _norm_choice(p.get("confidence"), ALLOWED_CONFIDENCE, "low")
    event_type = _norm_choice(p.get("event_type"), ALLOWED_EVENT_TYPES, "other")
    horizon = _norm_choice(p.get("time_horizon"), ALLOWED_HORIZONS, "short")

    event = str(p.get("event") or article.get("title") or DEFAULT_SIGNAL["event"]).strip()
    direct_effect = str(p.get("direct_effect") or DEFAULT_SIGNAL["direct_effect"]).strip()
    macro_impact = str(p.get("macro_impact") or DEFAULT_SIGNAL["macro_impact"]).strip()
    market_reaction = str(p.get("market_reaction") or DEFAULT_SIGNAL["market_reaction"]).strip()
    stock_impact = str(p.get("stock_specific_impact") or DEFAULT_SIGNAL["stock_specific_impact"]).strip()
    sentiment_reason = str(p.get("sentiment_reason") or DEFAULT_SIGNAL["sentiment_reason"]).strip()
    affected_sectors = _norm_sectors(p.get("affected_sectors"))
    relevance_score = _norm_score(p.get("relevance_score"), default=30)
    impact_score = _norm_score(p.get("impact_score"), default=30)

    chain = f"{event} -> {direct_effect} -> {market_reaction} -> {stock_impact}"
    return {
        "event": event[:260],
        "event_type": event_type,
        "direct_effect": direct_effect[:500],
        "macro_impact": macro_impact[:500],
        "market_reaction": market_reaction[:500],
        "affected_sectors": affected_sectors,
        "stock_specific_impact": stock_impact[:500],
        "sentiment": sentiment,
        "sentiment_reason": sentiment_reason[:500],
        "time_horizon": horizon,
        "confidence": confidence,
        "relevance_score": relevance_score,
        "impact_score": impact_score,
        "causal_chain": chain[:1200],
        "emoji": SENTIMENT_TO_EMOJI.get(sentiment, "🟡"),
    }


def _cache_key(article: Dict[str, Any], stock_name: str) -> str:
    raw_key = "|".join(
        [
            str(stock_name or ""),
            str(article.get("link", "")),
            str(article.get("title", "")),
            str(article.get("published_at", "")),
        ]
    )
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"signal::{digest}"


async def _extract_signal(article: Dict[str, Any], stock_name: str) -> Dict[str, Any]:
    prompt = _build_prompt(article, stock_name)
    response = await _get_client().responses.create(
        model="gpt-4.1-mini",
        input=prompt,
    )
    payload = _extract_json_payload(response.output_text.strip())
    signal = _normalize_signal(payload, article)
    if not payload:
        logger.warning("Konnte kein valides JSON aus LLM-Antwort lesen, nutze normalisierten Fallback.")
    return signal


async def _process_internal(article: Dict[str, Any], stock_name: str) -> Dict[str, Any]:
    key = _cache_key(article, stock_name)
    cached = get_cache(key)
    if isinstance(cached, dict) and cached.get("event"):
        return cached

    article_for_ai = dict(article)
    article_for_ai["content"] = clean_text(str(article.get("content", "")))
    signal = await _extract_signal(article_for_ai, stock_name)
    set_cache(key, signal)
    return signal


async def process_article(article: Dict[str, Any], stock_name: str = "") -> Dict[str, Any]:
    async with _get_semaphore():
        try:
            return await _process_internal(article, stock_name)
        except Exception as exc:
            logger.error(f"Fehler bei Artikel-Analyse: {exc}")
            fallback = dict(DEFAULT_SIGNAL)
            fallback["event"] = str(article.get("title") or DEFAULT_SIGNAL["event"])
            fallback["causal_chain"] = (
                f"{fallback['event']} -> {fallback['direct_effect']} -> "
                f"{fallback['market_reaction']} -> {fallback['stock_specific_impact']}"
            )
            return fallback
