import shutil
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from loguru import logger
import yaml

ARCHIVE_DIR = Path("archive")
OUTPUT_DIR = Path("outputs/briefings")
LOG_DIR = Path("logs")


def load_config():
    try:
        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f).get("archive", {})
    except Exception as e:
        logger.error(f"Fehler beim Laden der Archivkonfiguration: {e}")
        return {}


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def archive_report():
    """Kopiert den neuesten Report ins Archiv /archive/YYYY/MM/"""
    cfg = load_config()
    if not cfg.get("enabled", True):
        logger.info("Archivierung ist deaktiviert.")
        return

    reports = sorted(OUTPUT_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime)
    if not reports:
        logger.warning("Kein Report zum Archivieren gefunden.")
        return

    latest = reports[-1]
    date = datetime.now()
    target_dir = ARCHIVE_DIR / str(date.year) / f"{date.month:02d}"
    ensure_dir(target_dir)

    target_path = target_dir / latest.name
    shutil.copy2(latest, target_path)
    logger.info(f"📦 Report archiviert: {target_path}")

    # Logs monatlich kopieren
    month_log = LOG_DIR / f"{date.strftime('%Y-%m')}.log"
    if month_log.exists():
        shutil.copy2(month_log, target_dir / month_log.name)

    # Alte Reports optional behandeln
    if cfg.get("compress_old", False):
        compress_old_reports(cfg.get("delete_after_days", 180))


def compress_old_reports(delete_after_days: int = 180):
    """Komprimiert alte Reports und löscht sie bei Bedarf."""
    cutoff = datetime.now() - timedelta(days=delete_after_days)
    for year_dir in ARCHIVE_DIR.iterdir():
        if not year_dir.is_dir():
            continue
        for month_dir in year_dir.iterdir():
            if not month_dir.is_dir():
                continue
            old_reports = [p for p in month_dir.glob("*.md") if datetime.fromtimestamp(p.stat().st_mtime) < cutoff]
            if not old_reports:
                continue

            zip_path = month_dir / f"archive_{month_dir.name}.zip"
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zipf:
                for report in old_reports:
                    zipf.write(report, arcname=report.name)
                    logger.debug(f"Report hinzugefügt: {report.name}")
                    report.unlink()
            logger.info(f"📁 Alte Reports komprimiert: {zip_path}")
