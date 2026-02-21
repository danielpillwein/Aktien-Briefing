import threading
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Dict, List

import yaml

SETTINGS_PATH = Path("config/settings.yaml")
BACKUP_DIR = Path("config/backups")
_SETTINGS_WRITE_LOCK = threading.Lock()


def load_settings_file(settings_path: Path = None) -> Dict[str, Any]:
    path = settings_path or SETTINGS_PATH
    if not path.exists():
        raise FileNotFoundError(f"settings.yaml fehlt unter {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def backup_settings(settings_path: Path = None) -> Path:
    path = settings_path or SETTINGS_PATH
    if not path.exists():
        raise FileNotFoundError(f"Datei für Backup nicht gefunden: {path}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = BACKUP_DIR / f"settings-{ts}.yaml"
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def save_settings_atomic(settings: Dict[str, Any], settings_path: Path = None) -> None:
    path = settings_path or SETTINGS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        yaml.safe_dump(
            settings,
            tmp,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _ensure_list_schema(settings: Dict[str, Any], list_name: str) -> List[Dict[str, str]]:
    if list_name not in ("portfolio", "watchlist"):
        raise ValueError(f"Ungültige Liste: {list_name}")

    settings.setdefault("portfolio", [])
    settings.setdefault("watchlist", [])

    if not isinstance(settings[list_name], list):
        raise ValueError(f"{list_name} hat ein ungültiges Format (muss eine Liste sein)")

    return settings[list_name]


def _ticker_in_list(items: List[Dict[str, Any]], ticker: str) -> bool:
    ticker_upper = ticker.upper()
    for item in items:
        if str(item.get("ticker", "")).upper() == ticker_upper:
            return True
    return False


def _find_duplicate_list(settings: Dict[str, Any], ticker: str) -> str:
    if _ticker_in_list(settings.get("portfolio", []), ticker):
        return "portfolio"
    if _ticker_in_list(settings.get("watchlist", []), ticker):
        return "watchlist"
    return ""


def add_stock(list_name: str, ticker: str, name: str) -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    name = name.strip()
    if not ticker or not name:
        raise ValueError("Ticker und Name sind erforderlich.")

    with _SETTINGS_WRITE_LOCK:
        settings = load_settings_file()
        target_list = _ensure_list_schema(settings, list_name)

        duplicate_list = _find_duplicate_list(settings, ticker)
        if duplicate_list:
            raise ValueError(f"Ticker {ticker} existiert bereits in {duplicate_list}.")

        target_list.append({"ticker": ticker, "name": name})

        backup_path = backup_settings()
        save_settings_atomic(settings)

    return {
        "list_name": list_name,
        "ticker": ticker,
        "name": name,
        "backup_path": str(backup_path),
    }


def remove_stock(list_name: str, ticker: str) -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    if not ticker:
        raise ValueError("Ticker ist erforderlich.")

    with _SETTINGS_WRITE_LOCK:
        settings = load_settings_file()
        target_list = _ensure_list_schema(settings, list_name)

        removed_item = None
        new_list = []
        for item in target_list:
            if removed_item is None and str(item.get("ticker", "")).upper() == ticker:
                removed_item = item
                continue
            new_list.append(item)

        if removed_item is None:
            raise KeyError(f"Ticker {ticker} ist nicht in {list_name} vorhanden.")

        settings[list_name] = new_list

        backup_path = backup_settings()
        save_settings_atomic(settings)

    return {
        "list_name": list_name,
        "ticker": ticker,
        "name": removed_item.get("name", ""),
        "backup_path": str(backup_path),
    }
