from pathlib import Path
import yaml

with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)
LANG = settings.get("language", "de")

def load_prompt(name: str) -> str:
    """
    Lädt Prompt-Datei und ersetzt nur {language} –
    ohne Python-Format-Parsing, vollständig sicher.
    """
    path = Path("config/prompts") / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt {name}.txt fehlt!")

    raw = path.read_text(encoding="utf-8")

    # Manuelles Ersetzen ohne format()
    raw = raw.replace("{language}", LANG)

    return raw
