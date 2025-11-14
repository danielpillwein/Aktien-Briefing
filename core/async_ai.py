import asyncio
import os
import json
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
#  SANITIZE KI-Antwort (Backticks, Markdown entfernen)
# =========================================================
def clean_json_output(text: str) -> str:
    if not text:
        return ""

    text = text.strip()

    # Entferne ```json ... ```
    if text.startswith("```"):
        text = text.strip("`")
        text = text.replace("json", "", 1).strip()

    return text


# =========================================================
#  INTERNE IMPLEMENTIERUNG – EIN Request pro Artikel!!
# =========================================================
async def _process_internal(article):
    cache_key = f"combo::{article['title']}"
    cached = get_cache(cache_key)
    if cached:
        return cached

    cleaned = clean_text(article["content"])

    # Prompt sicher laden
    base_prompt = load_prompt("sentiment")

    # Platzhalter sicher ersetzen
    prompt = base_prompt.replace("{summary_text}", cleaned)

    # API Request
    response = await client.responses.create(
        model="gpt-4.1-mini",
        input=prompt
    )

    raw = clean_json_output(response.output_text)

    try:
        data = json.loads(raw)
        sent = data.get("sentiment", "neutral").lower()
        data["emoji"] = SENTIMENT_TO_EMOJI.get(sent, "🟡")
    except:
        logger.error(f"⚠️ KI-Ausgabe nicht parsebar: {response.output_text}")
        data = {
            "summary": "Keine Zusammenfassung verfügbar.",
            "sentiment": "neutral",
            "emoji": "🟡"
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
