"""Finding = one rule's verdict on one drug."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

# Severity ranks. Higher wins. The four non-zero levels map 1:1 onto the four
# output lists the UI and the reports already consume.
TAG, WARN, PREG, BAN = 0, 1, 2, 3
SEVERITY_NAME = {TAG: "note", WARN: "warning", PREG: "pregnancy_caution", BAN: "ban"}


@dataclass(frozen=True)
class Finding:
    severity: int
    code: str                                  # stable machine id of the rule outcome
    text_ar: str = ""                          # one-line summary (Arabic)
    text_en: str = ""                          # one-line summary (English)
    item: Dict[str, Any] = field(default_factory=dict)   # keys merged into the output row
    terminal: bool = False                     # nothing else about this drug matters

    def summary(self) -> Dict[str, str]:
        return {"code": self.code, "severity": SEVERITY_NAME[self.severity],
                "text_ar": self.text_ar, "text_en": self.text_en or self.text_ar}


def ban(code: str, category: str, short_ar: str, detail_ar: str,
        short_en: str = "", detail_en: str = "", terminal: bool = False,
        **extra: Any) -> Finding:
    """A ban row, in both languages. Clinical text is authored per language,
    never machine-translated out of the other one; the *_en fields fall back to
    the Arabic only so that a missing translation degrades to readable text
    rather than to an empty reason."""
    item = {"category": category,
            "reason_short": short_ar, "reason_detail": detail_ar,
            "reason_short_en": short_en or short_ar,
            "reason_detail_en": detail_en or detail_ar, **extra}
    return Finding(BAN, code, short_ar, short_en or short_ar, item, terminal)


def warn(code: str, text_ar: str, text_en: str = "",
         short_ar: str = "", short_en: str = "", **extra: Any) -> Finding:
    """A caution row. `short_*` is the one-line form for compact layouts (the
    PDF prints warnings as small chips); it is written by hand because cutting
    the full text at N characters turns a clinical caution into a fragment."""
    item = {"warning_reason": code, "warning_text": text_ar,
            "warning_text_en": text_en or text_ar,
            "warning_short": short_ar or text_ar,
            "warning_short_en": short_en or short_ar or text_en or text_ar, **extra}
    return Finding(WARN, code, short_ar or text_ar, short_en or text_en or text_ar, item)


def preg_caution(code: str, note_ar: str, note_en: str = "") -> Finding:
    first = (note_ar.splitlines() or [""])[0]
    item = {"preg_note": note_ar}
    if note_en:
        item["preg_note_en"] = note_en
    return Finding(PREG, code, first, (note_en.splitlines() or [first])[0] if note_en else first, item)


def tag(code: str, text_ar: str = "", text_en: str = "", **extra: Any) -> Finding:
    return Finding(TAG, code, text_ar, text_en or text_ar, dict(extra))
