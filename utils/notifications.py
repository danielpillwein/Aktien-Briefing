import os
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

MAX_LENGTH = 4000  # Telegram Limit (sicher unter 4096 bleiben)


def send_telegram_message(message: str, html: bool = False):
    """Sendet eine Telegram-Nachricht (Markdown oder HTML)."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram-Daten fehlen (.env prüfen)")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": message,
            "parse_mode": "HTML" if html else "Markdown",
            "disable_web_page_preview": True,
        }
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            logger.info("✅ Telegram-Nachricht gesendet.")
            return True
        else:
            logger.error(f"Telegram-Fehler: {r.text}")
            return False
    except Exception as e:
        logger.error(f"Fehler beim Telegram-Versand: {e}")
        return False


def split_long_message(text: str, max_length: int = MAX_LENGTH) -> list[str]:
    """Teilt langen Text an sinnvollen Stellen (nach Aktien-Abschnitten)."""
    if len(text) <= max_length:
        return [text]

    parts = []
    lines = text.split("\n")
    current_block = ""

    for line in lines:
        # +1 wegen \n
        if len(current_block) + len(line) + 1 > max_length:
            parts.append(current_block.strip())
            current_block = ""
        current_block += line + "\n"

    if current_block.strip():
        parts.append(current_block.strip())

    return parts


def send_briefing_blocks(data: dict):
    """Sendet den Briefing-Report als 4 sauber formatierte Blöcke (HTML, mit Split bei langen Nachrichten)."""
    if not BOT_TOKEN or not CHAT_ID:
        logger.warning("⚠️ Telegram-Daten fehlen (.env prüfen)")
        return False

    try:
        # === Block 1: Überblick ===
        msg1 = "<b>📊 Tägliches Aktienbriefing</b>\n\n"
        msg1 += "<b>💼 Portfolio:</b>\n"
        for s in data["portfolio"]:
            msg1 += f"{s['symbol']}: {s['change']} {s['emoji']} {s['sentiment']}\n"
        msg1 += "\n<b>👁️ Watchlist:</b>\n"
        for s in data["watchlist"]:
            msg1 += f"{s['symbol']}: {s['change']} {s['emoji']} {s['sentiment']}\n"

        send_telegram_message(msg1, html=True)

        # === Block 2: News – Portfolio ===
        base_msg = "<b>📰 News – Portfolio</b>\n\n"
        msg2 = base_msg
        for sym, articles in data["news"]["portfolio"].items():
            part = f"<b>{sym}</b>\n"
            for a in articles:
                part += f"- {a['summary']}\n"
                part += f"  <i>Einschätzung:</i> {a['emoji']} {a['sentiment']}\n"
                part += f"  🔗 <a href='{a['link']}'>Artikel öffnen</a>\n\n"
            msg2 += part

        # Nachrichten ggf. splitten
        parts = split_long_message(msg2)
        for i, chunk in enumerate(parts, 1):
            title = f"📰 News – Portfolio (Teil {i}/{len(parts)})" if len(parts) > 1 else "📰 News – Portfolio"
            send_telegram_message(f"<b>{title}</b>\n\n{chunk}", html=True)

        # === Block 3: News – Watchlist ===
        base_msg = "<b>👁️ News – Watchlist</b>\n\n"
        msg3 = base_msg
        for sym, articles in data["news"]["watchlist"].items():
            part = f"<b>{sym}</b>\n"
            for a in articles:
                part += f"- {a['summary']}\n"
                part += f"  <i>Einschätzung:</i> {a['emoji']} {a['sentiment']}\n"
                part += f"  🔗 <a href='{a['link']}'>Artikel öffnen</a>\n\n"
            msg3 += part

        # Nachrichten ggf. splitten
        parts = split_long_message(msg3)
        for i, chunk in enumerate(parts, 1):
            title = f"👁️ News – Watchlist (Teil {i}/{len(parts)})" if len(parts) > 1 else "👁️ News – Watchlist"
            send_telegram_message(f"<b>{title}</b>\n\n{chunk}", html=True)

        # === Block 4: Gesamtübersicht ===
        ov = data["overview"]
        msg4 = "<b>🧭 Gesamtübersicht</b>\n\n"
        msg4 += f"📊 <b>Marktlage:</b>\n{ov['macro']}\n\n"
        msg4 += f"💡 <b>Portfolioausblick:</b>\n{ov['portfolio']}\n\n"
        msg4 += f"🧾 <b>Gesamteinschätzung:</b> {ov['final']['emoji']} {ov['final']['text']}"

        send_telegram_message(msg4, html=True)

        logger.info("✅ Alle Telegram-Blöcke erfolgreich gesendet (inkl. Split).")
        return True

    except Exception as e:
        logger.error(f"Fehler beim Versand der Telegram-Blöcke: {e}")
        return False
