import json
import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import yaml

ARCHIVE_DIR = Path("archive")
OLD_OUTPUT_DIR = Path("outputs/briefings")   # alte Markdown-Reports (falls vorhanden)
LOG_DIR = Path("logs")


# -------------------------------------------
# CONFIG LADEN
# -------------------------------------------
def load_config():
    try:
        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("archive", {})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Archivkonfiguration: {e}")
        return {}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


# =====================================================
# 1) NEU: JSONL ARCHIVIERUNG (Hauptfunktion)
# =====================================================
def archive_briefing(entry: dict):
    """
    Speichert das Briefing als JSONL (eine Zeile pro Eintrag).
    Kompatibel mit den bestehenden Archiv-Einstellungen.
    """
    cfg = load_config()
    if not cfg.get("enabled", True):
        logger.info("Archivierung ist deaktiviert.")
        return

    # Datum bestimmen
    date = entry.get("date", datetime.now().strftime("%Y-%m-%d"))
    year, month = date[:4], date[5:7]

    # Zielordner
    target_dir = ARCHIVE_DIR / year / month
    ensure_dir(target_dir)

    # JSONL-Datei pro Tag
    jsonl_path = target_dir / f"{date}.jsonl"

    try:
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.info(f"📦 JSONL archiviert: {jsonl_path}")
    except Exception as e:
        logger.error(f"Fehler bei JSONL-Archivierung: {e}")

    # Logkopie (wie vorher)
    _copy_month_log()

    # Alte Archivierung behandeln (komprimieren / löschen)
    if cfg.get("compress_old", False):
        compress_old_archives(cfg.get("delete_after_days", 180))





# =====================================================
# 3) Logs monatlich kopieren
# =====================================================
def _copy_month_log():
    date = datetime.now()
    month_log = LOG_DIR / f"{date.strftime('%Y-%m')}.log"
    target_dir = ARCHIVE_DIR / str(date.year) / f"{date.month:02d}"

    if month_log.exists():
        shutil.copy2(month_log, target_dir / month_log.name)
        logger.debug(f"📚 Monatslog kopiert: {month_log.name}")


# =====================================================
# 4) Komprimierung alter Archive (Legacy + JSONL)
# =====================================================
def compress_old_archives(delete_after_days: int = 180):
    """
    Komprimiert alte Archive (jsonl + md) in ZIP-Dateien.
    Löscht nach Bedarf die Originaldateien.
    """
    cutoff = datetime.now() - timedelta(days=delete_after_days)

    for year_dir in ARCHIVE_DIR.iterdir():
        if not year_dir.is_dir():
            continue

        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue

            # Alles ältere als cutoff
            old_files = [
                p for p in month_dir.glob("*.*")
                if datetime.fromtimestamp(p.stat().st_mtime) < cutoff
                   and not p.name.endswith(".zip")
            ]

            if not old_files:
                continue

            zip_path = month_dir / f"archive_{month_dir.name}.zip"
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zipf:
                for file in old_files:
                    zipf.write(file, arcname=file.name)
                    logger.debug(f"📦 Archiviert in ZIP: {file.name}")
                    file.unlink()

            logger.info(f"📁 Alte Archive komprimiert: {zip_path}")
