from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
from pathlib import Path

import pytz
import yaml
from loguru import logger

from core.briefing_agent import (
    persist_prepared_memory,
    prepare_briefing_payload,
    run_briefing_test,
)
from core.report_builder import render_report
from utils.archive_manager import archive_briefing
from utils.notifications import send_briefing_blocks

_prepared_payload = None


def prepare_briefing():
    """
    Führt die Analyse aus und speichert die Blöcke für späteren Versand.
    Wird 5 Minuten vor der geplanten Zeit ausgeführt.
    """
    global _prepared_payload

    logger.info(f"📊 Starte Briefing-Vorbereitung ({datetime.now().isoformat()})...")

    try:
        _prepared_payload = prepare_briefing_payload()
        render_report(_prepared_payload["report_data"])
        archive_briefing(_prepared_payload["archive_entry"])
        logger.info("✅ Briefing vorbereitet und wartet auf Versand.")
    except Exception as e:
        logger.exception(f"❌ Fehler bei Briefing-Vorbereitung: {e}")
        _prepared_payload = None


def send_briefing():
    """
    Sendet die vorbereiteten Blöcke per Telegram.
    Wird zur geplanten Zeit ausgeführt.
    """
    global _prepared_payload

    logger.info(f"📤 Sende Briefing ({datetime.now().isoformat()})...")

    if _prepared_payload:
        send_briefing_blocks(_prepared_payload["blocks"])
        persist_prepared_memory(_prepared_payload)
        logger.info("✅ Briefing gesendet.")
        _prepared_payload = None
    else:
        logger.warning("⚠️ Keine vorbereiteten Daten vorhanden - führe Komplett-Briefing aus...")
        run_briefing_test(send_telegram=True)


def start_scheduler():
    """Startet den Scheduler mit 2 Jobs: Vorbereitung (5 Min früher) + Versand."""
    try:
        with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)

        sched_cfg = settings.get("scheduler", {})
        time_str = sched_cfg.get("time", "07:00")
        timezone = sched_cfg.get("timezone", "Europe/Vienna")

        hour, minute = map(int, time_str.split(":"))

        prep_minute = minute - 5
        prep_hour = hour
        if prep_minute < 0:
            prep_minute += 60
            prep_hour -= 1
            if prep_hour < 0:
                prep_hour = 23

        tz = pytz.timezone(timezone)
        scheduler = BlockingScheduler(timezone=tz)

        scheduler.add_job(prepare_briefing, "cron", hour=prep_hour, minute=prep_minute)
        scheduler.add_job(send_briefing, "cron", hour=hour, minute=minute)

        logger.info("📅 Scheduler gestartet:")
        logger.info(f"   - Vorbereitung: {prep_hour:02d}:{prep_minute:02d} ({timezone})")
        logger.info(f"   - Versand:      {time_str} ({timezone})")

        scheduler.start()

    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹️ Scheduler gestoppt.")
    except Exception as e:
        logger.error(f"Fehler beim Start des Schedulers: {e}")
