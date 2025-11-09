from openai import OpenAI
from utils.prompt_loader import load_prompt
from loguru import logger
from dotenv import load_dotenv
import os

# ⬇️ ENV-Variablen sofort laden
# zuerst prüfen, ob die globale .env existiert
if os.path.exists("/etc/aktienbriefing/.env"):
    load_dotenv("/etc/aktienbriefing/.env")
else:
    load_dotenv()  # Fallback für lokale Tests

# ⬇️ OpenAI-Client mit API-Key initialisieren
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize_article(article_text: str) -> str:
    """Erstellt eine 2–3-Satz-Zusammenfassung des Artikels."""
    try:
        prompt = load_prompt("summary").format(article_text=article_text.strip())
        response = client.chat.completions.create(
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
        logger.error(f"Fehler bei Zusammenfassung: {e}")
        return "(Fehler bei Zusammenfassung)"
