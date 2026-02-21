import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from loguru import logger

MEMORY_PATH = Path("cache/news_memory.json")
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "src",
    "mkt",
    "oc",
    "aid",
}


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonicalize_url(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url.strip())
    query = parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = [(k, v) for k, v in query if k.lower() not in TRACKING_PARAMS]
    filtered_query.sort(key=lambda x: x[0])

    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]

    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        query=urlencode(filtered_query, doseq=True),
        fragment="",
    )
    return urlunparse(cleaned)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in lowered)
    return " ".join(cleaned.split())


def build_title_fingerprint(title: str) -> str:
    return _sha256(normalize_text(title))


def build_summary_fingerprint(summary: str) -> str:
    return _sha256(normalize_text(summary))


def load_memory(path: Path = MEMORY_PATH) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "entries": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("memory root is not dict")
        data.setdefault("version", 1)
        data.setdefault("entries", [])
        if not isinstance(data["entries"], list):
            data["entries"] = []
        return data
    except Exception as exc:
        logger.error(f"Fehler beim Laden von News-Memory: {exc}")
        return {"version": 1, "entries": []}


def save_memory(memory: Dict[str, Any], path: Path = MEMORY_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(memory, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except Exception as exc:
        logger.error(f"Fehler beim Speichern von News-Memory: {exc}")


def _parse_iso(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", ""))
    except Exception:
        return None


def prune_memory(memory: Dict[str, Any], retention_days: int) -> Dict[str, Any]:
    if retention_days <= 0:
        return memory

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    original_len = len(memory.get("entries", []))
    pruned_entries: List[Dict[str, Any]] = []

    for entry in memory.get("entries", []):
        sent_at = _parse_iso(entry.get("date_sent", ""))
        if sent_at is None or sent_at >= cutoff:
            pruned_entries.append(entry)

    memory["entries"] = pruned_entries
    removed = original_len - len(pruned_entries)
    if removed > 0:
        logger.info(f"News-Memory bereinigt: {removed} alte Einträge entfernt.")
    return memory


def entries_for_stock(memory: Dict[str, Any], stock_name: str, lookback_days: int) -> List[Dict[str, Any]]:
    entries = memory.get("entries", [])
    if lookback_days <= 0:
        return [e for e in entries if e.get("stock_name") == stock_name]

    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    selected: List[Dict[str, Any]] = []

    for entry in entries:
        if entry.get("stock_name") != stock_name:
            continue
        sent_at = _parse_iso(entry.get("date_sent", ""))
        if sent_at is None or sent_at >= cutoff:
            selected.append(entry)
    return selected


def is_exact_duplicate(
    stock_entries: List[Dict[str, Any]],
    canonical_url_hash: str,
    title_fingerprint: str,
    exact_url_dedupe: bool = True,
    exact_title_dedupe: bool = True,
) -> bool:
    for entry in stock_entries:
        if exact_url_dedupe and canonical_url_hash and entry.get("canonical_url_hash") == canonical_url_hash:
            return True
        if exact_title_dedupe and title_fingerprint and entry.get("title_fingerprint") == title_fingerprint:
            return True
    return False


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_semantic_match(
    stock_entries: List[Dict[str, Any]],
    candidate_embedding: Optional[List[float]],
    threshold: float,
) -> Optional[Dict[str, Any]]:
    if not candidate_embedding:
        return None

    best_entry = None
    best_score = 0.0
    for entry in stock_entries:
        ref_emb = entry.get("topic_embedding")
        if not isinstance(ref_emb, list):
            continue
        score = cosine_similarity(candidate_embedding, ref_emb)
        if score > best_score:
            best_score = score
            best_entry = entry

    if best_entry is not None and best_score >= threshold:
        return {"entry": best_entry, "score": best_score}
    return None


def build_memory_entry(
    stock_name: str,
    article: Dict[str, Any],
    summary_text: str,
    topic_embedding: Optional[List[float]],
    date_sent: Optional[str] = None,
) -> Dict[str, Any]:
    canonical_url = canonicalize_url(article.get("link", ""))
    return {
        "stock_name": stock_name,
        "date_sent": date_sent or _utc_now_iso(),
        "canonical_url_hash": _sha256(canonical_url) if canonical_url else "",
        "title_fingerprint": build_title_fingerprint(article.get("title", "")),
        "summary_fingerprint": build_summary_fingerprint(summary_text),
        "topic_embedding": topic_embedding or [],
        "summary_text": summary_text[:500],
        "source": article.get("source_name", ""),
        "link": article.get("link", ""),
        "title": article.get("title", ""),
    }


def record_sent_news(memory: Dict[str, Any], entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    memory.setdefault("entries", [])
    memory["entries"].extend(entries)
    return memory
