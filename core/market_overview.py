from openai import OpenAI
from dotenv import load_dotenv
from loguru import logger
from utils.prompt_loader import load_prompt

import re
import os

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def strip_markdown_from_summary(text: str) -> str:
    """Entfernt Fettschrift-Markdown (**) nur aus KI-Zusammenfassungstexten."""
    if not text:
        return text
    # Entfernt ** ... **, lässt andere Markdown-Zeichen intakt
    cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    # Überflüssige Leerzeilen normalisieren
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()



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


def generate_market_overview(portfolio_data, summaries):
    """
    Erzeugt eine GPT-gestützte Marktanalyse mit Makro-, Portfolio- und Gesamteinschätzung.
    Sprache: Deutsch, Stil: wirtschaftlich-verständlich, Länge: mittel (3–5 Sätze pro Abschnitt)
    """
    try:
        kursdaten = ", ".join(
            [f"{s.symbol} ({s.change_percent:+.2f}%)" for s in portfolio_data]
        )
        joined_summaries = "\n".join(summaries)

        # Prompt laden und formatieren
        prompt = load_prompt("market_overview").format(
            kursdaten=kursdaten, summaries=joined_summaries
        )

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Du bist ein erfahrener Finanzanalyst."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            max_tokens=500,
        )

        text = response.choices[0].message.content.strip()
        return parse_market_overview(text)
    except Exception as e:
        logger.error(f"Fehler bei Marktanalyse: {e}")
        return {
            "macro": "(Fehler bei Marktlage)",
            "portfolio": "(Fehler bei Portfolioanalyse)",
            "final": {"text": "(Fehler bei Gesamteinschätzung)", "emoji": "⚠️"},
        }


def parse_market_overview(text: str):
    """Parst GPT-Antwort in Makro-, Portfolio- und Gesamteinschätzung."""
    macro_match = re.search(r"(?i)makro:\s*(.*?)(?:portfolio:|gesamteinschätzung:|$)", text, re.S)
    portfolio_match = re.search(r"(?i)portfolio:\s*(.*?)(?:gesamteinschätzung:|$)", text, re.S)
    final_match = re.search(r"(?i)gesamteinschätzung:\s*(.*)", text, re.S)

    macro = macro_match.group(1).strip() if macro_match else "(keine Daten)"
    portfolio = portfolio_match.group(1).strip() if portfolio_match else "(keine Daten)"
    final_text = final_match.group(1).strip() if final_match else "(keine Daten)"

    emoji_match = re.search(r"(🟢|🟡|🔴|⚪️|⚫️)", final_text)
    emoji = emoji_match.group(1) if emoji_match else "🟡"

    return {
        "macro": strip_markdown_from_summary(macro),
        "portfolio": strip_markdown_from_summary(portfolio),
        "final": {
            "text": strip_markdown_from_summary(final_text),
            "emoji": emoji,
        },
    }

