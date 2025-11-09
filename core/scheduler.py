from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
import pytz
import yaml
from pathlib import Path
from loguru import logger
from .briefing_agent import run_briefing_test
from utils.notifications import send_briefing_blocks

def job():
    """Führt das tägliche Briefing aus und sendet Telegram-Blöcke."""
    logger.info(f"🕒 Starte geplantes Briefing ({datetime.now().isoformat()})")
    try:
        data = run_briefing_test(send_telegram=False)  # Telegram NICHT doppelt senden
        send_briefing_blocks(data)                     # Nur hier einmal senden
        logger.info("✅ Tägliches Briefing abgeschlossen und gesendet.")
    except Exception as e:
        logger.error(f"❌ Fehler im geplanten Briefing: {e}")


def start_scheduler():
    """Startet den täglichen Scheduler gemäß settings.yaml."""
    try:
        with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)

        sched_cfg = settings.get("scheduler", {})
        time_str = sched_cfg.get("time", "07:30")
        timezone = sched_cfg.get("timezone", "Europe/Vienna")

        hour, minute = map(int, time_str.split(":"))
        scheduler = BlockingScheduler(timezone=pytz.timezone(timezone))

        scheduler.add_job(job, "cron", hour=hour, minute=minute)
        logger.info(f"📅 Scheduler gestartet – tägliches Briefing um {time_str} ({timezone})")

        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹️ Scheduler gestoppt.")
    except Exception as e:
        logger.error(f"Fehler beim Start des Schedulers: {e}")
