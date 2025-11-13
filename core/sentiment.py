from openai import OpenAI
from utils.prompt_loader import load_prompt
from loguru import logger
from dotenv import load_dotenv
import os

# zuerst prüfen, ob die globale .env existiert
if os.path.exists("/etc/aktienbriefing/.env"):
    load_dotenv("/etc/aktienbriefing/.env")
else:
    load_dotenv()  # Fallback für lokale Tests
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def analyze_sentiment(summary: str) -> str:
    """Ermittelt die Stimmung (Positiv / Neutral / Negativ) für einen Text."""
    try:
        prompt = load_prompt("sentiment").format(summary=summary)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": f"You are a financial sentiment analyzer. Respond only with Positiv, Neutral or Negativ in {settings.get('language', 'de')}."},
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
        logger.error(f"Fehler bei Sentimentanalyse: {e}")
        return "Neutral"
