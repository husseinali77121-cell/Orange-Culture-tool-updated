#!/usr/bin/env python3
"""
Orange Lab CDSS — Clinical Scenario Matrix
===========================================

WHY A MATRIX AND NOT MORE UNIT TESTS
------------------------------------
Every bug this system has shipped had the same shape: a rule was correct in
isolation and wrong in combination. The Acinetobacter/amox-clav defect needed a
specific organism AND a specific combination agent on the panel. The P.
aeruginosa carbapenemase defect needed carbapenem resistance AND a susceptible
beta-lactam in the same panel. Neither is reachable by testing one function.

A unit test asks "does this function return the right value?". This matrix asks
the question that actually matters clinically:

    for every organism the lab reports, in every specimen it comes from,
    against every realistic resistance pattern -- is the advice coherent?

"Coherent" is defined by INVARIANTS, not by expected outputs. Expected-output
tests rot: any deliberate change breaks hundreds of them and they get bulk-
updated without being read, which is worse than having no test. Invariants
survive intentional change and only fire on genuine contradictions.

STRUCTURE
---------
    ORGANISM_SPECIMEN   clinically plausible pairs only. Testing Legionella in
                        a stool culture generates noise, not signal.
    AST_ARCHETYPES      resistance patterns a real bench actually produces --
                        wild type, ESBL, AmpC, carbapenemase, MRSA, VRE, DTR,
                        and the specific shapes that caused past defects.
    build_matrix()      the cartesian product, filtered for plausibility, with
                        each drug panel restricted to agents that exist in
                        ABX_GUIDELINES so a typo cannot silently pass.

Run standalone to inspect:
    python scenario_matrix.py            # summary counts
    python scenario_matrix.py --list     # every scenario id
    python scenario_matrix.py --show N   # dump scenario N in full
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    from abx_guidelines import ABX_GUIDELINES
    _KNOWN_DRUGS = set(ABX_GUIDELINES)
except Exception:                                     # pragma: no cover
    _KNOWN_DRUGS = set()

# ============================================================================
#  ORGANISM x SPECIMEN — plausible pairs only
# ============================================================================
_URINE = "Urine"
_BLOOD = "Blood"
_SPUTUM = "Sputum"
_WOUND = "Wound"
_CSF = "CSF"
_STOOL = "Stool"

ORGANISM_SPECIMEN: Dict[str, List[str]] = {
    "E. coli":                      [_URINE, _BLOOD, _WOUND, _STOOL],
    "Klebsiella spp.":              [_URINE, _BLOOD, _SPUTUM, _WOUND],
    "Proteus mirabilis":            [_URINE, _WOUND],
    "Pseudomonas aeruginosa":       [_URINE, _BLOOD, _SPUTUM, _WOUND],
    "Acinetobacter baumannii":      [_BLOOD, _SPUTUM, _WOUND],
    "Stenotrophomonas maltophilia": [_BLOOD, _SPUTUM],
    "Staphylococcus aureus":        [_BLOOD, _WOUND, _SPUTUM],
    "MRSA":                         [_BLOOD, _WOUND, _SPUTUM],
    "Enterococcus faecalis":        [_URINE, _BLOOD, _WOUND],
    "VRE":                          [_URINE, _BLOOD],
    "Streptococcus pneumoniae":     [_BLOOD, _SPUTUM, _CSF],
    "Salmonella spp.":              [_STOOL, _BLOOD],
    "Shigella spp.":                [_STOOL],
    "Listeria monocytogenes":       [_BLOOD, _CSF],
}

# ============================================================================
#  AST ARCHETYPES — resistance patterns a real bench produces
# ============================================================================
#  Each archetype is (id, description, {drug: S/I/R}). Drugs absent from a
#  panel are simply not tested, which is the normal case on an Egyptian AST
#  sheet -- the engine must cope with partial panels, not assume a full one.
AST_ARCHETYPES: List[Tuple[str, str, Dict[str, str]]] = [
    ("wild_type", "fully susceptible wild type", {
        "Ampicillin": "S", "Amoxicillin + Clavulanic acid": "S",
        "Cefuroxime": "S", "Ceftriaxone": "S", "Ciprofloxacin": "S",
        "Gentamicin": "S", "Trimethoprim/Sulfamethoxazole": "S",
        "Meropenem": "S",
    }),
    ("esbl_classic", "ESBL: 3rd-gen ceph R, carbapenem S, cefoxitin S", {
        "Ampicillin": "R", "Amoxicillin + Clavulanic acid": "I",
        "Cefuroxime": "R", "Ceftriaxone": "R", "Cefotaxime": "R",
        "Cefoxitin": "S", "Meropenem": "S", "Ertapenem": "S",
        "Ciprofloxacin": "R", "Amikacin": "S",
    }),
    ("ampc_pattern", "AmpC: 3rd-gen ceph R WITH cefoxitin R", {
        "Ampicillin": "R", "Amoxicillin + Clavulanic acid": "R",
        "Cefuroxime": "R", "Ceftriaxone": "R", "Cefoxitin": "R",
        "Cefepime": "S", "Meropenem": "S", "Amikacin": "S",
    }),
    ("carbapenemase_2R", "two carbapenems R (Enterobacterales: KPC/MBL/OXA)", {
        "Ceftriaxone": "R", "Ceftazidime": "R", "Cefepime": "R",
        "Meropenem": "R", "Imipenem/Cilastatin": "R", "Ertapenem": "R",
        "Amikacin": "R", "Colistin": "S",
    }),
    ("oxa48_like", "ertapenem R with meropenem S — confirm-first pattern", {
        "Ceftriaxone": "R", "Ertapenem": "R", "Meropenem": "S",
        "Amikacin": "S", "Colistin": "S",
    }),
    # THE DEFECT PATTERN: carbapenem-R with a SUSCEPTIBLE beta-lactam present.
    # This is the shape that used to move a working Ceftazidime into Avoid.
    ("carbR_but_ceftaz_S", "carbapenem R but ceftazidime STILL S", {
        "Meropenem": "R", "Imipenem/Cilastatin": "R",
        "Ceftazidime": "S", "Cefepime": "S",
        "Amikacin": "S", "Ciprofloxacin": "R", "Colistin": "S",
    }),
    ("dtr_pattern", "difficult-to-treat: all first-line beta-lactams + FQ lost", {
        "Ceftazidime": "R", "Cefepime": "R", "Meropenem": "R",
        "Imipenem/Cilastatin": "R", "Piperacillin + Tazobactam": "R",
        "Ciprofloxacin": "R", "Levofloxacin": "R", "Colistin": "S",
    }),
    ("mrsa_oxacillin_R", "oxacillin R — mecA/PBP2a", {
        "Oxacillin": "R", "Cefoxitin": "R", "Penicillin": "R",
        "Vancomycin": "S", "Linezolid": "S", "Clindamycin": "S",
        "Erythromycin": "R", "Trimethoprim/Sulfamethoxazole": "S",
    }),
    ("mssa_plain", "oxacillin S — MSSA", {
        "Oxacillin": "S", "Cefoxitin": "S", "Penicillin": "R",
        "Vancomycin": "S", "Clindamycin": "S", "Erythromycin": "S",
    }),
    # D-test territory: erythro R + clinda S must not report clinda susceptible
    # without a documented negative D-test (inducible MLSb).
    ("inducible_mlsb", "erythromycin R with clindamycin S — D-test required", {
        "Oxacillin": "S", "Erythromycin": "R", "Clindamycin": "S",
        "Vancomycin": "S", "Linezolid": "S",
    }),
    ("vre_pattern", "vancomycin R enterococcus", {
        "Ampicillin": "R", "Vancomycin": "R", "Teicoplanin": "R",
        "Linezolid": "S", "Nitrofurantoin": "S",
    }),
    ("hlar_pattern", "enterococcus with aminoglycoside on the panel", {
        "Ampicillin": "S", "Gentamicin": "S", "Vancomycin": "S",
        "Nitrofurantoin": "S",
    }),
    # The combination-agent panel that produced phantom drugs in OCR.
    ("bli_combo_panel", "panel built from beta-lactamase-inhibitor combinations", {
        "Ampicillin/Sulbactam": "S", "Amoxicillin + Clavulanic acid": "S",
        "Piperacillin + Tazobactam": "S", "Cefoperazone + Sulbactam": "S",
        "Meropenem": "S", "Amikacin": "S",
    }),
    ("thin_panel", "only two agents tested — must not over-classify", {
        "Ciprofloxacin": "R", "Gentamicin": "S",
    }),
    ("all_resistant", "nothing susceptible anywhere", {
        "Ampicillin": "R", "Ceftriaxone": "R", "Ceftazidime": "R",
        "Cefepime": "R", "Meropenem": "R", "Ciprofloxacin": "R",
        "Gentamicin": "R", "Amikacin": "R",
        "Trimethoprim/Sulfamethoxazole": "R",
    }),
]

# ============================================================================
#  Plausibility filter
# ============================================================================
_GRAM_POS = ("staphylococcus", "mrsa", "enterococc", "vre", "streptococc",
             "listeria")
_GRAM_POS_ONLY = {"mrsa_oxacillin_R", "mssa_plain", "inducible_mlsb",
                  "vre_pattern", "hlar_pattern"}
_GRAM_NEG_ONLY = {"esbl_classic", "ampc_pattern", "carbapenemase_2R",
                  "oxa48_like", "carbR_but_ceftaz_S", "dtr_pattern",
                  "bli_combo_panel"}
_NON_FERMENTER = ("pseudomonas", "acinetobacter", "stenotrophomonas")


def _is_gram_pos(org: str) -> bool:
    o = org.lower()
    return any(k in o for k in _GRAM_POS)


def _plausible(org: str, arch_id: str) -> bool:
    """Filter out pairings that would only generate noise."""
    gp = _is_gram_pos(org)
    if gp and arch_id in _GRAM_NEG_ONLY:
        return False
    if not gp and arch_id in _GRAM_POS_ONLY:
        return False
    o = org.lower()
    # MRSA is a phenotype, not a wild-type organism.
    if o == "mrsa" and arch_id in ("mssa_plain", "wild_type"):
        return False
    if o == "vre" and arch_id != "vre_pattern" and arch_id != "all_resistant":
        return False
    # ESBL/AmpC/carbapenemase inference is an Enterobacterales concept.
    if any(k in o for k in _NON_FERMENTER) and arch_id in (
            "esbl_classic", "ampc_pattern", "oxa48_like"):
        return False
    # The carbapenem-R-with-susceptible-beta-lactam shape is the P. aeruginosa
    # defect pattern; it is also legitimate for Acinetobacter.
    if arch_id == "carbR_but_ceftaz_S" and not any(k in o for k in _NON_FERMENTER):
        return False
    if arch_id == "dtr_pattern" and not any(k in o for k in _NON_FERMENTER):
        return False
    return True


def build_matrix() -> List[Dict[str, Any]]:
    """Every plausible (organism, specimen, AST archetype) scenario."""
    out: List[Dict[str, Any]] = []
    for org, specimens in ORGANISM_SPECIMEN.items():
        for spec in specimens:
            for arch_id, desc, panel in AST_ARCHETYPES:
                if not _plausible(org, arch_id):
                    continue
                # Restrict to drugs the formulary actually knows, so a typo in
                # an archetype cannot silently become an untested scenario.
                sir = {d: v for d, v in panel.items()
                       if not _KNOWN_DRUGS or d in _KNOWN_DRUGS}
                if len(sir) < 2:
                    continue
                out.append({
                    "id": f"{org}|{spec}|{arch_id}",
                    "organism": org,
                    "specimen": spec,
                    "archetype": arch_id,
                    "description": desc,
                    "sir": sir,
                })
    return out


def unknown_archetype_drugs() -> Dict[str, List[str]]:
    """Drugs named in archetypes that the formulary does not recognise."""
    if not _KNOWN_DRUGS:
        return {}
    out: Dict[str, List[str]] = {}
    for arch_id, _desc, panel in AST_ARCHETYPES:
        missing = [d for d in panel if d not in _KNOWN_DRUGS]
        if missing:
            out[arch_id] = missing
    return out


if __name__ == "__main__":
    m = build_matrix()
    if "--list" in sys.argv:
        for s in m:
            print(s["id"])
    elif "--show" in sys.argv:
        i = int(sys.argv[sys.argv.index("--show") + 1])
        s = m[i]
        print(f"{s['id']}\n  {s['description']}")
        for d, v in s["sir"].items():
            print(f"    {d:34s} {v}")
    else:
        pairs = sum(len(v) for v in ORGANISM_SPECIMEN.values())
        print("Orange Lab CDSS — clinical scenario matrix")
        print("=" * 46)
        print(f"  organisms                 : {len(ORGANISM_SPECIMEN)}")
        print(f"  organism-specimen pairs   : {pairs}")
        print(f"  AST archetypes            : {len(AST_ARCHETYPES)}")
        print(f"  plausible scenarios       : {len(m)}")
        bad = unknown_archetype_drugs()
        print(f"  archetype drugs not in DB : {len(bad)}"
              + (f"  -> {bad}" if bad else ""))
        from collections import Counter
        c = Counter(s["archetype"] for s in m)
        print("\n  scenarios per archetype:")
        for k, n in sorted(c.items(), key=lambda kv: -kv[1]):
            print(f"    {k:24s} {n}")
