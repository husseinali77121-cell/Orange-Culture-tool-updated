"""Named resistance phenotypes (MRSA / VRE / CRE / CRAB / CRPA) from the S/I/R pattern."""
from __future__ import annotations

from typing import Any, Dict, List

from clinical_data import PHENOTYPE_RULES
from .organisms import identify
from .sir import normalize_sir_map

def _candidate(ph_name: str, organism: str) -> bool:
    """Is this organism eligible for the named phenotype? Decided on organism
    GROUPS, not on a hand-kept list of spellings - the CRE list, for instance,
    held "Klebsiella spp." and "Klebsiella pneumoniae" but not K. oxytoca,
    Morganella or Providencia."""
    org = identify(organism)
    if ph_name == "MRSA":
        return org.is_("s_aureus")
    if ph_name == "VRE":
        return org.is_("enterococcus")
    if ph_name == "CRE":
        return org.is_("enterobacterales")
    if ph_name == "CRAB":
        return org.is_("acinetobacter")
    if ph_name == "CRPA":
        return org.is_("pseudomonas")
    return False


def _entry(ph_name: str, rule: Dict[str, Any], matched: List[str]) -> Dict[str, Any]:
    return {
        "phenotype": ph_name,
        "icon": rule["icon"], "label": rule["label"],
        "detail": rule["detail"], "action": rule["action"],
        "isolation": rule.get("isolation", False),
        "matched_markers": matched,
    }


def detect_resistance_phenotypes(
    organism: str, sir_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """Named resistance phenotypes present in this isolate."""
    sir = normalize_sir_map(sir_map)
    if not sir:
        return []
    org = identify(organism)
    detected: List[Dict[str, Any]] = []

    for ph_name, rule in PHENOTYPE_RULES.items():
        if not _candidate(ph_name, organism):
            continue
        markers = list(rule.get("markers", []))
        # Proteus / Morganella / Providencia have intrinsically reduced
        # imipenem susceptibility: imipenem R alone is not CRE (CDC definition).
        if ph_name == "CRE" and org.is_("morganellaceae"):
            markers = [(d, e) for d, e in markers if d != "Imipenem/Cilastatin"]
        need = rule.get("require_any", len(markers))
        matched = [d for d, expected in markers if sir.get(d) == expected]
        # An organism REPORTED as MRSA / VRE carries the phenotype by name.
        named = ((ph_name == "MRSA" and org.is_("name_mrsa"))
                 or (ph_name == "VRE" and org.is_("name_vre")))
        if (matched and len(matched) >= need) or named:
            detected.append(_entry(ph_name, rule, matched))

    # MRSA fallback: S. aureus resistant to anti-staphylococcal beta-lactams
    # with no oxacillin/cefoxitin result -> ask for the confirmatory test.
    if org.is_("s_aureus") and not any(d["phenotype"] == "MRSA" for d in detected):
        beta_r = any(sir.get(d) == "R" for d in
                     ("Amoxicillin + Clavulanic acid", "Cephalexin", "Cefuroxime"))
        if beta_r and (sir.get("Vancomycin") == "S" or sir.get("Linezolid") == "S"):
            detected.append({
                "phenotype": "Possible MRSA",
                "icon":      "⚠️",
                "label":     "Possible MRSA — تأكيد مطلوب",
                "detail":    "نمط مقاومة beta-lactam مع حساسية للـ Vancomycin/Linezolid يشير لـ MRSA.",
                "action":    "أجرِ Cefoxitin disk diffusion أو PCR (mecA) للتأكيد.",
                "isolation": False,
                "matched_markers": [],
            })
    return detected
