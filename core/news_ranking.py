from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List
from urllib.parse import urlparse


DEFAULT_WEIGHTS = {
    "recency": 0.35,
    "entity": 0.25,
    "source_quality": 0.2,
    "information_density": 0.1,
    "macro_signal": 0.1,
}

SOURCE_QUALITY_HINTS = {
    "reuters": 95,
    "bloomberg": 92,
    "wsj": 90,
    "financial times": 90,
    "marketwatch": 80,
    "yahoo": 72,
    "google news": 65,
    "bing": 60,
    "seeking alpha": 65,
    "motley fool": 60,
}

MACRO_KEYWORDS = (
    "inflation",
    "zins",
    "rate",
    "yield",
    "cpi",
    "pmi",
    "recession",
    "rezession",
    "oil",
    "gas",
    "tariff",
    "zoll",
    "krieg",
    "conflict",
    "sanction",
)


def _parse_published(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)

    raw = str(value).strip()
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            continue
    return datetime.now(timezone.utc)


def _score_recency(published_at: str) -> int:
    dt = _parse_published(published_at)
    age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)

    if age_hours <= 6:
        return 100
    if age_hours <= 24:
        return 90
    if age_hours <= 48:
        return 75
    if age_hours <= 96:
        return 55
    if age_hours <= 168:
        return 35
    return 15


def _score_entity_match(stock_name: str, text: str) -> int:
    if not stock_name:
        return 40

    stock_tokens = [t.lower() for t in stock_name.replace("(", " ").replace(")", " ").split() if t.strip()]
    if not stock_tokens:
        return 40

    lower = text.lower()
    hits = sum(1 for token in stock_tokens if token in lower)
    if hits == 0:
        return 20
    if hits == 1:
        return 55
    if hits == 2:
        return 80
    return 95


def _score_source_quality(article: Dict[str, Any]) -> int:
    source_name = str(article.get("source_name", "")).lower()
    link = str(article.get("link", "")).lower()
    domain = urlparse(link).netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]

    text = f"{source_name} {domain}"
    for hint, score in SOURCE_QUALITY_HINTS.items():
        if hint in text:
            return score
    return 50


def _score_information_density(text: str) -> int:
    lower = text.lower()
    score = 30

    number_tokens = sum(ch.isdigit() for ch in lower)
    if number_tokens >= 10:
        score += 25
    elif number_tokens >= 5:
        score += 15

    for marker in ("%", "billion", "million", "guidance", "outlook", "earnings"):
        if marker in lower:
            score += 7
    return max(0, min(100, score))


def _score_macro_signal(text: str) -> int:
    lower = text.lower()
    hits = sum(1 for kw in MACRO_KEYWORDS if kw in lower)
    if hits == 0:
        return 25
    if hits == 1:
        return 55
    if hits == 2:
        return 75
    return 90


def _weights_from_cfg(cfg: Dict[str, Any]) -> Dict[str, float]:
    configured = cfg.get("weights", {}) if isinstance(cfg, dict) else {}
    weights = dict(DEFAULT_WEIGHTS)
    for key in weights:
        try:
            val = float(configured.get(key, weights[key]))
            weights[key] = max(0.0, min(1.0, val))
        except Exception:
            continue

    weight_sum = sum(weights.values()) or 1.0
    return {k: v / weight_sum for k, v in weights.items()}


def score_article_relevance(stock_name: str, article: Dict[str, Any], ranking_cfg: Dict[str, Any]) -> float:
    text = f"{article.get('title', '')}\n{article.get('content', '')}"
    weights = _weights_from_cfg(ranking_cfg)

    recency = _score_recency(str(article.get("published_at", "")))
    entity = _score_entity_match(stock_name, text)
    source_quality = _score_source_quality(article)
    info_density = _score_information_density(text)
    macro_signal = _score_macro_signal(text)

    score = (
        recency * weights["recency"]
        + entity * weights["entity"]
        + source_quality * weights["source_quality"]
        + info_density * weights["information_density"]
        + macro_signal * weights["macro_signal"]
    )
    return round(float(score), 2)


def rank_articles_for_stock(
    stock_name: str,
    articles: List[Dict[str, Any]],
    ranking_cfg: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not articles:
        return []

    min_score = float(ranking_cfg.get("min_relevance_score", 0))
    max_candidates = int(ranking_cfg.get("max_candidates_per_stock", len(articles)))
    ranked: List[Dict[str, Any]] = []

    for article in articles:
        item = dict(article)
        score = score_article_relevance(stock_name, item, ranking_cfg)
        item["relevance_score"] = score
        if score >= min_score:
            ranked.append(item)

    ranked.sort(
        key=lambda x: (
            float(x.get("relevance_score", 0)),
            str(x.get("published_at", "")),
        ),
        reverse=True,
    )
    return ranked[: max(0, max_candidates)]
