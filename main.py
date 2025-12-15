import argparse
import time
from pathlib import Path
from core.briefing_agent import run_briefing_test
from core.scheduler import start_scheduler
from loguru import logger

# Logging-Konfiguration: Logs in Datei speichern
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)
logger.add(
    log_dir / "aktien_briefing.log",
    rotation="1 day",      # Täglich neue Datei
    retention="7 days",    # Alte Logs nach 7 Tagen löschen
    compression="zip",     # Alte Logs komprimieren
    encoding="utf-8",
    level="DEBUG",
)


def main():
    parser = argparse.ArgumentParser(description="AI Aktienbriefing Agent")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Führt den Agenten sofort aus (Testmodus)",
    )
    args = parser.parse_args()

    if args.test:
        logger.info("🚀 Starte manuelles Briefing (Testmodus)...")

        start_time = time.time()

        run_briefing_test()

        duration = time.time() - start_time
        logger.info(f"⏱️ Testlauf abgeschlossen — Gesamtdauer: {duration:.2f} Sekunden")

    else:
        logger.info("🕓 Starte Scheduler-Modus...")
        start_scheduler()


if __name__ == "__main__":
    main()
