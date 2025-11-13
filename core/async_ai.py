import asyncio
import random
from openai import AsyncOpenAI
from loguru import logger
from utils.cache import load_cache, save_cache, get_cached_result, set_cached_result
import yaml
from pathlib import Path

client = AsyncOpenAI()
with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)
perf = settings.get("performance", {})
CACHE_ENABLED = perf.get("cache_enabled", True)
RETRIES = perf.get("retries", 3)
MAX_TASKS = perf.get("max_concurrent_tasks", 5)

cache = load_cache()


async def async_summarize(title: str, semaphore: asyncio.Semaphore):
    """Fasst Artikel mit GPT asynchron zusammen (mit Cache & Retry)."""
    cache_key = f"summary::{title.strip().lower()}"
    if CACHE_ENABLED and (cached := get_cached_result(cache, cache_key)):
        logger.debug(f"Cache hit für {title}")
        return cached

    async with semaphore:
        for attempt in range(RETRIES):
            try:
                logger.debug(f"Summarizing ({attempt+1}/{RETRIES}): {title}")
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": f"You are a professional financial summarizer. Use the TLDR style internally but do NOT output 'TLDR:'. Respond only in {settings.get('language', 'de')}."},
                        {"role": "user", "content": title},
                    ],
                    max_tokens=150,
                    temperature=0.5,
                )
                summary = resp.choices[0].message.content.strip()
                if CACHE_ENABLED:
                    set_cached_result(cache, cache_key, summary)
                    save_cache(cache)
                return summary
            except Exception as e:
                logger.warning(f"Fehler bei async_summarize ({attempt+1}/{RETRIES}): {e}")
                await asyncio.sleep(1.5 * (attempt + 1))
        return "(Fehler bei Zusammenfassung)"


async def async_sentiment(summary: str, semaphore: asyncio.Semaphore):
    """Analysiert Stimmung asynchron (mit Cache & Retry)."""
    cache_key = f"sentiment::{summary.strip().lower()[:150]}"
    if CACHE_ENABLED and (cached := get_cached_result(cache, cache_key)):
        logger.debug("Cache hit für Sentiment.")
        return cached

    async with semaphore:
        for attempt in range(RETRIES):
            try:
                logger.debug(f"Sentimentanalyse ({attempt+1}/{RETRIES})")
                resp = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": f"You are a financial sentiment analyzer. Respond only with Positiv, Neutral or Negativ in {settings.get('language', 'de')}."},
                        {"role": "user", "content": summary},
                    ],
                    max_tokens=5,
                    temperature=0,
                )
                sentiment = resp.choices[0].message.content.strip().capitalize()
                if sentiment not in ["Positiv", "Neutral", "Negativ"]:
                    sentiment = "Neutral"
                if CACHE_ENABLED:
                    set_cached_result(cache, cache_key, sentiment)
                    save_cache(cache)
                return sentiment
            except Exception as e:
                logger.warning(f"Fehler bei async_sentiment ({attempt+1}/{RETRIES}): {e}")
                await asyncio.sleep(1.5 * (attempt + 1))
        return "Neutral"
