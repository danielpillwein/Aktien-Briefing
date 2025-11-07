from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
import pytz
import yaml
from pathlib import Path
from loguru import logger
from .briefing_agent import run_briefing_test
from utils.notifications import send_telegram_message

def job():
    """Erzeugt Briefing und sendet Telegram-Zusammenfassung."""
    logger.info(f"🕒 Starte geplantes Briefing ({datetime.now().isoformat()})")
    data = run_briefing_test()

    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
        msg = f"📩 *Tägliches Aktienbriefing – {date_str}*\n\n"
        msg += "💼 *Portfolio-Entwicklung:*\n"
        for s in data["portfolio"]:
            msg += f"{s['symbol']}: {s['change']} {s['emoji']}\n"
        msg += "\n🧭 *Gesamteinschätzung:*\n"
        msg += f"{data['overview']['final']['emoji']} {data['overview']['final']['text']}"
        send_telegram_message(msg)
    except Exception as e:
        logger.error(f"Fehler beim Telegram-Versand: {e}")

def start_scheduler():
    """Startet täglichen Scheduler laut settings.yaml."""
    with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    time_str = cfg["scheduler"]["time"]
    tz = cfg["scheduler"].get("timezone", "Europe/Vienna")
    hour, minute = map(int, time_str.split(":"))

    scheduler = BlockingScheduler(timezone=pytz.timezone(tz))
    scheduler.add_job(job, "cron", hour=hour, minute=minute)

    logger.info(f"📅 Scheduler gestartet – tägliches Briefing um {time_str} ({tz})")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹️ Scheduler gestoppt.")
