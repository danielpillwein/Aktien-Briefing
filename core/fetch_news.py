import feedparser
from loguru import logger
from typing import Dict, List
from pydantic import BaseModel
import time
import urllib.parse


class NewsItem(BaseModel):
    title: str
    link: str
    source: str


def fetch_rss_news(name: str, max_items: int = 5) -> List[NewsItem]:
    """
    Holt Nachrichten ausschließlich über RSS:
    - Google News RSS
    - Yahoo Finance RSS (nicht über API!)

    Query basiert immer auf dem Firmennamen.
    """
    safe_query = urllib.parse.quote_plus(f"{name} stock")

    feeds = [
        f"https://news.google.com/rss/search?q={safe_query}",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={safe_query}&region=US&lang=en-US",
    ]

    articles: List[NewsItem] = []

    for feed_url in feeds:
        try:
            parsed = feedparser.parse(feed_url)

            if not parsed.entries:
                continue

            for entry in parsed.entries[:max_items]:
                title = entry.get("title")
                link = entry.get("link")

                if not title or not link:
                    continue

                articles.append(
                    NewsItem(
                        title=title,
                        link=link,
                        source=feed_url.split("/")[2],
                    )
                )

        except Exception as e:
            logger.error(f"RSS error for '{name}': {e}")

        time.sleep(0.25)

    return articles


def get_all_news(items: List[dict]) -> Dict[str, List[NewsItem]]:
    """
    Holt Nachrichten für mehrere Aktien basierend auf:
    ticker = interner Key
    name   = RSS-Suchbegriff
    Rückgabe: {ticker: [NewsItem, ...]}
    """
    all_news: Dict[str, List[NewsItem]] = {}

    for item in items:
        ticker = item["ticker"]
        name = item["name"]

        try:
            news = fetch_rss_news(name)
            all_news[ticker] = news

            if not news:
                logger.warning(f"Keine News gefunden für {name} ({ticker})")

        except Exception as e:
            logger.error(f"Error fetching news for {name} ({ticker}): {e}")
            all_news[ticker] = []

    return all_news
