"""IV-to-PO switch, hepatic dosing, combination therapy and de-escalation advisors."""
from __future__ import annotations

from typing import Any, Dict, List

from clinical_data import (ALWAYS_IV_SYNDROMES, COMBINATION_THERAPY,
                           HEPATIC_DOSING, HIGH_BIOAVAILABILITY)

def evaluate_iv_po_switch(
    drug_name: str, syndrome: str,
    clinical_improving: bool, tolerating_oral: bool,
    bacteremia_resolved: bool, days_on_iv: int,
) -> Dict[str, Any]:
    """OPAT IV→PO Evaluation — IDSA 2019 | BNF 2025"""
    # Exact name only. A substring test matched "Amoxicillin" inside
    # "Amoxicillin + Clavulanic acid" and the IV-only "Cefuroxime sodium"
    # would have inherited the oral figure of "Cefuroxime" axetil.
    bioavail, matched = 0, ""
    _wanted = (drug_name or "").strip().lower()
    for k, v in HIGH_BIOAVAILABILITY.items():
        if _wanted and k.lower() == _wanted:
            bioavail, matched = v, k
            break

    blockers, supporters = [], []
    if not clinical_improving: blockers.append("No clinical improvement in 48-72h")
    else:                      supporters.append("Clinical improvement documented")
    if not tolerating_oral:    blockers.append("Not tolerating oral intake")
    else:                      supporters.append("Tolerating oral medications")
    if not bacteremia_resolved: blockers.append("Active bacteremia / endovascular infection")
    else:                       supporters.append("No active bloodstream infection")

    if bioavail >= 80:     supporters.append(f"{matched}: Oral bioavailability {bioavail}% — excellent for switch")
    elif bioavail >= 50:   blockers.append(f"{matched}: Moderate bioavailability ({bioavail}%) — consider IV continuation")
    elif bioavail > 0:     blockers.append(f"{matched}: Low bioavailability ({bioavail}%) — IV preferred")
    else:                  blockers.append(f"{drug_name}: No established oral equivalent")

    synd_lower = (syndrome or "").lower()
    if any(s in synd_lower for s in ALWAYS_IV_SYNDROMES):
        blockers.append(f"{syndrome} — requires prolonged IV therapy")
    if days_on_iv < 2:    blockers.append(f"Less than 48h on IV ({days_on_iv}d) — complete initial IV course")
    else:                  supporters.append(f"{days_on_iv} days on IV — appropriate reassessment window")

    can_switch = len(blockers) == 0
    return {
        "can_switch": can_switch, "bioavail": bioavail, "matched_drug": matched,
        "blockers": blockers, "supporters": supporters,
        "verdict": (f"Switch acceptable. Oral bioavailability: {bioavail}%." if can_switch
                    else "IV→PO switch NOT recommended at this time."),
        "ref": "IDSA OPAT 2019 | BNF 2025 | BSAC 2023",
    }

def get_hepatic_recommendations(allowed_drugs: List[Dict], child_pugh: str) -> List[Dict[str, str]]:
    """Hepatic dosing recommendations — BNF 2025 | Lexicomp 2025"""
    results = []
    for drug in allowed_drugs:
        name = drug.get("name", "")
        if name in HEPATIC_DOSING:
            level, rec = HEPATIC_DOSING[name].get(child_pugh, ("Normal", "No adjustment"))
            note = HEPATIC_DOSING[name].get("note", "")
            results.append({
                "name": name, "level": level,
                "recommendation": rec, "note": note,
                "requires_action": level not in ("Normal", "Renal-based", "AUC/MIC monitoring"),
            })
    results.sort(key=lambda x: (0 if x["requires_action"] else 1, x["name"]))
    return results

def get_combination_therapy(phenotypes: List[Dict]) -> List[Dict]:
    """Combination therapy suggestions based on detected phenotypes — IDSA AMR 2025"""
    results  = []
    ph_names = [p.get("phenotype", "") for p in phenotypes]
    for ph in ["CRAB", "CRPA", "CRE", "MRSA", "VRE", "ESBL", "MDR"]:
        if ph in ph_names and ph in COMBINATION_THERAPY:
            results.append({"phenotype": ph, "data": COMBINATION_THERAPY[ph]})
    return results

def evaluate_deescalation(
    allowed: List[Dict], phenotypes: List[Dict],
    hours_on_treatment: int, clinical_improving: bool,
) -> Dict[str, Any]:
    """De-escalation advisor — WHO AWaRe 2025 | IDSA Stewardship 2025"""
    ph_names    = [p.get("phenotype", "") for p in phenotypes]
    is_reserve  = any(p in ph_names for p in ["MDR", "XDR", "PDR", "CRE", "CRPA", "CRAB"])
    access_drugs = [d for d in allowed if d.get("aware") == "Access"]
    watch_drugs  = [d for d in allowed if d.get("aware") == "Watch"]
    recs, can_de = [], False

    if hours_on_treatment < 48:
        recs.append(f"INFO: Still in early treatment phase ({hours_on_treatment}h). Complete 48-72h before reassessment.")
    elif not clinical_improving:
        recs.extend(["WARNING: No clinical improvement at 48-72h:",
                     "  - Repeat culture to confirm sensitivity",
                     "  - Assess source control (drainage, catheter removal)",
                     "  - Consider TDM (vancomycin AUC, aminoglycosides)",
                     "  - Consult Infectious Disease"])
    else:
        can_de = True
        recs.append("RECOMMENDED: Clinical improvement documented — consider spectrum narrowing:")
        if access_drugs:
            names = [d["name"] for d in access_drugs[:4]]
            recs.append(f"  Access-group options: {' | '.join(names)}")
        elif watch_drugs:
            names = [d["name"] for d in watch_drugs[:3]]
            recs.append(f"  Watch-group options: {' | '.join(names)}")
        if is_reserve:
            recs.append("  CAUTION: MDR/XDR organism — ID consult before de-escalating Reserve agents")
            can_de = False

    recs.append("PRINCIPLE: Narrowest effective spectrum + shortest safe duration (WHO AWaRe 2025)")
    return {
        "can_deescalate": can_de,
        "access_options": [d["name"] for d in access_drugs],
        "watch_options":  [d["name"] for d in watch_drugs],
        "recommendations": recs,
        "is_reserve_organism": is_reserve,
        "ref": "WHO AWaRe 2025 | IDSA Stewardship 2025",
    }
