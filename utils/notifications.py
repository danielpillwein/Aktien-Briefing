import os
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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


def send_briefing_blocks(data: dict):
    """Sendet den Briefing-Report als 4 sauber formatierte Blöcke (HTML)."""
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

        # === Block 2: News – Portfolio ===
        msg2 = "<b>📰 News – Portfolio</b>\n\n"
        for sym, articles in data["news"]["portfolio"].items():
            msg2 += f"<b>{sym}</b>\n"
            for a in articles:
                msg2 += f"- {a['summary']}\n"
                msg2 += f"  <i>Einschätzung:</i> {a['emoji']} {a['sentiment']}\n"
                msg2 += f"  🔗 <a href='{a['link']}'>Artikel öffnen</a>\n\n"

        # === Block 3: News – Watchlist ===
        msg3 = "<b>👁️ News – Watchlist</b>\n\n"
        for sym, articles in data["news"]["watchlist"].items():
            msg3 += f"<b>{sym}</b>\n"
            for a in articles:
                msg3 += f"- {a['summary']}\n"
                msg3 += f"  <i>Einschätzung:</i> {a['emoji']} {a['sentiment']}\n"
                msg3 += f"  🔗 <a href='{a['link']}'>Artikel öffnen</a>\n\n"

        # === Block 4: Gesamtübersicht ===
        ov = data["overview"]
        msg4 = "<b>🧭 Gesamtübersicht</b>\n\n"
        msg4 += f"📊 <b>Marktlage:</b>\n{ov['macro']}\n\n"
        msg4 += f"💡 <b>Portfolioausblick:</b>\n{ov['portfolio']}\n\n"
        msg4 += f"🧾 <b>Gesamteinschätzung:</b> {ov['final']['emoji']} {ov['final']['text']}"

        # === Versand ===
        for idx, msg in enumerate([msg1, msg2, msg3, msg4], start=1):
            send_telegram_message(msg, html=True)
            logger.info(f"✅ Block {idx}/4 gesendet.")

        return True
    except Exception as e:
        logger.error(f"Fehler beim Versand der Telegram-Blöcke: {e}")
        return False
