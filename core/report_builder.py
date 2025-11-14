from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from datetime import datetime
from loguru import logger

def render_report(data: dict) -> Path:
    """Erstellt einen Markdown-Report aus den Briefing-Daten."""
    try:
        template_dir = Path("templates")
        output_dir = Path("outputs/briefings")
        output_dir.mkdir(parents=True, exist_ok=True)

        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template("briefing.md.j2")

        report_date = datetime.now().strftime("%Y-%m-%d")
        rendered = template.render(
            portfolio=data["portfolio"],
            watchlist=data["watchlist"],
            news=data["news"],
            overview=data["overview"],
            date=data["date"],
        )

        output_path = output_dir / f"{report_date}.md"
        output_path.write_text(rendered, encoding="utf-8")

        logger.info(f"📄 Briefing gespeichert unter: {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Fehler beim Rendern des Reports: {e}")
        return None
