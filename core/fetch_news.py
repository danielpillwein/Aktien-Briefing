import feedparser
import yfinance as yf
from loguru import logger
from typing import Dict, List
from pydantic import BaseModel
import time


class NewsItem(BaseModel):
    title: str
    link: str
    source: str


def fetch_rss_news(symbol: str, max_items: int = 5) -> List[NewsItem]:
    """Holt Finanznachrichten über Google News RSS als Fallback."""
    feeds = [
        f"https://news.google.com/rss/search?q={symbol}+stock",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    ]
    articles = []

    for feed_url in feeds:
        try:
            parsed = feedparser.parse(feed_url)
            for entry in parsed.entries[:max_items]:
                title = entry.get("title")
                link = entry.get("link")
                if not title or not link:
                    continue
                articles.append(
                    NewsItem(title=title, link=link, source=feed_url.split("/")[2])
                )
        except Exception as e:
            logger.error(f"RSS error for {symbol}: {e}")
        time.sleep(0.3)

    return articles


def fetch_yf_news(symbol: str, max_items: int = 5) -> List[NewsItem]:
    """
    Holt Nachrichten über die Yahoo Finance API via yfinance.
    Falls Datenstruktur fehlerhaft, wird leer zurückgegeben.
    """
    try:
        ticker = yf.Ticker(symbol)
        news = getattr(ticker, "news", [])
        if not isinstance(news, list) or len(news) == 0:
            return []

        articles = []
        for n in news[:max_items]:
            title = n.get("title")
            link = n.get("link")
            if not title or not link:
                # Daten fehlerhaft → ignorieren
                continue
            articles.append(NewsItem(title=title, link=link, source="Yahoo Finance"))

        return articles
    except Exception as e:
        logger.error(f"Yahoo news error for {symbol}: {e}")
        return []


def get_all_news(symbols: List[str], prefer_yf: bool = True) -> Dict[str, List[NewsItem]]:
    """Holt News für mehrere Aktien, robust mit Yahoo+RSS Fallback."""
    all_news: Dict[str, List[NewsItem]] = {}

    for sym in symbols:
        try:
            articles = fetch_yf_news(sym) if prefer_yf else []
            if not articles:
                articles = fetch_rss_news(sym)
            all_news[sym] = articles
            if not articles:
                logger.warning(f"Keine News für {sym}")
        except Exception as e:
            logger.error(f"Unbekannter Fehler bei {sym}: {e}")
    return all_news
