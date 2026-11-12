"""Everything the rules need to know, computed once per analysis."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from abx_guidelines import ABX_GUIDELINES
from ast_reportability import check_reportability

from ..drugs import family
from ..mechanisms import predict_esbl
from ..organisms import Organism, identify
from ..sir import normalize_sir_map, sir_of
from ..specimens import classify_specimen


@dataclass(frozen=True)
class DrugCase:
    name: str
    info: Dict[str, Any]
    family: str
    sir: Optional[str]            # "S" / "I" / "R" / None (not tested)


@dataclass(frozen=True)
class Context:
    organism_name: str
    organism: Organism
    specimen_name: str
    specimen: str                 # canonical category (cdss.specimens)
    age: int
    sex: str
    is_renal: bool
    cl_cr: float
    is_preg: bool
    is_hepatic: bool
    current_meds: tuple
    sir: Dict[str, Any]
    interp_std: str               # "EUCAST" | "CLSI"
    mechanism: Dict[str, Any]
    policy: Optional[str]         # mechanism["betalactam_policy"]
    is_mrsa: bool
    reportability_intrinsic: Dict[str, str] = field(default_factory=dict)

    def case(self, drug: str) -> DrugCase:
        return DrugCase(drug, ABX_GUIDELINES[drug], family(drug), sir_of(self.sir, drug))


def _detect_mrsa(org: Organism, sir: Dict[str, Any]) -> bool:
    """MRSA = a staphylococcus that is named MRSA or carries the mecA surrogate
    marker (oxacillin R or cefoxitin R - EUCAST/CLSI use cefoxitin as the
    screening agent, and most panels carry only one of the two)."""
    if not org.is_("staphylococcus"):
        return False
    return (org.is_("name_mrsa")
            or sir.get("Oxacillin") == "R" or sir.get("Cefoxitin") == "R")


def build_context(organism_type: str, culture_type: str, age: int, sex: str,
                  is_renal: bool, cl_cr: float, is_preg: bool, is_hepatic: bool,
                  current_meds: Optional[List[str]], sir_map: Optional[Dict[str, Any]],
                  interp_std: str = "EUCAST") -> Context:
    sir = normalize_sir_map(sir_map)
    org = identify(organism_type)
    mech = predict_esbl(organism_type, sir) if sir else {}
    rep: Dict[str, str] = {}
    for r in check_reportability(organism_type or "", sir):
        if r["category"] == "intrinsic":
            for d in r["drugs"]:
                rep[d] = r["reason_ar"]
    try:
        age_i = int(age)
    except (TypeError, ValueError):
        age_i = 0
    try:
        crcl = float(cl_cr)
    except (TypeError, ValueError):
        crcl = 0.0
    return Context(
        organism_name=organism_type or "", organism=org,
        specimen_name=culture_type or "", specimen=classify_specimen(culture_type or ""),
        age=age_i, sex=sex or "", is_renal=bool(is_renal), cl_cr=crcl,
        is_preg=bool(is_preg), is_hepatic=bool(is_hepatic),
        current_meds=tuple(current_meds or ()), sir=sir,
        interp_std="EUCAST" if str(interp_std).upper() == "EUCAST" else "CLSI",
        mechanism=mech, policy=mech.get("betalactam_policy"),
        is_mrsa=_detect_mrsa(org, sir), reportability_intrinsic=rep,
    )
