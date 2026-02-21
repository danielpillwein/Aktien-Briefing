import os
import json
import re
import requests
import time
from typing import Dict, Optional
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
        except Exception:
            return []
    return []


def save_message_cache(msg_ids: list):
    MESSAGE_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MESSAGE_CACHE_FILE.write_text(json.dumps(msg_ids), encoding="utf-8")


def register_message_id(message_id: int):
    try:
        normalized_id = int(message_id)
    except Exception:
        return
    msg_ids = load_message_cache()
    if normalized_id not in msg_ids:
        msg_ids.append(normalized_id)
        save_message_cache(msg_ids)


def _delete_message(chat_id: str, message_id: int) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": chat_id, "message_id": message_id},
            timeout=5,
        )
        if resp.ok:
            return True
        logger.debug(f"Telegram deleteMessage fehlgeschlagen für {message_id}: {resp.text}")
        return False
    except Exception as e:
        logger.error(f"Fehler beim Löschen von Nachricht {message_id}: {e}")
        return False


def clear_old_messages(chat_id: Optional[str] = None):
    msg_ids = load_message_cache()
    if not msg_ids:
        return

    target_chat_id = str(chat_id or TELEGRAM_CHAT_ID)

    for mid in msg_ids:
        _delete_message(target_chat_id, int(mid))
        time.sleep(0.03)

    save_message_cache([])


def clear_chat_history_best_effort(
    chat_id: str,
    from_message_id: int,
    max_scan: int = 5000,
    stop_after_failures: int = 60,
) -> Dict[str, int]:
    """
    Versucht, Nachrichten ab from_message_id rückwärts zu löschen.
    Telegram-Berechtigungen/Altersgrenzen werden respektiert (best effort).
    """
    deleted = 0
    failed = 0
    consecutive_failures = 0

    low = max(1, from_message_id - max_scan + 1)
    for message_id in range(from_message_id, low - 1, -1):
        ok = _delete_message(chat_id, message_id)
        if ok:
            deleted += 1
            consecutive_failures = 0
        else:
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= stop_after_failures:
                break
        time.sleep(0.02)

    if deleted > 0:
        save_message_cache([])

    return {"deleted": deleted, "failed": failed}


def clear_chat_before_briefing():
    """
    Führt vor dem Daily-Briefing eine aggressive, aber begrenzte Bereinigung aus.
    Fallback bleibt das Löschen aller gecachten Bot-Nachrichten.
    """
    msg_ids = load_message_cache()
    if msg_ids:
        try:
            anchor = max(int(mid) for mid in msg_ids)
            # Größerer Headroom, damit auch neuere User-Nachrichten oberhalb
            # der letzten bekannten Bot-ID mit erfasst werden.
            stats = clear_chat_history_best_effort(
                chat_id=str(TELEGRAM_CHAT_ID),
                from_message_id=anchor + 600,
                max_scan=4200,
                stop_after_failures=700,
            )
            logger.info(
                f"Daily Chat-Clear (best effort): gelöscht={stats['deleted']}"
            )
        except Exception as e:
            logger.error(f"Fehler bei Daily Chat-Clear: {e}")
    clear_old_messages()


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
                register_message_id(data["result"]["message_id"])
                
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
