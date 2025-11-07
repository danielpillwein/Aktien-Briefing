from loguru import logger
import sys
from pathlib import Path

Path("outputs").mkdir(exist_ok=True)

logger.remove()
logger.add(sys.stdout, colorize=True, format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
logger.add("outputs/logs.log", rotation="1 MB", level="INFO")


def get_logger(name: str):
    return logger.bind(name=name)
