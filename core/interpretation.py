from typing import Any, Dict, List, Optional


SENTIMENT_WEIGHT = {"positiv": 1.0, "neutral": 0.0, "negativ": -1.0}
CONFIDENCE_FACTOR = {"low": 0.75, "medium": 1.0, "high": 1.2}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_change(change: Optional[str]) -> float:
    if not change:
        return 0.0
    raw = str(change).replace("%", "").replace(",", ".").strip()
    return _safe_float(raw, 0.0)


def _driver_key(signal: Dict[str, Any]) -> str:
    event = str(signal.get("event", "")).strip().lower()
    if event:
        return event
    return str(signal.get("stock_specific_impact", "")).strip().lower()


def _driver_weight(signal: Dict[str, Any]) -> float:
    relevance = _safe_float(signal.get("relevance_score", 0), 0.0)
    impact = _safe_float(signal.get("impact_score", 0), 0.0)
    base = relevance * 0.4 + impact * 0.6
    conf = CONFIDENCE_FACTOR.get(str(signal.get("confidence", "medium")).lower(), 1.0)
    return base * conf


def _aggregate_sentiment(signals: List[Dict[str, Any]], horizon: str) -> float:
    total_weight = 0.0
    weighted_sum = 0.0
    for s in signals:
        s_horizon = str(s.get("time_horizon", "")).lower()
        if horizon == "short" and s_horizon not in ("short", "medium"):
            continue
        if horizon == "long" and s_horizon not in ("medium", "long"):
            continue

        sentiment_value = SENTIMENT_WEIGHT.get(str(s.get("sentiment", "neutral")).lower(), 0.0)
        weight = _driver_weight(s)
        weighted_sum += sentiment_value * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    return weighted_sum / total_weight


def _label_from_score(score: float) -> str:
    if score > 0.2:
        return "positiv"
    if score < -0.2:
        return "negativ"
    return "neutral"


def _build_horizon_text(label: str, horizon: str) -> str:
    if horizon == "short":
        if label == "positiv":
            return "Kurzfristig überwiegen positive Treiber."
        if label == "negativ":
            return "Kurzfristig dominiert Risiko- und Abwärtsdruck."
        return "Kurzfristig ist das Bild ausgeglichen."
    if label == "positiv":
        return "Langfristig sprechen die Treiber für einen konstruktiven Pfad."
    if label == "negativ":
        return "Langfristig bleibt das Chance-Risiko-Verhältnis belastet."
    return "Langfristig ist die Wirkung eher neutral."


def _explain_price_move(change: float, short_label: str) -> str:
    if change <= -0.5 and short_label == "negativ":
        return "Die negative Kursbewegung ist fundamental weitgehend erklärbar."
    if change >= 0.5 and short_label == "positiv":
        return "Die positive Kursbewegung wird durch die identifizierten Treiber gestützt."
    if abs(change) < 0.5:
        return "Die Kursbewegung ist klein; Signale sind gemischt bzw. noch nicht voll eingepreist."
    return "Kursbewegung und Nachrichtenlage laufen nur teilweise synchron; technische Faktoren sind möglich."


def build_stock_interpretation(
    stock_name: str,
    stock_change: Optional[str],
    signals: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not signals:
        return {
            "stock_name": stock_name,
            "price_change": stock_change or "0.00%",
            "top_drivers": [],
            "short_term": "Keine belastbaren neuen Treiber erkannt.",
            "long_term": "Keine belastbare langfristige Ableitung verfügbar.",
            "price_move_explained": "Keine Interpretation möglich, da keine neuen Signale vorliegen.",
            "overall": "neutral",
        }

    grouped: Dict[str, Dict[str, Any]] = {}
    for signal in signals:
        key = _driver_key(signal)
        if key not in grouped:
            grouped[key] = {
                "event": signal.get("event", ""),
                "event_type": signal.get("event_type", "other"),
                "causal_chain": signal.get("causal_chain", ""),
                "direct_effect": signal.get("direct_effect", ""),
                "macro_impact": signal.get("macro_impact", ""),
                "market_reaction": signal.get("market_reaction", ""),
                "stock_specific_impact": signal.get("stock_specific_impact", ""),
                "time_horizon": signal.get("time_horizon", "short"),
                "confidence": signal.get("confidence", "low"),
                "weight": 0.0,
                "sources": [],
            }
        grouped[key]["weight"] += _driver_weight(signal)
        link = signal.get("link")
        if link and link not in grouped[key]["sources"]:
            grouped[key]["sources"].append(link)

    drivers = sorted(grouped.values(), key=lambda x: x["weight"], reverse=True)[:3]
    total_weight = sum(d["weight"] for d in drivers) or 1.0
    for d in drivers:
        d["weight_pct"] = round((d["weight"] / total_weight) * 100, 1)

    change_num = _parse_change(stock_change)
    short_score = _aggregate_sentiment(signals, "short")
    long_score = _aggregate_sentiment(signals, "long")
    short_label = _label_from_score(short_score)
    long_label = _label_from_score(long_score)

    return {
        "stock_name": stock_name,
        "price_change": stock_change or "0.00%",
        "top_drivers": drivers,
        "short_term": _build_horizon_text(short_label, "short"),
        "long_term": _build_horizon_text(long_label, "long"),
        "price_move_explained": _explain_price_move(change_num, short_label),
        "overall": short_label,
    }
