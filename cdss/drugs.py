"""Typed drug facts.

The rules used to decide what a drug IS by searching its free-text `class`
label for substrings ("penicillin", "bli", "clavulan" ...). The labels were
written for display, not for logic, and the searches missed:

  * "Beta-lactamase Inhibitor Combination" (amoxicillin-clavulanate) contains
    neither "penicillin" nor "bli", so it was NOT a beta-lactam to any rule:
    it stayed a recommended option against MRSA, ESBL and carbapenemase
    producers alike;
  * "3rd Gen Cephalosporin + Beta-lactamase Inhibitor" (cefoperazone-sulbactam)
    was a plain cephalosporin, "Anti-pseudomonal Penicillin + Inhibitor"
    (piperacillin-tazobactam) a plain penicillin - so the "BLI combination"
    branch of the ESBL logic was unreachable.

Every formulary drug now has ONE explicit family here. A drug added to
abx_guidelines without a row in this table fails tests/test_drugs.py, so the
classification can never again be left to a substring.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import FrozenSet

from abx_guidelines import ABX_GUIDELINES

logger = logging.getLogger("orange_lab.engines")

PENICILLIN        = "penicillin"
PENICILLIN_BLI    = "penicillin_bli"       # penicillin + beta-lactamase inhibitor
CEPHALOSPORIN     = "cephalosporin"
CEPHALOSPORIN_BLI = "cephalosporin_bli"
CEPHAMYCIN        = "cephamycin"
CARBAPENEM        = "carbapenem"
MONOBACTAM        = "monobactam"
FLUOROQUINOLONE   = "fluoroquinolone"
AMINOGLYCOSIDE    = "aminoglycoside"
TETRACYCLINE      = "tetracycline"
MACROLIDE         = "macrolide"
LINCOSAMIDE       = "lincosamide"
GLYCOPEPTIDE      = "glycopeptide"
OXAZOLIDINONE     = "oxazolidinone"
POLYMYXIN         = "polymyxin"
FOLATE            = "folate_inhibitor"
NITROFURAN        = "nitrofuran"
PHOSPHONIC        = "phosphonic"
NITROIMIDAZOLE    = "nitroimidazole"
FUSIDANE          = "fusidane"
OTHER             = "other"

DRUG_FAMILY = {
    "Amoxicillin + Clavulanic acid": PENICILLIN_BLI,
    "Ampicillin/Sulbactam":          PENICILLIN_BLI,
    "Piperacillin + Tazobactam":     PENICILLIN_BLI,
    "Ampicillin": PENICILLIN, "Amoxicillin": PENICILLIN,
    "Penicillin": PENICILLIN, "Oxacillin": PENICILLIN,
    "Cephalexin": CEPHALOSPORIN, "Cefadroxil": CEPHALOSPORIN,
    "Cephradine": CEPHALOSPORIN, "Cefazolin": CEPHALOSPORIN,
    "Cefaclor": CEPHALOSPORIN, "Cefuroxime": CEPHALOSPORIN,
    "Cefuroxime sodium": CEPHALOSPORIN,
    "Ceftriaxone": CEPHALOSPORIN, "Cefixime": CEPHALOSPORIN,
    "Cefotaxime": CEPHALOSPORIN, "Ceftazidime": CEPHALOSPORIN,
    "Cefoperazone": CEPHALOSPORIN, "Cefepime": CEPHALOSPORIN,
    "Cefoperazone + Sulbactam": CEPHALOSPORIN_BLI,
    "Cefoxitin": CEPHAMYCIN,
    "Imipenem/Cilastatin": CARBAPENEM, "Meropenem": CARBAPENEM, "Ertapenem": CARBAPENEM,
    "Aztreonam": MONOBACTAM,
    "Ciprofloxacin": FLUOROQUINOLONE, "Levofloxacin": FLUOROQUINOLONE,
    "Ofloxacin": FLUOROQUINOLONE, "Norfloxacin": FLUOROQUINOLONE,
    "Gatifloxacin": FLUOROQUINOLONE, "Moxifloxacin": FLUOROQUINOLONE,
    "Gentamicin": AMINOGLYCOSIDE, "Amikacin": AMINOGLYCOSIDE, "Tobramycin": AMINOGLYCOSIDE,
    "Doxycycline": TETRACYCLINE, "Tetracycline": TETRACYCLINE,
    "Azithromycin": MACROLIDE, "Clarithromycin": MACROLIDE, "Erythromycin": MACROLIDE,
    "Clindamycin": LINCOSAMIDE,
    "Vancomycin": GLYCOPEPTIDE,
    "Linezolid": OXAZOLIDINONE,
    "Colistin": POLYMYXIN,
    "Trimethoprim/Sulfamethoxazole": FOLATE,
    "Nitrofurantoin": NITROFURAN,
    "Fosfomycin": PHOSPHONIC,
    "Metronidazole": NITROIMIDAZOLE, "Tinidazole": NITROIMIDAZOLE,
    "Fusidic acid": FUSIDANE,
}

BETA_LACTAM_FAMILIES: FrozenSet[str] = frozenset({
    PENICILLIN, PENICILLIN_BLI, CEPHALOSPORIN, CEPHALOSPORIN_BLI,
    CEPHAMYCIN, CARBAPENEM, MONOBACTAM,
})
BLI_FAMILIES: FrozenSet[str] = frozenset({PENICILLIN_BLI, CEPHALOSPORIN_BLI})

# 3rd-generation (oxyimino) cephalosporins - the agents an inducible AmpC
# defeats on therapy even when the isolate first tests susceptible.
THIRD_GEN_CEPHALOSPORINS: FrozenSet[str] = frozenset({
    "Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefixime", "Cefoperazone",
})

# Agents that reach therapeutic concentrations ONLY in urine.
URINE_ONLY: FrozenSet[str] = frozenset({"Nitrofurantoin", "Fosfomycin", "Norfloxacin"})
# ... of which Norfloxacin also has a (limited) gut-lumen role.
URINE_ONLY_EXCEPT_GI: FrozenSet[str] = frozenset({"Norfloxacin"})


def _infer_family(drug: str) -> str:
    """Last-resort inference for a drug missing from DRUG_FAMILY. Logged, and
    flagged by the test-suite; never relied on for a shipped formulary drug."""
    c = (ABX_GUIDELINES.get(drug, {}).get("class", "") or "").lower()
    n = drug.lower()
    has_inhibitor = any(k in c or k in n for k in (
        "inhibitor", "clavulan", "sulbactam", "tazobactam", "avibactam",
        "vaborbactam", "relebactam"))
    if "carbapenem" in c:
        return CARBAPENEM
    if "cephamycin" in c:
        return CEPHAMYCIN
    if "cephalosporin" in c:
        return CEPHALOSPORIN_BLI if has_inhibitor else CEPHALOSPORIN
    if "penicillin" in c or has_inhibitor:
        return PENICILLIN_BLI if has_inhibitor else PENICILLIN
    for key, fam in (("monobactam", MONOBACTAM), ("fluoroquinolone", FLUOROQUINOLONE),
                     ("aminoglycoside", AMINOGLYCOSIDE), ("tetracycline", TETRACYCLINE),
                     ("glycylcycline", TETRACYCLINE), ("macrolide", MACROLIDE),
                     ("lincosamide", LINCOSAMIDE), ("glycopeptide", GLYCOPEPTIDE),
                     ("oxazolidinone", OXAZOLIDINONE), ("polymyxin", POLYMYXIN),
                     ("sulfonamide", FOLATE), ("nitroimidazole", NITROIMIDAZOLE)):
        if key in c:
            return fam
    return OTHER


@lru_cache(maxsize=None)
def family(drug: str) -> str:
    fam = DRUG_FAMILY.get(drug)
    if fam is None:
        fam = _infer_family(drug)
        logger.warning("drug %r has no row in cdss.drugs.DRUG_FAMILY - inferred %r "
                       "from its class label; add it explicitly", drug, fam)
    return fam


def is_beta_lactam(drug: str) -> bool:
    return family(drug) in BETA_LACTAM_FAMILIES


def is_carbapenem(drug: str) -> bool:
    return family(drug) == CARBAPENEM


def is_bli_combination(drug: str) -> bool:
    return family(drug) in BLI_FAMILIES
