from typing import Any, Dict, List


MACRO_EVENT_TYPES = {"geopolitical", "macro", "policy", "commodity"}

KNOWN_SECTOR_MAP = {
    "alphabet": "Communication Services",
    "microsoft": "Technology",
    "nvidia": "Semiconductors",
    "tsmc": "Semiconductors",
    "siemens energy": "Industrials",
    "visa": "Financials",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _infer_sector(stock_item: Dict[str, Any]) -> str:
    if stock_item.get("sector"):
        return str(stock_item["sector"])
    name = str(stock_item.get("name", "")).lower()
    for key, sector in KNOWN_SECTOR_MAP.items():
        if key in name:
            return sector
    return "Unknown"


def _is_macro_signal(signal: Dict[str, Any]) -> bool:
    event_type = str(signal.get("event_type", "")).lower()
    if event_type in MACRO_EVENT_TYPES:
        return True

    text = " ".join(
        [
            str(signal.get("macro_impact", "")),
            str(signal.get("direct_effect", "")),
            str(signal.get("event", "")),
        ]
    ).lower()
    keywords = ("inflation", "zins", "rate", "oil", "gas", "krieg", "tariff", "sanction", "yield")
    return any(k in text for k in keywords)


def build_macro_overview(
    portfolio_items: List[Dict[str, Any]],
    watchlist_items: List[Dict[str, Any]],
    news_bundle: Dict[str, Any],
) -> Dict[str, Any]:
    all_items = list(portfolio_items) + list(watchlist_items)
    exposure_map = {str(item.get("name", "")): _infer_sector(item) for item in all_items}

    grouped: Dict[str, Dict[str, Any]] = {}
    for section in ("portfolio", "watchlist"):
        section_data = news_bundle.get(section, {})
        for stock_name, stock_data in section_data.items():
            for signal in stock_data.get("items", []):
                if not _is_macro_signal(signal):
                    continue
                key = str(signal.get("event", "")).strip().lower()
                if not key:
                    continue
                if key not in grouped:
                    grouped[key] = {
                        "factor": signal.get("event", ""),
                        "mechanism": signal.get("direct_effect", ""),
                        "macro_impact": signal.get("macro_impact", ""),
                        "market_reaction": signal.get("market_reaction", ""),
                        "event_types": set(),
                        "affected_sectors": set(signal.get("affected_sectors", []) or []),
                        "affected_holdings": set(),
                        "sources": [],
                        "weight": 0.0,
                        "confidence": signal.get("confidence", "medium"),
                        "time_horizon": signal.get("time_horizon", "short"),
                    }
                grouped[key]["weight"] += _safe_float(signal.get("impact_score", 0)) * 0.6 + _safe_float(
                    signal.get("relevance_score", 0)
                ) * 0.4
                grouped[key]["event_types"].add(str(signal.get("event_type", "other")).lower())
                grouped[key]["affected_holdings"].add(stock_name)
                link = str(signal.get("link", "")).strip()
                if link and link not in grouped[key]["sources"]:
                    grouped[key]["sources"].append(link)
                stock_sector = exposure_map.get(stock_name, "Unknown")
                if stock_sector != "Unknown":
                    grouped[key]["affected_sectors"].add(stock_sector)

    factors = sorted(grouped.values(), key=lambda x: x["weight"], reverse=True)[:3]
    normalized = []
    for factor in factors:
        normalized.append(
            {
                "factor": factor["factor"],
                "mechanism": factor["mechanism"],
                "macro_impact": factor["macro_impact"],
                "market_reaction": factor["market_reaction"],
                "event_type": sorted(factor["event_types"])[0] if factor["event_types"] else "other",
                "affected_sectors": sorted(factor["affected_sectors"]),
                "affected_holdings": sorted(factor["affected_holdings"]),
                "confidence": factor["confidence"],
                "time_horizon": factor["time_horizon"],
                "weight": round(float(factor["weight"]), 2),
                "sources": list(factor["sources"]),
            }
        )

    if not normalized:
        return {
            "factors": [],
            "summary": "Keine dominanten neuen Makro- oder Geopolitik-Treiber erkannt.",
        }

    headline = normalized[0]
    summary = (
        f"Hauptfaktor: {headline['factor']} -> {headline['macro_impact']} -> "
        f"betroffen: {', '.join(headline['affected_holdings'])}."
    )
    return {"factors": normalized, "summary": summary}
