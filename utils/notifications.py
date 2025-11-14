import os
import time
import requests
from loguru import logger
from dotenv import load_dotenv
from html import escape

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
    raise RuntimeError("TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlen in .env!")


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
    except Exception as e:
        logger.error(f"Telegram Exception: {e}")


def send_briefing_blocks(blocks: list):
    """
    blocks = [ { "title": "...", "emoji": "...", "content": "..." } ]
    """
    for block in blocks:
        title = escape(block.get("title", "Block"))
        emoji = block.get("emoji", "")
        content = block.get("content", "")

        # HTML safe
        content_html = content.replace("\n", "\n")

        msg = f"<b>{emoji} {title}</b>\n{content_html}"

        send_telegram_message(msg)
        time.sleep(0.2)
