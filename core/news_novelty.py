import asyncio
import hashlib
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from loguru import logger
from openai import AsyncOpenAI

from utils.news_memory import (
    build_title_fingerprint,
    canonicalize_url,
    entries_for_stock,
    find_semantic_match,
    is_exact_duplicate,
    normalize_text,
)

load_dotenv()

_embedding_client = None
_embedding_client_loop = None
_embedding_semaphore = None
_embedding_semaphore_loop = None
_EMBEDDING_BATCH_SIZE = 32
_EMBEDDING_MODEL = "text-embedding-3-small"


def _get_embedding_client() -> AsyncOpenAI:
    global _embedding_client, _embedding_client_loop
    loop = asyncio.get_running_loop()
    if _embedding_client is None or _embedding_client_loop is not loop:
        _embedding_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        _embedding_client_loop = loop
    return _embedding_client


def _get_embedding_semaphore(max_concurrent: int = 3) -> asyncio.Semaphore:
    global _embedding_semaphore, _embedding_semaphore_loop
    loop = asyncio.get_running_loop()
    if _embedding_semaphore is None or _embedding_semaphore_loop is not loop:
        _embedding_semaphore = asyncio.Semaphore(max_concurrent)
        _embedding_semaphore_loop = loop
    return _embedding_semaphore


def _embedding_input(article: Dict[str, Any]) -> str:
    title = article.get("title", "")
    content = article.get("content", "")
    return normalize_text(f"{title}\n{content[:1000]}")


async def _embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    if not texts:
        return []
    try:
        vectors: List[List[float]] = []
        client = _get_embedding_client()
        semaphore = _get_embedding_semaphore()

        for idx in range(0, len(texts), _EMBEDDING_BATCH_SIZE):
            batch = texts[idx:idx + _EMBEDDING_BATCH_SIZE]
            async with semaphore:
                response = await client.embeddings.create(
                    model=_EMBEDDING_MODEL,
                    input=batch,
                )
            vectors.extend([item.embedding for item in response.data])
        return vectors
    except Exception as exc:
        logger.warning(f"Embedding-Fehler, falle auf Exact-Dedupe zurück: {exc}")
        return None


async def filter_news_by_novelty(
    stock_name: str,
    raw_articles: List[Dict[str, Any]],
    memory: Dict[str, Any],
    cfg: Dict[str, Any],
) -> Dict[str, Any]:
    lookback_days = int(cfg.get("lookback_days", 14))
    semantic_threshold = float(cfg.get("semantic_threshold", 0.86))
    exact_url_dedupe = bool(cfg.get("exact_url_dedupe", True))
    exact_title_dedupe = bool(cfg.get("exact_title_dedupe", True))

    stock_entries = entries_for_stock(memory, stock_name, lookback_days)

    stats = {
        "fetched": len(raw_articles),
        "exact_dupes": 0,
        "semantic_dupes": 0,
        "new_count": 0,
    }

    candidates: List[Dict[str, Any]] = []
    suppressed_known_topics: List[Dict[str, Any]] = []

    seen_url_hashes = set()
    seen_title_fingerprints = set()

    for article in raw_articles:
        canonical_url = canonicalize_url(article.get("link", ""))
        url_hash = hashlib.sha256(canonical_url.encode("utf-8")).hexdigest() if canonical_url else ""
        title_fp = build_title_fingerprint(article.get("title", ""))

        exact_duplicate_in_run = (
            (exact_url_dedupe and url_hash and url_hash in seen_url_hashes)
            or (exact_title_dedupe and title_fp and title_fp in seen_title_fingerprints)
        )
        exact_duplicate_in_memory = is_exact_duplicate(
            stock_entries,
            url_hash,
            title_fp,
            exact_url_dedupe=exact_url_dedupe,
            exact_title_dedupe=exact_title_dedupe,
        )

        if exact_duplicate_in_run or exact_duplicate_in_memory:
            stats["exact_dupes"] += 1
            suppressed_known_topics.append({
                "title": article.get("title", ""),
                "link": article.get("link", ""),
                "reason": "exact_duplicate",
            })
            continue

        seen_url_hashes.add(url_hash)
        seen_title_fingerprints.add(title_fp)

        article["_canonical_url_hash"] = url_hash
        article["_title_fingerprint"] = title_fp
        candidates.append(article)

    if not candidates:
        return {
            "new_items": [],
            "suppressed_known_topics": suppressed_known_topics,
            "stats": stats,
            "candidate_embeddings": [],
        }

    embed_inputs = [_embedding_input(a) for a in candidates]
    embeddings = await _embed_texts(embed_inputs)

    new_items: List[Dict[str, Any]] = []
    new_item_embeddings: List[List[float]] = []
    known_semantic_embeddings: List[List[float]] = []

    for idx, article in enumerate(candidates):
        candidate_embedding = embeddings[idx] if embeddings else None

        semantic_match_memory = find_semantic_match(
            stock_entries,
            candidate_embedding,
            semantic_threshold,
        ) if embeddings else None

        semantic_match_run = None
        if embeddings and candidate_embedding and new_item_embeddings:
            best_score = 0.0
            for emb in new_item_embeddings + known_semantic_embeddings:
                # local import to avoid duplicate utility functions
                from utils.news_memory import cosine_similarity
                score = cosine_similarity(candidate_embedding, emb)
                if score > best_score:
                    best_score = score
            if best_score >= semantic_threshold:
                semantic_match_run = {"score": best_score}

        if semantic_match_memory or semantic_match_run:
            stats["semantic_dupes"] += 1
            match_score = (
                semantic_match_memory.get("score")
                if semantic_match_memory
                else semantic_match_run.get("score")
            )
            suppressed_known_topics.append({
                "title": article.get("title", ""),
                "link": article.get("link", ""),
                "reason": "semantic_duplicate",
                "similarity": round(float(match_score), 4) if match_score is not None else None,
            })
            if candidate_embedding:
                known_semantic_embeddings.append(candidate_embedding)
            continue

        article["_novelty_embedding"] = candidate_embedding or []
        new_items.append(article)
        if candidate_embedding:
            new_item_embeddings.append(candidate_embedding)

    stats["new_count"] = len(new_items)

    return {
        "new_items": new_items,
        "suppressed_known_topics": suppressed_known_topics,
        "stats": stats,
        "candidate_embeddings": embeddings or [],
    }
