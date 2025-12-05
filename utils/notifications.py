import os
import json
import re
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
TELEGRAM_MAX_LENGTH = 4000  # Sicherheitspuffer unter 4096

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

    save_message_cache([])


# ---------------------------------------------------------
# HTML-Sanitizer: nur erlaubte Tags behalten
# ---------------------------------------------------------
def sanitize_html(text: str) -> str:
    """Entfernt alle HTML-Tags außer <b>, </b>, <a href="...">, </a>."""
    allowed_tags = []
    
    def save_tag(match):
        idx = len(allowed_tags)
        allowed_tags.append(match.group(0))
        return f"__TAG_{idx}__"
    
    text = re.sub(r'<b>|</b>|<a\s+href="[^"]*">|</a>', save_tag, text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    
    parts = re.split(r'(__TAG_\d+__)', text)
    result = []
    for part in parts:
        if part.startswith('__TAG_') and part.endswith('__'):
            idx = int(part[6:-2])
            result.append(allowed_tags[idx])
        else:
            result.append(escape(part))
    
    return ''.join(result)


# ---------------------------------------------------------
# Nachricht in Chunks aufteilen (an Zeilenumbrüchen)
# ---------------------------------------------------------
def split_message(text: str, max_len: int = TELEGRAM_MAX_LENGTH) -> list:
    """Teilt lange Nachrichten an Zeilenumbrüchen auf."""
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    lines = text.split('\n')
    current = ""
    
    for line in lines:
        if len(current) + len(line) + 1 <= max_len:
            current += line + '\n'
        else:
            if current:
                chunks.append(current.strip())
            current = line + '\n'
    
    if current.strip():
        chunks.append(current.strip())
    
    return chunks


# ---------------------------------------------------------
# Nachricht senden + Message-ID speichern
# ---------------------------------------------------------
def send_telegram_message(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    chunks = split_message(text)
    
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            r = requests.post(url, data=payload, timeout=10)
            if not r.ok:
                logger.error(f"Telegram-Fehler: {r.text}")
                continue

            data = r.json()

            if "result" in data and "message_id" in data["result"]:
                msg_ids = load_message_cache()
                msg_ids.append(data["result"]["message_id"])
                save_message_cache(msg_ids)
                
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Telegram Exception: {e}")


# ---------------------------------------------------------
# Blöcke senden (mit Löschen vorher!)
# ---------------------------------------------------------
def send_briefing_blocks(blocks: list):
    """blocks = [ { "title": "...", "emoji": "...", "content": "..." } ]"""

    clear_old_messages()

    for block in blocks:
        title = escape(block.get("title", "Block"))
        emoji = block.get("emoji", "")
        content = block.get("content", "")

        content_safe = sanitize_html(content)
        msg = f"<b>{emoji} {title}</b>\n{content_safe}"

        send_telegram_message(msg)
        time.sleep(0.2)
