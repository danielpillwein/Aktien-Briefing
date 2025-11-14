import os
import json
import requests
import time
from loguru import logger
from dotenv import load_dotenv
from pathlib import Path
from html import escape

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MESSAGE_CACHE_FILE = Path("data/telegram_messages.json")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlen in .env!")


# ---------------------------------------------------------
# Hilfsfunktionen zum Speichern/Löschen der gesendeten Messages
# ---------------------------------------------------------
def load_message_cache() -> list:
    if MESSAGE_CACHE_FILE.exists():
        try:
            return json.loads(MESSAGE_CACHE_FILE.read_text(encoding="utf-8"))
        except:
            return []
    return []


def save_message_cache(msg_ids: list):
    MESSAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MESSAGE_CACHE_FILE.write_text(json.dumps(msg_ids), encoding="utf-8")


def clear_old_messages():
    msg_ids = load_message_cache()
    if not msg_ids:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"

    for mid in msg_ids:
        try:
            requests.post(url, data={
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": mid
            }, timeout=5)
            time.sleep(0.05)
        except Exception as e:
            logger.error(f"Fehler beim Löschen von Nachricht {mid}: {e}")

    # Cache leeren
    save_message_cache([])


# ---------------------------------------------------------
# Nachricht senden + Message-ID speichern
# ---------------------------------------------------------
def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    try:
        r = requests.post(url, data=payload, timeout=10)
        if not r.ok:
            logger.error(f"Telegram-Fehler: {r.text}")
            return

        data = r.json()

        # message_id speichern
        if "result" in data and "message_id" in data["result"]:
            msg_ids = load_message_cache()
            msg_ids.append(data["result"]["message_id"])
            save_message_cache(msg_ids)

    except Exception as e:
        logger.error(f"Telegram Exception: {e}")


# ---------------------------------------------------------
# Blöcke senden (mit Löschen vorher!)
# ---------------------------------------------------------
def send_briefing_blocks(blocks: list):
    """
    blocks = [ { "title": "...", "emoji": "...", "content": "..." } ]
    """

    # 1️⃣ vor dem neuen Briefing: alte Nachrichten löschen
    clear_old_messages()

    # 2️⃣ neue Blöcke senden
    for block in blocks:
        title = escape(block.get("title", "Block"))
        emoji = block.get("emoji", "")
        content = block.get("content", "")

        content_html = content.replace("\n", "\n")
        msg = f"<b>{emoji} {title}</b>\n{content_html}"

        send_telegram_message(msg)
        time.sleep(0.2)
