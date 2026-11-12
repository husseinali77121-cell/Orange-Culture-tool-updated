"""S/I/R normalisation.

Every engine receives the AST panel as {drug: value}. Values reach the engines
from three sources (manual entry, OCR, saved records) and are not guaranteed to
be the single upper-case letters the rules compare against. Before this module
existed a lower-case "r" - or the word "Resistant" - matched none of the
`== "R"` tests, so a RESISTANT drug fell through every rule and came out as a
recommended option. Normalise once, at the boundary, and the rules can stay
simple.
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

_WORDS = {
    "s": "S", "sensitive": "S", "susceptible": "S", "sens": "S", "حساس": "S",
    "i": "I", "intermediate": "I", "sdd": "I", "متوسط": "I",
    "susceptible, increased exposure": "I", "susceptible increased exposure": "I",
    "r": "R", "resistant": "R", "res": "R", "مقاوم": "R",
}

SIR_VALUES = ("S", "I", "R")


def normalize_sir(value: Any) -> Optional[str]:
    """Return "S" / "I" / "R", or None when `value` is not an S/I/R result."""
    if value is None:
        return None
    return _WORDS.get(str(value).strip().lower())


def normalize_sir_map(sir_map: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Copy of `sir_map` with every recognisable result folded to S / I / R.

    Entries that are not S/I/R results are kept as stripped text, because the
    panel also carries a few non-SIR observations the rules read by name
    (e.g. "D-test": "Negative"). Empty entries are dropped - an empty cell is
    "not tested", not a result.
    """
    out: Dict[str, Any] = {}
    for drug, value in (sir_map or {}).items():
        if drug is None:
            continue
        name = str(drug).strip()
        if not name:
            continue
        sir = normalize_sir(value)
        if sir is not None:
            out[name] = sir
        elif value is not None and str(value).strip():
            out[name] = str(value).strip()
    return out


def sir_of(sir_map: Mapping[str, Any], drug: str) -> Optional[str]:
    """S / I / R for `drug`, or None when it was not tested."""
    v = sir_map.get(drug)
    return v if v in SIR_VALUES else None
