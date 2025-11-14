import json
from pathlib import Path
from datetime import datetime
from loguru import logger


def render_report(data: dict) -> Path:
    """
    Speichert das Briefing als JSON Datei (nicht JSONL!).
    Dient nur zur lokalen Einsicht / Debugging.
    Die echte Archivierung passiert in archive_manager.py als JSONL.
    """
    try:
        output_dir = Path("outputs/briefings")
        output_dir.mkdir(parents=True, exist_ok=True)

        file_path = output_dir / f"{data['date']}.json"

        with file_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"📄 Debug-Report gespeichert unter: {file_path}")
        return file_path

    except Exception as e:
        logger.error(f"Fehler beim Speichern des JSON-Reports: {e}")
        return None
