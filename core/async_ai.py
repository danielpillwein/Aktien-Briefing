import asyncio
import os
from loguru import logger
from openai import AsyncOpenAI
from dotenv import load_dotenv
from utils.prompt_loader import load_prompt

load_dotenv()
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def async_summarize(article_text: str, semaphore: asyncio.Semaphore) -> str:
    """Erstellt asynchron eine kurze 3-4-Satz-Zusammenfassung."""
    try:
        prompt = load_prompt("summary").format(article_text=article_text.strip())
        async with semaphore:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a financial news summarizer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.4,
                max_tokens=150,
            )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Fehler bei async_summarize: {e}")
        return "(Fehler bei Zusammenfassung)"


async def async_sentiment(summary: str, semaphore: asyncio.Semaphore) -> str:
    """Analysiert Stimmung (Positiv / Neutral / Negativ) asynchron."""
    try:
        prompt = load_prompt("sentiment").format(summary=summary)
        async with semaphore:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a financial sentiment analyzer."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                max_tokens=10,
            )
        result = response.choices[0].message.content.strip().lower()
        if "positiv" in result or "positive" in result:
            return "Positiv"
        if "negativ" in result or "negative" in result:
            return "Negativ"
        return "Neutral"
    except Exception as e:
        logger.error(f"Fehler bei async_sentiment: {e}")
        return "Neutral"
