from pathlib import Path
import yaml

SETTINGS_PATH = Path("config/settings.yaml")


def load_settings() -> dict:
    """Lädt die Einstellungen aus config/settings.yaml."""
    if not SETTINGS_PATH.exists():
        raise FileNotFoundError(f"settings.yaml fehlt unter {SETTINGS_PATH}")

    with SETTINGS_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
