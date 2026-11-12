"""Reconcile guideline agents quoted in free-text notes with the isolate AST."""
from __future__ import annotations

import re
from typing import Dict, Optional

from abx_guidelines import normalize_abx_key

# ── Empiric-regimen note annotation ─────────────────────────────────────────
# The TREATMENT_DURATION_DB "notes" field may quote guideline first-line agents
# (e.g. "3d TMP-SMX | 5d Nitrofurantoin | 3-7d FQ"). On a culture report those
# drug names MUST be reconciled with the patient's own AST — otherwise a drug
# that is Resistant, or was never tested, appears as if it were recommended.
# This annotator flags each quoted agent with its real susceptibility status.
_REGIMEN_TOKENS = [
    # (token as written in notes, [AST drug name(s) to check])
    ("TMP-SMX",        ["Trimethoprim/Sulfamethoxazole"]),
    ("Nitrofurantoin", ["Nitrofurantoin"]),
    ("Fosfomycin",     ["Fosfomycin"]),
    ("FQ",             ["Ciprofloxacin", "Ofloxacin", "Norfloxacin",
                        "Levofloxacin", "Gatifloxacin", "Moxifloxacin"]),
]


def _sir_lookup(drug: str, sir_map: Dict[str, str]) -> Optional[str]:
    """Return S/I/R for `drug` from sir_map, matching keys tolerantly."""
    if not sir_map:
        return None
    try:
        from abx_guidelines import normalize_abx_key
        target = normalize_abx_key(drug)
        for k, v in sir_map.items():
            if normalize_abx_key(k) == target:
                return ((v or "").strip().upper()[:1]) or None
    except Exception:
        low = {k.lower(): v for k, v in sir_map.items()}
        val = low.get(drug.lower())
        return ((val or "").strip().upper()[:1]) or None
    return None


def _regimen_token_status(drug_names, sir_map) -> str:
    """Aggregate AST status for one token. For a class, S wins, then I, then R,
    else 'NT' (not tested / not on the panel)."""
    seen = [s for s in (_sir_lookup(d, sir_map) for d in drug_names) if s]
    if not seen:
        return "NT"
    if "S" in seen:
        return "S"
    if "I" in seen:
        return "I"
    return "R"


def annotate_regimen_note(note: str, sir_map: Dict[str, str], lang: str = "ar") -> str:
    """Insert an AST-status flag after each guideline agent quoted in `note`.
    Sensitive agents are left unflagged; Resistant / Intermediate / not-tested
    agents are marked so the note can never contradict the antibiogram."""
    if not note or not sir_map:
        return note
    flags = {
        "R":  " ⚠️[R — مقاوم في هذه المزرعة]" if lang == "ar" else " ⚠️[R — resistant here]",
        "I":  " [I]",
        "NT": " [غير مُختبر]" if lang == "ar" else " [not tested]",
        # "S" is intentionally left unflagged.
    }
    out = note
    for token, drugs in _REGIMEN_TOKENS:
        if token not in out:
            continue
        flag = flags.get(_regimen_token_status(drugs, sir_map), "")
        if not flag:
            continue
        out = re.sub(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])",
                     lambda m: m.group(0) + flag, out, count=1)
    return out
