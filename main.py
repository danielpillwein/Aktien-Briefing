import argparse
from core.briefing_agent import run_briefing_test
from core.scheduler import start_scheduler
from loguru import logger

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
        run_briefing_test()
    else:
        logger.info("🕓 Starte Scheduler-Modus...")
        start_scheduler()

if __name__ == "__main__":
    main()
