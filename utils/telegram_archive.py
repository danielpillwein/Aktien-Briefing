import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from loguru import logger

ARCHIVE_ROOT = Path("archive/telegram")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _archive_path(ts: datetime) -> Path:
    return ARCHIVE_ROOT / f"{ts:%Y}" / f"{ts:%m}" / f"{ts:%Y-%m-%d}.jsonl.gz"


def archive_outgoing_message(
    *,
    chat_id: str,
    message_id: int,
    text: str,
    parse_mode: str = "",
    source: str = "",
) -> None:
    """
    Speichert jede gesendete Bot-Nachricht platzsparend als kompaktes JSONL in GZip.
    Ziel: spätere Analysen bei minimalem Speicherbedarf.
    """
    try:
        ts = _utc_now()
        target = _archive_path(ts)
        target.parent.mkdir(parents=True, exist_ok=True)

        clean_text = str(text or "")
        payload = {
            "ts": ts.replace(microsecond=0).isoformat(),
            "chat_id": str(chat_id),
            "message_id": int(message_id),
            "parse_mode": str(parse_mode or ""),
            "source": str(source or ""),
            "len": len(clean_text),
            "sha256": hashlib.sha256(clean_text.encode("utf-8")).hexdigest(),
            "text": clean_text,
        }

        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with gzip.open(target, "at", encoding="utf-8", compresslevel=9) as f:
            f.write(line)
    except Exception as exc:
        # Archivierung darf Versand niemals blockieren.
        logger.error(f"Telegram-Archivierung fehlgeschlagen: {exc}")


def archive_outgoing_message_from_telegram_obj(
    *,
    message_obj,
    text: Optional[str],
    parse_mode: str = "",
    source: str = "",
) -> None:
    if not message_obj:
        return
    try:
        chat = getattr(message_obj, "chat", None)
        chat_id = getattr(chat, "id", "")
        message_id = getattr(message_obj, "message_id", 0)
        archive_outgoing_message(
            chat_id=str(chat_id),
            message_id=int(message_id),
            text=str(text or ""),
            parse_mode=parse_mode,
            source=source,
        )
    except Exception as exc:
        logger.error(f"Telegram-Objektarchivierung fehlgeschlagen: {exc}")
