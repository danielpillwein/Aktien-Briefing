import argparse
from core.briefing_agent import run_briefing_test
from core.scheduler import start_scheduler

def main():
    parser = argparse.ArgumentParser(description="AI-Aktienbriefing-Agent")
    parser.add_argument("--test", action="store_true",
                        help="Führt den Agenten sofort aus (Testmodus)")
    args = parser.parse_args()

    if args.test:
        run_briefing_test()
    else:
        start_scheduler()

if __name__ == "__main__":
    main()
