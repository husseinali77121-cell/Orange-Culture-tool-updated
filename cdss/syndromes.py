"""Infection-syndrome context for a specimen."""
from __future__ import annotations

from typing import Any, Dict, Optional

from clinical_data import INFECTION_SYNDROMES
from .specimens import classify_specimen

_CATEGORY_KEY = {"urine": "Urine", "blood": "Blood", "sputum": "Sputum",
                 "respiratory": "Sputum", "csf": "CSF", "stool": "Stool"}


def _syndrome_key(specimen: str) -> Optional[str]:
    """Specimen name -> INFECTION_SYNDROMES key, via the shared classifier.
    Genital / throat / unknown specimens have no syndrome row and return None
    (they used to fall into "Wound Swab" on the word "swab")."""
    name = (specimen or "").strip()
    if (name, None) in INFECTION_SYNDROMES:
        return name
    cat = classify_specimen(name)
    if cat in _CATEGORY_KEY:
        return _CATEGORY_KEY[cat]
    if cat == "wound":
        low = name.lower()
        return "Pus" if ("pus" in low or "abscess" in low or "drain" in low) else "Wound Swab"
    return None


def get_infection_syndrome(
    specimen:  str,
    organism:  str,
    age:       int,
    is_preg:   bool,
    is_cath:   bool = False,
) -> Optional[Dict[str, Any]]:
    """Clinical context of the infection for this specimen (None if unknown)."""
    key = _syndrome_key(specimen)
    data = INFECTION_SYNDROMES.get((key, None)) if key else None
    if not data:
        return None
    sub_type = data["classify"](age, is_preg, is_cath)
    duration = data["duration"].get(sub_type, "حسب الاستجابة السريرية")
    return {
        "syndrome":     data["syndrome"],
        "sub_type":     sub_type,
        "first_choice": data["first_choice"],
        "duration":     duration,
        "escalation":   data["escalation"],
        "threshold":    data["culture_threshold"],
    }
