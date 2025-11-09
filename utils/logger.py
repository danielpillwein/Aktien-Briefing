from loguru import logger
from datetime import datetime
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True, parents=True)

logfile = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"

logger.remove()
logger.add(logfile, rotation="00:00", encoding="utf-8", enqueue=True)
logger.add(lambda msg: print(msg, end=""))  # Console-Output bleibt

def get_logger(name: str):
    return logger.bind(module=name)
