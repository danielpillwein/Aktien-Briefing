import json
from pathlib import Path
from loguru import logger

CACHE_FILE = Path("cache/cache.json")
CACHE_FILE.parent.mkdir(exist_ok=True, parents=True)


def load_cache():
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Fehler beim Laden des Caches: {e}")
        return {}


def save_cache(cache: dict):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Caches: {e}")


def get_cached_result(cache: dict, key: str):
    return cache.get(key)


def set_cached_result(cache: dict, key: str, value):
    cache[key] = value
