from pathlib import Path

def load_prompt(name: str) -> str:
    """Lädt einen Prompt aus config/prompts/."""
    path = Path("config/prompts") / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt-Datei {name}.txt fehlt unter config/prompts/")
    return path.read_text(encoding="utf-8")