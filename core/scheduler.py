import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

from core.briefing_agent import (
    persist_prepared_memory,
    prepare_briefing_payload,
    run_briefing_test,
)
from core.report_builder import render_report
from utils.archive_manager import archive_briefing
from utils.notifications import clear_chat_before_briefing, send_briefing_blocks

_prepared_payload = None
_scheduler: Optional[BackgroundScheduler] = None
_scheduler_meta = {}
PREPARE_JOB_ID = "daily_prepare_briefing"
SEND_JOB_ID = "daily_send_briefing"


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
    clear_chat_before_briefing()

    if _prepared_payload:
        send_briefing_blocks(_prepared_payload["blocks"])
        persist_prepared_memory(_prepared_payload)
        logger.info("✅ Briefing gesendet.")
        _prepared_payload = None
    else:
        logger.warning("⚠️ Keine vorbereiteten Daten vorhanden - führe Komplett-Briefing aus...")
        run_briefing_test(send_telegram=True)


def _load_scheduler_config():
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

    return {
        "hour": hour,
        "minute": minute,
        "prep_hour": prep_hour,
        "prep_minute": prep_minute,
        "time_str": time_str,
        "timezone": timezone,
    }


def start_scheduler_background() -> BackgroundScheduler:
    global _scheduler
    global _scheduler_meta

    if _scheduler and _scheduler.running:
        return _scheduler

    cfg = _load_scheduler_config()
    tz = pytz.timezone(cfg["timezone"])
    scheduler = BackgroundScheduler(timezone=tz)

    scheduler.add_job(
        prepare_briefing,
        "cron",
        hour=cfg["prep_hour"],
        minute=cfg["prep_minute"],
        id=PREPARE_JOB_ID,
        replace_existing=True,
    )
    scheduler.add_job(
        send_briefing,
        "cron",
        hour=cfg["hour"],
        minute=cfg["minute"],
        id=SEND_JOB_ID,
        replace_existing=True,
    )

    scheduler.start()
    _scheduler = scheduler
    _scheduler_meta = cfg

    logger.info("📅 Scheduler gestartet:")
    logger.info(f"   - Vorbereitung: {cfg['prep_hour']:02d}:{cfg['prep_minute']:02d} ({cfg['timezone']})")
    logger.info(f"   - Versand:      {cfg['time_str']} ({cfg['timezone']})")
    return scheduler


def stop_scheduler_background():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("⏹️ Scheduler gestoppt.")
    _scheduler = None


def get_scheduler_status() -> dict:
    running = bool(_scheduler and _scheduler.running)
    next_prepare = None
    next_send = None

    if running:
        prepare_job = _scheduler.get_job(PREPARE_JOB_ID)
        send_job = _scheduler.get_job(SEND_JOB_ID)
        if prepare_job and prepare_job.next_run_time:
            next_prepare = prepare_job.next_run_time.isoformat()
        if send_job and send_job.next_run_time:
            next_send = send_job.next_run_time.isoformat()

    return {
        "running": running,
        "timezone": _scheduler_meta.get("timezone"),
        "configured_send_time": _scheduler_meta.get("time_str"),
        "next_prepare_run": next_prepare,
        "next_send_run": next_send,
    }


def start_scheduler():
    """
    Legacy blocking mode: startet den Scheduler im Hintergrund
    und blockiert den Prozess bis zum manuellen Stop.
    """
    try:
        start_scheduler_background()
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler_background()
    except Exception as e:
        logger.error(f"Fehler beim Start des Schedulers: {e}")
