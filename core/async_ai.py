import asyncio
import os
from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI
from utils.prompt_loader import load_prompt
from utils.cache import get_cache, set_cache
from utils.preprocess import clean_text

# ---------------------------------------------------------
# .env laden
# ---------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------
# OpenAI Client
# ---------------------------------------------------------
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---------------------------------------------------------
# Parallelitätslimit (OpenAI limitiert ≈ 5–8 gleichzeitige Requests)
# ---------------------------------------------------------
SEMAPHORE = asyncio.Semaphore(5)

SENTIMENT_TO_EMOJI = {
    "positiv": "🟢",
    "neutral": "🟡",
    "negativ": "🔴",
}


# =========================================================
#  STEP 1: Summary generieren
# =========================================================
async def _get_summary(article_content: str) -> str:
    """Generiert eine Zusammenfassung des Artikels."""
    prompt = load_prompt("summary").replace("{article_text}", article_content)
    
    response = await client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )
    
    return response.output_text.strip()


# =========================================================
#  STEP 2: Sentiment analysieren
# =========================================================
async def _get_sentiment(summary: str) -> str:
    """Analysiert das Sentiment einer Zusammenfassung."""
    prompt = load_prompt("sentiment").replace("{summary_text}", summary)
    
    response = await client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )
    
    raw = response.output_text.strip().lower()
    
    # Nur erlaubte Werte
    if raw in ["positiv", "neutral", "negativ"]:
        return raw
    
    logger.warning(f"⚠️ Unerwartetes Sentiment: {raw} → fallback neutral")
    return "neutral"


# =========================================================
#  INTERNE IMPLEMENTIERUNG – ZWEI Requests pro Artikel
# =========================================================
async def _process_internal(article):
    cache_key = f"combo::{article['title']}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    cleaned = clean_text(article["content"])

    # Step 1: Summary
    summary = await _get_summary(cleaned)
    
    # Step 2: Sentiment
    sentiment = await _get_sentiment(summary)
    emoji = SENTIMENT_TO_EMOJI.get(sentiment, "🟡")

    data = {
        "summary": summary,
        "sentiment": sentiment,
        "emoji": emoji
    }

    set_cache(cache_key, data)
    return data


# =========================================================
#  ÖFFENTLICHE API – nutzt Semaphore (Rate-Limit fix)
# =========================================================
async def process_article(article):
    """
    Wrappt den internen Prozessor mit einem Semaphore,
    damit die Pipeline nie vom OpenAI-Rate-Limiter
    in serielle Verarbeitung gezwungen wird.
    """
    async with SEMAPHORE:
        return await _process_internal(article)
