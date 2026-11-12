"""Specimen classification - the single source of truth for specimen routing."""
from __future__ import annotations

import re

# ─────────────────────────────────────────────────────────────────────────
# Specimen classification — the SINGLE source of truth for specimen routing
# across the whole app (UI field visibility, pathogenicity branches, and the
# pathogenicity scoring engine). One classifier prevents the UI and the engine
# from drifting apart — the exact drift that made a bare "swab" keyword get
# checked before "rectal"/"throat"/"vaginal", so a rectal/throat/vaginal swab
# was mis-scored as a wound.
#
# Category split worth noting:
#   • "sputum"      → expectorated sputum → Murray-Washington screening applies.
#   • "respiratory" → BAL / bronchial washing / (endo)tracheal aspirate →
#                     lower-respiratory, but Murray-Washington does NOT apply.
#   • "genital"/"throat" → own buckets so a swab from these sites is never a
#                     "wound".
# ─────────────────────────────────────────────────────────────────────────
SPECIMEN_CATEGORIES = (
    "urine", "blood", "sputum", "respiratory", "stool",
    "csf", "genital", "throat", "wound", "other",
)


def _spec_word(s: str, *tokens: str) -> bool:
    """Whole-word match for short/ambiguous specimen tokens.

    The classifier below matches most site keywords by substring, which is fine
    for long, unambiguous ones ("urine", "sputum"). But a handful of the tokens
    are short strings that live INSIDE common words:
        'otic'  ⊂ necr·OTIC        → "necrotic tissue"  mis-classified as throat
        'bal'   ⊂ BAL·anitis       → "balanitis swab"   mis-classified as respiratory
        'ear'   ⊂ sm·EAR / cl·EAR
        'et'    ⊂ (everywhere)
        'gi'    ⊂ sur·GI·cal
    Those go through here so they only fire as standalone words. Longer keywords
    stay on plain substring matching (faster, and safe).
    """
    return any(re.search(r"(?<![a-z])" + re.escape(t) + r"(?![a-z])", s)
               for t in tokens)


def classify_specimen(name: str) -> str:
    """Map any specimen label to a canonical category (see SPECIMEN_CATEGORIES).

    Order matters: the most specific site keywords are checked BEFORE the
    generic wound/swab keywords, so 'rectal swab' → stool, 'throat swab' →
    throat, 'high vaginal swab' → genital, and only a bare/other swab falls
    through to 'wound'.
    """
    s = (name or "").lower()
    stripped = s.strip()
    if not stripped:
        return "other"

    # 1) CSF / sterile CNS fluid
    if any(k in s for k in ("csf", "cerebro", "spinal fluid", "lumbar",
                            "ventricular fluid")):
        return "csf"
    # 2) Blood
    if any(k in s for k in ("blood", "haemocult", "hemocult", "bacterem",
                            "septicaem", "septicem")):
        return "blood"
    # 3) Urine  ('msu'/'csu' are short → whole-word)
    if (any(k in s for k in ("urine", "urinary", "midstream"))
            or _spec_word(s, "msu", "csu")):
        return "urine"
    # 4) Genital (before wound → a genital swab is never a "wound").
    #    'balanit' added so "balanitis" is genital, not 'bal'→respiratory.
    #    'hvs' is short → whole-word.
    if (any(k in s for k in ("vagin", "cervi", "endocerv", "urethr", "genital",
                             "semen", "seminal", "prostat", "penile", "vulv",
                             "balanit"))
            or _spec_word(s, "hvs")):
        return "genital"
    # 5) Stool / GI (before wound → 'rectal swab' is stool, not wound).
    #    'gi'/'git' are short → whole-word (so 'surgical' never matches).
    if (any(k in s for k in ("stool", "fecal", "faecal", "rectal", "gastro",
                             "colon"))
            or _spec_word(s, "gi", "git")):
        return "stool"
    # 6) Throat / upper-respiratory-tract & ENT (before wound; no M-W here).
    #    'otic'/'aural'/'ear'/'oral' are short → whole-word, so 'necrotic',
    #    'smear' and the like never trip them.
    if (any(k in s for k in ("throat", "pharyng", "tonsil", "nasal", "nasoph",
                             "nostril", "auricular", "buccal"))
            or _spec_word(s, "aural", "otic", "ear", "oral")):
        return "throat"
    # 7) Expectorated sputum → Murray-Washington applies
    if any(k in s for k in ("sputum", "expectorat")):
        return "sputum"
    # 8) Lower-respiratory aspirates → respiratory scoring, NO Murray-Washington.
    #    'bal'/'et' are short → whole-word ('balanitis', 'ureter'… never match).
    if (any(k in s for k in ("broncho", "bronch", "tracheal", "endotrach",
                             "lavage", "respir"))
            or _spec_word(s, "bal", "et")):
        return "respiratory"
    # 9) Wound / pus / abscess / tissue (a bare 'swab' lands here as last resort)
    if any(k in s for k in ("wound", "pus", "abscess", "tissue", "ulcer",
                            "drain", "cellulit", "sinus tract", "swab")):
        return "wound"
    return "other"
