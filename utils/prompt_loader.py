from pathlib import Path
import yaml

# --- SafeDict für teilweises Formatieren ---
class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"

# Sprache laden
with open(Path("config/settings.yaml"), "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)
LANG = settings.get("language", "de")

def load_prompt(name: str) -> str:
    """
    Lädt einen Prompt aus config/prompts/
    und ersetzt NUR {language}, ohne andere Platzhalter zu löschen.
    """
    path = Path("config/prompts") / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt-Datei {name}.txt fehlt unter config/prompts/")

    raw = path.read_text(encoding="utf-8")

    # Nur {language} ersetzen, alle anderen Platzhalter unverändert lassen
    return raw.format_map(SafeDict(language=LANG))
