"""Auto-suggested infection severity from patient risk factors."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .specimens import classify_specimen

def suggest_severity(
    specimen: str, age: int, sex: str,
    is_preg: bool, is_renal: bool, cl_cr: float,
    host_factors: Optional[List] = None,
    symptoms: Optional[List] = None,
) -> Dict[str, Any]:
    """
    Auto-suggest infection severity based on patient risk factors.
    Clinical basis: IDSA UTI 2022 | IDSA CAP 2019 | Sanford 2025 |
                    AHA Infective Endocarditis 2015 | SCCM Sepsis-3 2016.

    Returns:
        suggested: "mild" | "moderate" | "severe"
        reasons:   list of clinical reasons
        override:  True (user can still change it)
    """
    spec_l = (specimen or "").lower()
    cat    = classify_specimen(specimen or "")
    hf     = [h.lower() for h in (host_factors or [])]
    syms   = [s.lower() for s in (symptoms or [])]

    reasons_severe   = []
    reasons_moderate = []
    reasons_mild     = []

    # ── Universal red flags → SEVERE ─────────────────────────────────────
    if any(k in " ".join(syms) for k in
           ["septic shock", "hypotension", "icu", "bacteremia",
            "altered consciousness", "confusion", "rigors"]):
        reasons_severe.append("Systemic sepsis signs / shock")

    # The UI labels this host factor "Immunosuppressants / Steroids"; the old
    # test looked only for the word "immunocompromised" and so never fired.
    _immuno = any(k in " ".join(hf) for k in
                  ("immunocompromised", "immunosuppress", "neutropeni", "chemotherapy"))
    if "central line" in " ".join(hf) or _immuno:
        reasons_severe.append("Immunocompromised / central line")

    # ── Specimen-specific logic ────────────────────────────────────────────
    if cat == "urine" or "uti" in spec_l:
        # IDSA: complicated UTI = male, pregnant, elderly, renal, catheter
        if sex == "Male":
            reasons_moderate.append("Male UTI → always complicated (IDSA 2022)")
        if is_preg:
            reasons_moderate.append("Pregnancy → complicated UTI")
        if age >= 65:
            reasons_moderate.append("Age ≥ 65 → complicated UTI")
        if is_renal and cl_cr < 60:
            reasons_moderate.append(f"Renal impairment (CrCl {cl_cr:.0f}) → complicated")
        if any(k in " ".join(hf) for k in ["catheter", "urologic", "diabetes"]):
            reasons_moderate.append("Host risk factor (DM / catheter / urologic anomaly)")
        if any(k in " ".join(syms) for k in ["fever", "flank pain", "costovertebral"]):
            reasons_moderate.append("Upper UTI symptoms → pyelonephritis")
        if not reasons_moderate and not reasons_severe:
            if sex == "Female" and age < 65 and not is_preg and not is_renal:
                reasons_mild.append("Young healthy female → uncomplicated cystitis (IDSA 2022)")

    elif cat in ("sputum", "respiratory"):
        # CURB-65 proxy: Age ≥65, renal, altered mentation
        curb = 0
        if age >= 65:         curb += 1; reasons_moderate.append("Age ≥ 65 (CURB-65)")
        if is_renal:          curb += 1; reasons_moderate.append("Renal impairment (CURB-65)")
        if any(k in " ".join(syms) for k in ["confusion", "altered"]):
            curb += 1; reasons_severe.append("Altered mentation (CURB-65 ≥3)")
        if curb == 0:
            reasons_mild.append("No CURB-65 risk factors → mild CAP")

    elif cat == "blood":
        # Bacteremia is always at least moderate
        reasons_moderate.append("Bloodstream infection → minimum moderate")
        if age >= 65 or is_renal:
            reasons_severe.append("Bacteremia + age ≥65 / renal impairment → severe")

    elif cat == "csf" or "meningitis" in spec_l:
        # CNS = always severe
        reasons_severe.append("CNS infection → always severe")

    elif cat == "wound":
        if _immuno or "diabetes" in " ".join(hf):
            reasons_moderate.append("Wound infection + DM/immunocompromised")
        elif not reasons_moderate and not reasons_severe:
            reasons_mild.append("Simple SSTI without systemic features")

    elif cat == "stool":
        if age >= 65 or is_renal or is_preg:
            reasons_moderate.append("GI infection + high-risk host")
        if any(k in " ".join(syms) for k in ["bloody", "fever", "dehydration"]):
            reasons_moderate.append("Febrile / bloody diarrhea → moderate+")
        else:
            reasons_mild.append("GI infection without systemic features → supportive")

    # ── Final decision ────────────────────────────────────────────────────
    if reasons_severe:
        return {"suggested": "severe",   "reasons": reasons_severe,   "override": True}
    elif reasons_moderate:
        return {"suggested": "moderate", "reasons": reasons_moderate, "override": True}
    else:
        return {"suggested": "mild",     "reasons": reasons_mild or ["No risk factors identified"],
                "override": True}
