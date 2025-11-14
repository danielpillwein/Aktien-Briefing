import feedparser
import asyncio
from loguru import logger
from urllib.parse import quote_plus
from utils.preprocess import clean_title, remove_boilerplate, limit_length

# ================================================================
# Newsquellen (Stage 5)
# ================================================================
SOURCES = [
    "https://news.google.com/rss/search?q={query}+stock&hl=en-US&gl=US&ceid=US:en",
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={query}&region=US&lang=en-US",
    "https://www.bing.com/news/search?q={query}+stock&format=rss"
]


# ================================================================
# Einzelne Quelle abrufen
# ================================================================
def fetch_source(url: str):
    feed = feedparser.parse(url)
    results = []

    for e in feed.entries[:5]:  # harte Begrenzung für Speed & Kosten
        content = e.get("summary", "") or e.get("description", "")

        article = {
            "title": clean_title(e.title),
            "content": limit_length(remove_boilerplate(content)),
            "link": e.link,
        }
        results.append(article)

    return results


# ================================================================
# ALLE Quellen parallel abrufen
# ================================================================
async def fetch_all_sources(name: str):
    """Holt News für eine Aktie (Stage 5)."""

    # Kritisch: URL-ENCODING!
    encoded_query = quote_plus(name)

    # URLs bauen
    urls = [src.format(query=encoded_query) for src in SOURCES]

    # Parsen parallel ausführen
    tasks = [asyncio.to_thread(fetch_source, url) for url in urls]
    results_per_source = await asyncio.gather(*tasks)

    # Flach machen
    all_articles = [item for sub in results_per_source for item in sub]

    logger.info(f"{name}: {len(all_articles)} Artikel geladen.")

    return all_articles
