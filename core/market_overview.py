from openai import OpenAI
from dotenv import load_dotenv
from loguru import logger
import os

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize_portfolio_news(news_summaries: list[str]) -> str:
    """
    Erstellt eine Gesamtzusammenfassung des Portfolios auf Basis der Artikel-Zusammenfassungen.
    """
    try:
        text = "\n".join(news_summaries)
        prompt = (
            "Fasse die folgenden Artikelzusammenfassungen zu einem Gesamtüberblick zusammen. "
            "Ziel: 3-4 Sätze über die allgemeine Stimmung, Themen und Tendenzen des Portfolios.\n\n"
            f"{text}"
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial market analyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=250,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Fehler bei Marktübersicht: {e}")
        return "(Fehler bei Gesamtzusammenfassung)"
