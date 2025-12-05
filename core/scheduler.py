from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
import pytz
import yaml
import time
from pathlib import Path
from loguru import logger
from core.briefing_agent import run_briefing_test
from utils.notifications import send_briefing_blocks


# ---------------------------------------------------------
# Globale Variable für vorbereitete Daten
# ---------------------------------------------------------
_prepared_blocks = None


def prepare_briefing():
    """
    Führt die Analyse aus und speichert die Blöcke für späteren Versand.
    Wird 5 Minuten vor der geplanten Zeit ausgeführt.
    """
    global _prepared_blocks
    
    logger.info(f"📊 Starte Briefing-Vorbereitung ({datetime.now().isoformat()})...")
    
    try:
        # Analyse durchführen OHNE Telegram-Versand
        from config.settings_loader import load_settings
        from core.fetch_prices import get_price_changes
        from core.briefing_agent import (
            gather_news_parallel, generate_market_overview,
            format_stock, build_telegram_blocks
        )
        from core.report_builder import render_report
        from utils.archive_manager import archive_briefing
        import asyncio
        
        settings = load_settings()
        pf_items = settings["portfolio"]
        wl_items = settings["watchlist"]
        
        # Kursdaten
        logger.info("💹 Hole Kursdaten…")
        pf_data, date = get_price_changes(pf_items)
        wl_data, _ = get_price_changes(wl_items)
        
        # News
        logger.info("📰 Starte parallele News-Analyse…")
        news_pf, news_wl = asyncio.run(gather_news_parallel(pf_items, wl_items))
        
        all_summaries = [
            ai["summary"]
            for arr in news_pf.values()
            for ai in arr
        ]
        
        # Marktanalyse
        logger.info("🌍 Erstelle Marktanalyse…")
        overview = generate_market_overview(pf_data, all_summaries)
        
        pf_fmt = [format_stock(s) for s in pf_data]
        wl_fmt = [format_stock(s) for s in wl_data]
        
        # Blöcke vorbereiten
        _prepared_blocks = build_telegram_blocks(
            date, pf_fmt, wl_fmt,
            {"portfolio": news_pf, "watchlist": news_wl},
            overview
        )
        
        # Debug-Report speichern
        render_report({
            "date": date,
            "portfolio": pf_fmt,
            "watchlist": wl_fmt,
            "news": {"portfolio": news_pf, "watchlist": news_wl},
            "overview": overview,
        })
        
        # Archivieren
        archive_briefing({
            "date": date,
            "portfolio": pf_fmt,
            "watchlist": wl_fmt,
            "news": {"portfolio": news_pf, "watchlist": news_wl},
            "market_overview": overview,
            "version": "1.0.0"
        })
        
        logger.info("✅ Briefing vorbereitet und wartet auf Versand.")
        
    except Exception as e:
        logger.error(f"❌ Fehler bei Briefing-Vorbereitung: {e}")
        _prepared_blocks = None


def send_briefing():
    """
    Sendet die vorbereiteten Blöcke per Telegram.
    Wird zur geplanten Zeit ausgeführt.
    """
    global _prepared_blocks
    
    logger.info(f"📤 Sende Briefing ({datetime.now().isoformat()})...")
    
    if _prepared_blocks:
        send_briefing_blocks(_prepared_blocks)
        logger.info("✅ Briefing gesendet.")
        _prepared_blocks = None
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
        
        # Berechne Vorbereitungszeit (5 Minuten früher)
        prep_minute = minute - 5
        prep_hour = hour
        if prep_minute < 0:
            prep_minute += 60
            prep_hour -= 1
            if prep_hour < 0:
                prep_hour = 23
        
        tz = pytz.timezone(timezone)
        scheduler = BlockingScheduler(timezone=tz)

        # Job 1: Vorbereitung (5 Min früher)
        scheduler.add_job(
            prepare_briefing, 
            "cron", 
            hour=prep_hour, 
            minute=prep_minute
        )
        
        # Job 2: Versand (pünktlich)
        scheduler.add_job(
            send_briefing, 
            "cron", 
            hour=hour, 
            minute=minute
        )
        
        logger.info(f"📅 Scheduler gestartet:")
        logger.info(f"   - Vorbereitung: {prep_hour:02d}:{prep_minute:02d} ({timezone})")
        logger.info(f"   - Versand:      {time_str} ({timezone})")

        scheduler.start()
        
    except (KeyboardInterrupt, SystemExit):
        logger.info("⏹️ Scheduler gestoppt.")
    except Exception as e:
        logger.error(f"Fehler beim Start des Schedulers: {e}")
