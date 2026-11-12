"""Treatment duration engine."""
from __future__ import annotations

from typing import Any, Dict, List

from clinical_data import TREATMENT_DURATION_DB
from .organisms import identify
from .specimens import classify_specimen

_NOT_MATCHED = {"label": "Not matched", "min_days": 7, "max_days": 14, "standard_days": 10,
                "iv_days": 3, "po_days": 7, "notes": "Individualize based on clinical response.",
                "follow_up_culture": True, "ref": "Clinical judgment"}

_MDR_PHENOTYPES = ("MDR", "XDR", "PDR", "CRE", "CRPA", "CRAB")


def _duration_key(specimen: str, organism: str, syndrome: str, age: int, sex: str,
                  is_renal: bool, has_mrsa: bool, has_mdr: bool, severity: str):
    """Pick the TREATMENT_DURATION_DB row. Pure routing - no numbers here.

    The specimen is classified by the shared classifier. Raw substring tests
    used to send every "... swab" (throat, vaginal, rectal) to the skin and
    soft-tissue rows, and "bal" matched "balanitis".
    """
    cat = classify_specimen(specimen)
    spec = (specimen or "").lower()
    synd = (syndrome or "").lower()
    org = identify(organism)

    if cat == "urine":
        if any(k in synd for k in ("pyelonephritis", "upper", "kidney", "pyelo")):
            return "Pyelonephritis_inpatient" if severity == "severe" else "Pyelonephritis_outpatient"
        if severity == "severe":
            return "Pyelonephritis_inpatient"
        if severity == "moderate" or sex == "Male" or age >= 65 or is_renal or has_mdr:
            return "UTI_complicated"
        return "UTI_uncomplicated_female"

    if cat in ("sputum", "respiratory"):
        if any(k in synd for k in ("hap", "vap", "hospital", "ventil")):
            return "HAP_VAP"
        return {"mild": "CAP_mild", "severe": "CAP_severe"}.get(severity, "CAP_moderate")

    if cat == "blood":
        if org.is_("s_aureus"):
            return "Bacteremia_MRSA" if (has_mrsa or org.is_("name_mrsa")) else "Bacteremia_MSSA"
        if org.gram == "negative":
            return "Bacteremia_GNB"
        return "Bacteremia_other"

    if cat == "csf":
        if org.key == "streptococcus pneumoniae":
            return "Meningitis_pneumococcal"
        if org.key == "neisseria meningitidis":
            return "Meningitis_meningococcal"
        if org.key == "haemophilus influenzae":
            return "Meningitis_hinfluenzae"
        if org.key == "streptococcus agalactiae":
            return "Meningitis_GBS"
        if org.key == "listeria monocytogenes":
            return "Meningitis_listeria"
        if (org.is_("enterobacterales") or org.is_("pseudomonas")
                or org.is_("acinetobacter") or org.is_("stenotrophomonas")):
            return "Meningitis_GNB"
        return "Meningitis_other"

    if cat == "wound":
        if any(k in synd for k in ("necrotiz", "fasciitis", "gangrene")):
            return "SSTI_severe"
        if "osteomyelitis" in synd or "bone" in synd:
            return "Osteomyelitis"
        return {"mild": "SSTI_mild", "severe": "SSTI_severe"}.get(severity, "SSTI_moderate")

    if cat == "stool":
        return "GI_severe" if severity == "severe" else "GI_mild"

    if any(w in spec for w in ("abdomen", "periton", "ascit", "bile")):
        return "Intraabdominal_severe" if severity == "severe" else "Intraabdominal_mild"
    return None


def get_treatment_duration(
    specimen: str, organism: str, syndrome: str,
    age: int, sex: str, is_renal: bool,
    phenotypes: List[Dict], severity: str = "moderate",
) -> Dict[str, Any]:
    """Treatment Duration Engine (sources are cited per row in the DB)."""
    ph = [p.get("phenotype", "") for p in (phenotypes or [])]
    has_mrsa = "MRSA" in ph
    has_mdr = any(x in ph for x in _MDR_PHENOTYPES)
    severity = (severity or "moderate").lower()

    key = _duration_key(specimen, organism, syndrome, age, sex, is_renal,
                        has_mrsa, has_mdr, severity)
    row = TREATMENT_DURATION_DB.get(key) if key else None
    if not row:
        return dict(_NOT_MATCHED)

    d = row.copy()
    mn, mx = d["days"]
    notes_extra = []
    if has_mdr:
        mx = max(mx, 14)
        notes_extra.append("MDR organism: extended duration may be required.")
    if is_renal:
        notes_extra.append("Renal impairment: monitor drug levels closely.")
    if age > 65:
        notes_extra.append("Elderly: monitor for toxicity; shorter courses if responding.")
    if notes_extra:
        base = d.get("notes") or ""
        d["notes"] = (base + " | " if base else "") + " | ".join(notes_extra)
    d.update({"min_days": mn, "max_days": mx, "standard_days": d["standard"], "key": key})
    return d
