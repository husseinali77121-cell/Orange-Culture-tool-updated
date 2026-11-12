"""Small shared helpers with no clinical content."""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any, Dict, List

__all__ = ["fuzzy_match", "safe_int", "get_route_label", "uniq_keep_order", "build_banned_item"]

logger = logging.getLogger("orange_lab.engines")

def fuzzy_match(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 100.0
    return SequenceMatcher(None, a, b).ratio() * 100

def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception as _exc:
        logger.debug("suppressed exception: %s", _exc)
        return default


def get_route_label(item: Dict[str, Any]) -> str:
    return "🟢 Oral preferred / PO-friendly" if item.get("high_po") else "💉 IV/IM only"

def uniq_keep_order(items: List[str]) -> List[str]:
    seen:   set       = set()
    result: List[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


def build_banned_item(name: str, category: str, reason_short: str, reason_detail: str,
                      reason_short_en: str = "", reason_detail_en: str = "") -> Dict[str, str]:
    """One entry on the AVOID list, in both languages.

    The English report used to be produced by running the Arabic text through a
    word-substitution table (reports._ar2en) and DELETING whatever the table did
    not know. That turned real clinical statements into fragments — "المزرعة
    أثبتت أن Ceftriaxone لا يثبط نمو الجرثومة" came out as "Ceftriaxone no ." —
    and, worse, occasionally inverted the meaning. Clinical text must be authored
    in each language, never machine-mangled out of the other one, so every
    banned item now carries its own English wording.

    The `*_en` arguments default to the Arabic so an un-migrated call site
    degrades to today's behaviour instead of emitting an empty reason; reports.py
    prefers `*_en` when present and only falls back to _ar2en otherwise.
    """
    return {"name": name, "category": category,
            "reason_short": reason_short, "reason_detail": reason_detail,
            "reason_short_en":  reason_short_en  or reason_short,
            "reason_detail_en": reason_detail_en or reason_detail}
