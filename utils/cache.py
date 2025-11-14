import json
import os
from pathlib import Path
from loguru import logger

CACHE_PATH = Path("cache/cache.json")

# internes Dictionary (In-Memory Cache)
_cache = {}

# ---------------------------------------------------------
# Lade Cache beim Start
# ---------------------------------------------------------
def load_cache():
    global _cache

    if not CACHE_PATH.exists():
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text("{}", encoding="utf-8")
        _cache = {}
        return _cache

    try:
        _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"Fehler beim Laden des Caches: {e}")
        _cache = {}

    return _cache


# Direkt beim Import initialisieren
load_cache()


# ---------------------------------------------------------
# Hole Wert aus Cache
# ---------------------------------------------------------
def get_cache(key: str):
    return _cache.get(key)


# ---------------------------------------------------------
# Setze Wert im Cache + speichere automatisch
# ---------------------------------------------------------
def set_cache(key: str, value):
    _cache[key] = value
    save_cache()


# ---------------------------------------------------------
# Schreibe Cache auf Disk
# ---------------------------------------------------------
def save_cache():
    try:
        CACHE_PATH.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"Fehler beim Speichern des Caches: {e}")
