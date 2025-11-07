import argparse
from core.briefing_agent import run_briefing_test


def main():
    parser = argparse.ArgumentParser(description="AI Aktienbriefing Agent")
    parser.add_argument("--test", action="store_true", help="Führt den Agenten im Testmodus aus")
    args = parser.parse_args()

    if args.test:
        run_briefing_test()
    else:
        print("Scheduler-Mode folgt in Phase 6.")


if __name__ == "__main__":
    main()
