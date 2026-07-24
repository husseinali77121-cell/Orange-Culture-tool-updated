# © 2025 Dr. Hussein Ali — Orange Lab, 6 October City, Egypt
# AST Quality Assurance Engine — Independent Module
# Unauthorized copying or distribution is prohibited.
"""
AST-QA Engine: Laboratory Consistency & Plausibility Checker
Runs BEFORE the Clinical Decision Engine to flag AST contradictions,
biological impossibilities, phenotype inconsistencies, and clinical mismatches.

Architecture:
  OCR → Organism Detection → AST Parsing
    → [AST-QA Engine]  ← THIS MODULE
      → Phenotype Detection → Clinical Decision Engine → Final Report
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ── Issue container ────────────────────────────────────────────────────────────
@dataclass
class QAIssue:
    level:     int           # 1–15
    severity:  str           # CRITICAL | HIGH | MEDIUM | LOW
    category:  str           # Short category label
    message:   str           # One-line headline
    detail:    str           # Full clinical explanation
    drug:      str = ""      # Drug(s) involved
    reference: str = ""      # Guideline reference

_SEV_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# ── Helper ─────────────────────────────────────────────────────────────────────
def _r(drug: str, sir: Dict[str, str]) -> Optional[str]:
    """Get SIR value for a drug."""
    return sir.get(drug)

def _is_R(drug: str, sir: Dict[str, str]) -> bool:
    return sir.get(drug) == "R"

def _is_S(drug: str, sir: Dict[str, str]) -> bool:
    return sir.get(drug) == "S"

def _is_I(drug: str, sir: Dict[str, str]) -> bool:
    return sir.get(drug) == "I"

def _both_tested(a: str, b: str, sir: Dict[str, str]) -> bool:
    return a in sir and b in sir


# ══════════════════════════════════════════════════════════════════════════════
# INTRINSIC RESISTANCE — single source of truth = clinical_data.INTRINSIC_RESISTANCE
# The QA engine consumes the SAME canonical table as the clinical engine, so the
# two halves of the system can never disagree again (that drift caused the
# P. aeruginosa false-ESBL / Doxycycline-placement bugs). MRSA (mecA) and
# Mycoplasma (no cell wall) are QA-specific plausibility checks — functional, not
# EUCAST "intrinsic" — so they are kept local and merged over the canonical set.
# Matching is substring-based (see _check_intrinsic_resistance).
try:
    from clinical_data import INTRINSIC_RESISTANCE as _CANONICAL_INTRINSIC
    CANONICAL_INTRINSIC_LOADED = True
except Exception:                          # standalone use without clinical_data
    # NOTE: this fallback used to fire in the commercial build because
    # clinical_data.py was never shipped with it. The result was a QA engine that
    # silently checked MRSA and Mycoplasma ONLY, while the clinical engine used a
    # full Gram-negative table -- so "AST Quality Check" reported no intrinsic
    # conflicts on organisms the recommendation panel was already banning drugs
    # for. If this branch is taken, say so loudly rather than degrading quietly.
    _CANONICAL_INTRINSIC = {}
    CANONICAL_INTRINSIC_LOADED = False

# QA-only supplements (functional resistance, NOT EUCAST intrinsic)
_QA_ONLY_INTRINSIC: Dict[str, List[str]] = {
    # MRSA: mecA/PBP2a → ALL β-lactams fail (except anti-MRSA cephalosporins)
    "mrsa": [
        "Oxacillin", "Penicillin",
        "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
        "Piperacillin", "Piperacillin + Tazobactam", "Ticarcillin",
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefoxitin", "Cefotaxime", "Ceftriaxone", "Ceftazidime",
        "Cefepime", "Cefoperazone", "Cefixime", "Cefpodoxime",
        "Imipenem/Cilastatin", "Meropenem", "Ertapenem",
    ],
    # Mycoplasma: no cell wall → all cell-wall-active agents inert
    "mycoplasma spp.": [
        "Penicillin", "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
        "Piperacillin", "Piperacillin + Tazobactam",
        "Cephalexin", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefepime", "Cefoxitin", "Cefixime",
        "Imipenem/Cilastatin", "Meropenem", "Ertapenem", "Aztreonam",
        "Vancomycin", "Teicoplanin", "Fosfomycin",
    ],
    "mycoplasma": [
        "Penicillin", "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Vancomycin", "Cephalexin", "Ceftriaxone", "Cefotaxime",
        "Imipenem/Cilastatin", "Meropenem", "Ertapenem",
    ],
}

# Canonical keys are already lowercase; QA supplements win on any key collision.
_INTRINSIC_RESISTANCE: Dict[str, List[str]] = {
    **{k.lower(): list(v) for k, v in _CANONICAL_INTRINSIC.items()},
    **_QA_ONLY_INTRINSIC,
}

def _check_intrinsic_resistance(organism: str, sir: Dict[str, str]) -> List[QAIssue]:
    issues = []
    # substring match (binomial ↔ abbreviated), identical to the clinical engine
    _org_l = (organism or "").lower().strip()
    if not _org_l:
        # Guard: with an empty organism, `_org_l in _k` is True for EVERY key, so
        # the union of all intrinsic lists would be flagged against the panel.
        return issues
    resistant_drugs = set()
    for _k, _lst in _INTRINSIC_RESISTANCE.items():
        if _k and (_k in _org_l or _org_l in _k):
            resistant_drugs.update(_lst)
    for drug in sorted(resistant_drugs):
        if _is_S(drug, sir) or _is_I(drug, sir):
            val = sir[drug]
            issues.append(QAIssue(
                level=1, severity="CRITICAL",
                category="Intrinsic Resistance",
                message=f"{drug} = {val} contradicts intrinsic resistance",
                detail=(
                    f"{organism} is intrinsically resistant to {drug} (natural/chromosomal mechanism). "
                    f"Reporting {drug}={val} is microbiologically incorrect — "
                    f"possible lab error, OCR misread, or wrong organism ID. "
                    f"Do NOT treat based on this result."
                ),
                drug=drug,
                reference="EUCAST Intrinsic Resistance v3.3 · CLSI M100 Ed36 Appendix B",
            ))
    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 2 — Phenotype Consistency
# ══════════════════════════════════════════════════════════════════════════════
def _check_phenotype_consistency(
    organism: str,
    sir: Dict[str, str],
    esbl_result: Optional[Dict] = None,
    mdr_result: Optional[Dict] = None,
) -> List[QAIssue]:
    issues = []
    org_l = organism.lower()

    # ── MRSA phenotype checks ──
    if "staphylococcus aureus" in org_l or "staph" in org_l:
        oxa = _r("Oxacillin", sir)
        cfx = _r("Cefoxitin", sir)
        cfz = _r("Cefazolin", sir)

        # Oxacillin R but Cefazolin S → inconsistent (both lost in MRSA)
        if oxa == "R" and cfz == "S":
            issues.append(QAIssue(
                level=2, severity="CRITICAL",
                category="Phenotype Consistency",
                message="Oxacillin=R but Cefazolin=S — MRSA inconsistency",
                detail=(
                    "MRSA (mecA/PBP2a) renders ALL beta-lactams resistant, including Cefazolin. "
                    "Oxacillin=R + Cefazolin=S is biologically impossible. "
                    "Likely AST technical error or incorrect organism. Repeat testing required."
                ),
                drug="Oxacillin, Cefazolin",
                reference="CLSI M100 Ed36, EUCAST Breakpoint Tables v16.0",
            ))

        # Cefoxitin R but Oxacillin S → flag (Cefoxitin is the surrogate marker)
        if cfx == "R" and oxa == "S":
            issues.append(QAIssue(
                level=2, severity="HIGH",
                category="Phenotype Consistency",
                message="Cefoxitin=R but Oxacillin=S — possible MRSA missed",
                detail=(
                    "Cefoxitin disk diffusion is the preferred MRSA surrogate marker. "
                    "Cefoxitin=R strongly suggests mecA-mediated resistance (MRSA), "
                    "even if Oxacillin reads S (heteroresistance). "
                    "Consider reporting as MRSA and verify with PBP2a/mecA PCR."
                ),
                drug="Cefoxitin, Oxacillin",
                reference="CLSI M100 Ed36 Table 2B · EUCAST Breakpoint Tables v16.0",
            ))

    # ── ESBL / AmpC phenotype note (Gram-negatives) ──
    # INFORMATIONAL, not an error. Under EUCAST v16.0 "report as tested", a
    # susceptible cephalosporin in an ESBL/AmpC producer is reported AS-IS — it is
    # NOT edited to R (that is the pre-2017 practice, withdrawn). ESBL detection is
    # for infection control / surveillance. Preferring a carbapenem in serious
    # ESBL infection (IDSA / MERINO) is a PRESCRIBING decision for the treating
    # physician, not a laboratory reporting edit — so this stays informational and
    # never asks for an S→R edit. (This matches the QC006 override and
    # analyze_antibiotics; the old text here contradicted both.)
    esbl_prob = (esbl_result or {}).get("probability", "low")
    if esbl_prob in ("high", "carbapenemase", "ampc"):
        _mech = ("Carbapenemase" if esbl_prob == "carbapenemase"
                 else "AmpC" if esbl_prob == "ampc" else "ESBL")
        for drug in ("Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefepime"):
            if _is_S(drug, sir):
                issues.append(QAIssue(
                    level=2, severity="MEDIUM",
                    category="Phenotype Consistency",
                    message=f"{_mech} predicted with {drug}=S — report as tested",
                    detail=(
                        f"{_mech} was predicted from the phenotype and {drug} tested S. "
                        f"Report the result AS TESTED (EUCAST v16.0 — do NOT edit S to R; "
                        f"editing susceptible cephalosporins to R on mechanism detection is the "
                        f"pre-2017 practice, withdrawn). The {_mech} call is for infection "
                        f"control and surveillance. Separately — a prescribing decision, not a "
                        f"reporting edit — a carbapenem is preferred over cephalosporins/pip-tazo "
                        f"for serious (non-urinary) ESBL infection even when the cephalosporin "
                        f"tests S (IDSA AMR 2024 / MERINO 2018)."
                    ),
                    drug=drug,
                    reference="EUCAST Breakpoint Tables v16.0 — Enterobacterales note; IDSA AMR 2024",
                ))

    # ── CRE phenotype check ──
    if mdr_result and mdr_result.get("level") in ("XDR", "PDR"):
        for carb in ("Meropenem", "Imipenem/Cilastatin", "Ertapenem"):
            if _is_S(carb, sir):
                issues.append(QAIssue(
                    level=2, severity="HIGH",
                    category="Phenotype Consistency",
                    message=f"XDR/PDR pattern but {carb}=S",
                    detail=(
                        f"XDR/PDR classification requires resistance across multiple categories. "
                        f"{carb}=S in the context of XDR is inconsistent. "
                        f"Verify carbapenem AST and organism identification."
                    ),
                    drug=carb,
                    reference="EUCAST Breakpoint Tables v16.0 · Magiorakos et al. 2012",
                ))

    # ── VRE consistency ──
    if "vre" in org_l or "vancomycin-resistant" in org_l:
        if _is_S("Vancomycin", sir):
            issues.append(QAIssue(
                level=2, severity="CRITICAL",
                category="Phenotype Consistency",
                message="VRE organism but Vancomycin=S — impossible",
                detail=(
                    "VRE (Vancomycin-Resistant Enterococcus) by definition carries vanA/vanB genes. "
                    "Vancomycin=S contradicts the organism designation. "
                    "Review organism identification or AST result."
                ),
                drug="Vancomycin",
                reference="EUCAST Breakpoint Tables v16.0",
            ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 3 — Cross Resistance
# ══════════════════════════════════════════════════════════════════════════════
def _check_cross_resistance(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    # Macrolides: Erythromycin R → Clarithromycin/Azithromycin should be R (MLSB)
    if _is_R("Erythromycin", sir):
        for mac in ("Clarithromycin", "Azithromycin"):
            if _is_S(mac, sir) and mac in sir:
                issues.append(QAIssue(
                    level=3, severity="HIGH",
                    category="Cross Resistance",
                    message=f"Erythromycin=R but {mac}=S — MLSB cross-resistance expected",
                    detail=(
                        f"Erythromycin resistance (erm-mediated MLSB) typically confers resistance "
                        f"to all macrolides including {mac}. {mac}=S in this context is unusual "
                        f"and may indicate an efflux-mediated pattern (M-phenotype) — "
                        f"confirm with D-test and macrolide susceptibility pattern."
                    ),
                    drug=f"Erythromycin, {mac}",
                    reference="CLSI M100 Ed36 · EUCAST Breakpoint Tables v16.0",
                ))

    # Fluoroquinolones: Ciprofloxacin R → Levofloxacin usually R
    if _is_R("Ciprofloxacin", sir) and _is_S("Levofloxacin", sir) and "Levofloxacin" in sir:
        issues.append(QAIssue(
            level=3, severity="MEDIUM",
            category="Cross Resistance",
            message="Ciprofloxacin=R but Levofloxacin=S — verify",
            detail=(
                "Ciprofloxacin and Levofloxacin share resistance mechanisms (gyrA/parC mutations). "
                "Ciprofloxacin=R with Levofloxacin=S is uncommon and requires verification. "
                "Possible for some organisms with step-wise mutation patterns but warrants review."
            ),
            drug="Ciprofloxacin, Levofloxacin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Quinolones: Levofloxacin R → Ciprofloxacin should be R (≥ resistance)
    if _is_R("Levofloxacin", sir) and _is_S("Ciprofloxacin", sir) and "Ciprofloxacin" in sir:
        issues.append(QAIssue(
            level=3, severity="HIGH",
            category="Cross Resistance",
            message="Levofloxacin=R but Ciprofloxacin=S — unexpected pattern",
            detail=(
                "Levofloxacin has higher intrinsic activity than Ciprofloxacin. "
                "Levofloxacin=R with Ciprofloxacin=S is microbiologically inconsistent "
                "for most Gram-negative organisms. Review AST methodology."
            ),
            drug="Levofloxacin, Ciprofloxacin",
            reference="EUCAST Breakpoint Tables v16.0 · CLSI M100 Ed36",
        ))

    # Clindamycin + Erythromycin (D-test relevance flagged)
    if _is_R("Erythromycin", sir) and _is_S("Clindamycin", sir) and "Clindamycin" in sir:
        d_test = (sir.get("D-test") or sir.get("D test") or "").upper()
        if d_test != "NEGATIVE":
            issues.append(QAIssue(
                level=3, severity="HIGH",
                category="Cross Resistance / D-test",
                message="Erythromycin=R + Clindamycin=S — D-test required",
                detail=(
                    "This pattern suggests possible MLSB inducible resistance (iMLSB phenotype). "
                    "Clindamycin may appear susceptible in vitro but fail clinically. "
                    "D-test (double disk diffusion) MUST be performed before reporting Clindamycin as S. "
                    "If D-test positive → report Clindamycin as R."
                    + ("" if not d_test else f" Current D-test: {d_test}.")
                ),
                drug="Erythromycin, Clindamycin",
                reference="CLSI M100 Ed36 · EUCAST Breakpoint Tables v16.0 — Inducible Clindamycin Resistance",
            ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 4 — Beta-lactam Pattern
# ══════════════════════════════════════════════════════════════════════════════
def _check_betalactam_patterns(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    # Ampicillin R + Amoxicillin S → inconsistent (same mechanism)
    if _is_R("Ampicillin", sir) and _is_S("Amoxicillin", sir) and "Amoxicillin" in sir:
        issues.append(QAIssue(
            level=4, severity="HIGH",
            category="Beta-lactam Pattern",
            message="Ampicillin=R but Amoxicillin=S — inconsistent",
            detail=(
                "Ampicillin and Amoxicillin differ only by a hydroxyl group and share "
                "the same resistance mechanisms (beta-lactamase). "
                "Ampicillin=R with Amoxicillin=S is biologically implausible."
            ),
            drug="Ampicillin, Amoxicillin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Cefotaxime R + Ceftriaxone S → inconsistent (same class, same MIC pattern)
    if _is_R("Cefotaxime", sir) and _is_S("Ceftriaxone", sir) and "Ceftriaxone" in sir:
        issues.append(QAIssue(
            level=4, severity="HIGH",
            category="Beta-lactam Pattern",
            message="Cefotaxime=R but Ceftriaxone=S — review needed",
            detail=(
                "Cefotaxime and Ceftriaxone are 3rd-generation cephalosporins with "
                "essentially identical spectrum and resistance mechanisms. "
                "Discordant results strongly suggest a technical or reporting error."
            ),
            drug="Cefotaxime, Ceftriaxone",
            reference="CLSI M100 Ed36",
        ))

    # Cefepime R (4th gen) + Ceftriaxone S (3rd gen) → possible but flag
    if _is_R("Cefepime", sir) and _is_S("Ceftriaxone", sir) and "Ceftriaxone" in sir:
        issues.append(QAIssue(
            level=4, severity="MEDIUM",
            category="Beta-lactam Pattern",
            message="Cefepime=R but Ceftriaxone=S — unusual, verify",
            detail=(
                "Cefepime (4th gen) resistant while Ceftriaxone (3rd gen) sensitive is unusual. "
                "Typically resistance progresses from older to newer generations. "
                "Possible in AmpC derepression (AmpC R to 3rd gen but Cefepime borderline). "
                "However, Cefepime=R with Ceftriaxone=S warrants careful review."
            ),
            drug="Cefepime, Ceftriaxone",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Piperacillin/Tazobactam R + Ceftriaxone S in Gram-negatives
    if (_is_R("Piperacillin + Tazobactam", sir) and _is_S("Ceftriaxone", sir)
            and "Ceftriaxone" in sir):
        issues.append(QAIssue(
            level=4, severity="MEDIUM",
            category="Beta-lactam Pattern",
            message="Pip-Tazo=R but Ceftriaxone=S — unusual pattern",
            detail=(
                "Piperacillin/Tazobactam resistant with Ceftriaxone susceptible is uncommon. "
                "Usually ESBL organisms resistant to both, and non-ESBL organisms sensitive to both. "
                "Consider confirming with ESBL testing."
            ),
            drug="Piperacillin + Tazobactam, Ceftriaxone",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 5 — Carbapenem Pattern
# ══════════════════════════════════════════════════════════════════════════════
def _check_carbapenem_patterns(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    imi  = _r("Imipenem/Cilastatin", sir)
    mero = _r("Meropenem", sir)
    erta = _r("Ertapenem", sir)

    # Imipenem R + Meropenem S → needs verification
    if imi == "R" and mero == "S" and _both_tested("Imipenem/Cilastatin", "Meropenem", sir):
        issues.append(QAIssue(
            level=5, severity="HIGH",
            category="Carbapenem Pattern",
            message="Imipenem=R but Meropenem=S — verify",
            detail=(
                "Imipenem and Meropenem share carbapenem class resistance mechanisms. "
                "Isolated Imipenem resistance with Meropenem susceptibility may occur with "
                "OprD porin loss in Pseudomonas (without carbapenemase), but requires careful review. "
                "Perform carbapenemase testing (CarbaNP / mCIM) to clarify."
            ),
            drug="Imipenem/Cilastatin, Meropenem",
            reference="EUCAST Breakpoint Tables v16.0 · CLSI M100 Ed36",
        ))

    # Meropenem R + Imipenem S → strong alert
    if mero == "R" and imi == "S" and _both_tested("Meropenem", "Imipenem/Cilastatin", sir):
        issues.append(QAIssue(
            level=5, severity="HIGH",
            category="Carbapenem Pattern",
            message="Meropenem=R but Imipenem=S — requires review",
            detail=(
                "Meropenem=R with Imipenem=S is unusual. Possible in organisms with "
                "specific porin mutations combined with AmpC. However, this pattern "
                "requires carbapenemase testing and repeat AST to confirm."
            ),
            drug="Meropenem, Imipenem/Cilastatin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Ertapenem R + Imipenem S → clinically significant (early CRE warning)
    if erta == "R" and imi == "S" and _both_tested("Ertapenem", "Imipenem/Cilastatin", sir):
        issues.append(QAIssue(
            level=5, severity="MEDIUM",
            category="Carbapenem Pattern",
            message="Ertapenem=R + Imipenem=S — possible early CRE/KPC",
            detail=(
                "Ertapenem=R with Imipenem=S can occur with low-level KPC production or "
                "porin loss + AmpC combinations. This is an early CRE warning. "
                "Perform carbapenemase detection immediately (CarbaNP/mCIM/PCR). "
                "Do not dismiss — may progress to full carbapenem resistance."
            ),
            drug="Ertapenem, Imipenem/Cilastatin",
            reference="EUCAST Breakpoint Tables v16.0 · IDSA AMR Guidance v4.0 (2024)",
        ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 6 — Aminoglycoside Pattern
# ══════════════════════════════════════════════════════════════════════════════
def _check_aminoglycoside_patterns(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    genta  = _r("Gentamicin", sir)
    amika  = _r("Amikacin", sir)
    tobra  = _r("Tobramycin", sir)

    # Amikacin R + Gentamicin S → unusual (Amikacin is more resistant to modifying enzymes)
    if amika == "R" and genta == "S" and _both_tested("Amikacin", "Gentamicin", sir):
        issues.append(QAIssue(
            level=6, severity="MEDIUM",
            category="Aminoglycoside Pattern",
            message="Amikacin=R but Gentamicin=S — verify",
            detail=(
                "Amikacin is more resistant to aminoglycoside-modifying enzymes than Gentamicin. "
                "Amikacin=R with Gentamicin=S is uncommon and may suggest a specific AME pattern "
                "(e.g., AAC(6')-Ib-cr). Requires verification — reverse pattern is more expected."
            ),
            drug="Amikacin, Gentamicin",
            reference="CLSI M100 Ed36",
        ))

    # Gentamicin R + Tobramycin S against Pseudomonas — possible but flag
    if (genta == "R" and tobra == "S"
            and _both_tested("Gentamicin", "Tobramycin", sir)):
        issues.append(QAIssue(
            level=6, severity="LOW",
            category="Aminoglycoside Pattern",
            message="Gentamicin=R but Tobramycin=S — review in context",
            detail=(
                "Possible with specific AME enzymes (ANT(2'')-Ia confers Gentamicin/Tobramycin R, "
                "while AAC(3)-I confers Gentamicin R only). Biologically possible but review "
                "against organism-specific AME patterns."
            ),
            drug="Gentamicin, Tobramycin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 7 — Glycopeptide Pattern
# ══════════════════════════════════════════════════════════════════════════════
def _check_glycopeptide_patterns(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    vanco = _r("Vancomycin", sir)
    linz  = _r("Linezolid", sir)

    # Vancomycin R + Linezolid R → extremely rare, flag
    if vanco == "R" and linz == "R":
        issues.append(QAIssue(
            level=7, severity="HIGH",
            category="Glycopeptide Pattern",
            message="Vancomycin=R + Linezolid=R — extremely rare, verify",
            detail=(
                "Vancomycin + Linezolid co-resistance is extremely rare and clinically alarming. "
                "cfr/optrA-mediated Linezolid resistance in VRE has been reported but is rare. "
                "Verify organism ID, repeat AST, and consider sending to reference laboratory. "
                "Treatment options are extremely limited (Daptomycin if susceptible)."
            ),
            drug="Vancomycin, Linezolid",
            reference="CLSI M100 Ed36 · EUCAST Breakpoint Tables v16.0",
        ))

    # Vancomycin R but Teicoplanin S — vanB pattern (flag)
    if vanco == "R" and "Teicoplanin" in sir and _is_S("Teicoplanin", sir):
        issues.append(QAIssue(
            level=7, severity="MEDIUM",
            category="Glycopeptide Pattern",
            message="Vancomycin=R + Teicoplanin=S — vanB phenotype",
            detail=(
                "Vancomycin=R with Teicoplanin=S suggests vanB genotype VRE. "
                "vanB confers variable Vancomycin resistance but retains Teicoplanin susceptibility. "
                "Clinically important — confirm genotype by PCR."
            ),
            drug="Vancomycin, Teicoplanin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 8 — Organism-specific Plausibility
# ══════════════════════════════════════════════════════════════════════════════
_ORG_IMPLAUSIBLE: Dict[str, List[Tuple[str, str, str]]] = {
    # organism → [(drug, result_expected_impossible, explanation)]
    "E. coli": [
        ("Vancomycin",    "S", "E. coli (Gram-negative) is intrinsically resistant to Vancomycin"),
        ("Linezolid",     "S", "Linezolid is not active against Gram-negative organisms"),
        ("Daptomycin",    "S", "Daptomycin has no activity against Gram-negatives"),
    ],
    "Pseudomonas aeruginosa": [
        ("Vancomycin",    "S", "Pseudomonas is intrinsically resistant to Vancomycin"),
        ("Linezolid",     "S", "Linezolid inactive against Gram-negatives"),
        ("Daptomycin",    "S", "Daptomycin inactive against Gram-negatives"),
        ("Doxycycline",   "S", "Doxycycline has limited/unreliable activity vs Pseudomonas"),
    ],
    "Klebsiella spp.": [
        ("Vancomycin",    "S", "Klebsiella (Gram-negative) is intrinsically resistant to Vancomycin"),
        ("Linezolid",     "S", "Linezolid inactive against Gram-negatives"),
    ],
    "Acinetobacter baumannii": [
        ("Vancomycin",    "S", "Acinetobacter is intrinsically resistant to Vancomycin"),
        ("Amoxicillin",   "S", "Acinetobacter is intrinsically resistant to Amoxicillin"),
    ],
    "Staphylococcus aureus": [
        ("Aztreonam",     "S", "Aztreonam has no activity against Gram-positive organisms"),
        ("Colistin",      "S", "Colistin is inactive against Gram-positives"),
        ("Nitrofurantoin","S", "Nitrofurantoin=S in Staph lacks systemic clinical relevance outside UTI"),
    ],
    "MRSA": [
        ("Aztreonam",     "S", "Aztreonam inactive against Gram-positives"),
        ("Colistin",      "S", "Colistin inactive against Gram-positives"),
    ],
    "Streptococcus pneumoniae": [
        ("Aztreonam",     "S", "Aztreonam inactive against Gram-positives"),
        ("Colistin",      "S", "Colistin inactive against Gram-positives"),
    ],
}

def _check_organism_plausibility(organism: str, sir: Dict[str, str]) -> List[QAIssue]:
    issues = []
    checks = _ORG_IMPLAUSIBLE.get(organism, [])
    for drug, impossible_result, explanation in checks:
        if sir.get(drug) == impossible_result:
            issues.append(QAIssue(
                level=8, severity="CRITICAL",
                category="Biological Plausibility",
                message=f"{organism} + {drug}={impossible_result} — biologically impossible",
                detail=(
                    f"{explanation}. "
                    f"Reporting {drug}={impossible_result} for {organism} is microbiologically "
                    f"impossible. This indicates a serious error in either the organism "
                    f"identification or the AST result. Do not use for clinical decisions."
                ),
                drug=drug,
                reference="EUCAST Intrinsic Resistance v3.3 · CLSI M100 Ed36 Appendix B",
            ))
    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 9 — Sample Consistency
# ══════════════════════════════════════════════════════════════════════════════
_UNUSUAL_SPECIMEN_ORGANISM: Dict[str, List[Tuple[str, str, str]]] = {
    "Urine": [
        ("Neisseria meningitidis", "HIGH",
         "N. meningitidis is extremely rare in urine. Consider contamination or wrong specimen label."),
        ("Mycoplasma spp.", "HIGH",
         "Mycoplasma does not grow on standard urine culture media. Verify isolate."),
        ("Stenotrophomonas maltophilia", "MEDIUM",
         "Stenotrophomonas in urine is unusual outside ICU/catheterized patients."),
    ],
    "CSF": [
        ("E. coli", "MEDIUM",
         "E. coli in CSF is primarily seen in neonates. Unusual in adults — verify."),
        ("Staphylococcus aureus", "MEDIUM",
         "S. aureus meningitis is rare; more common after neurosurgery or as hematogenous spread."),
        ("Anaerobes (لاهوائيات)", "HIGH",
         "Anaerobes in CSF are extremely rare. Consider contamination or brain abscess rupture."),
        ("Salmonella spp.", "MEDIUM",
         "Salmonella meningitis is rare — primarily in infants or sickle cell disease."),
        ("Campylobacter jejuni", "HIGH",
         "Campylobacter in CSF is extremely rare. Verify organism ID."),
    ],
    "Blood": [
        ("Lactobacillus", "HIGH",
         "Lactobacillus bacteremia is almost always contamination. Single positive bottle — repeat."),
        ("Campylobacter jejuni", "MEDIUM",
         "Campylobacter bacteremia is rare — mainly in immunocompromised. Verify."),
    ],
    "Stool": [
        ("Staphylococcus aureus", "MEDIUM",
         "S. aureus in stool is usually colonization unless in context of food poisoning outbreak."),
        ("Pseudomonas aeruginosa", "MEDIUM",
         "Pseudomonas in stool is uncommon outside ICU/antibiotic-treated patients."),
        ("MRSA", "HIGH",
         "MRSA in stool usually represents colonization, not infection. Clinical context required."),
    ],
}

def _check_sample_consistency(organism: str, specimen: str) -> List[QAIssue]:
    issues = []
    unusual = _UNUSUAL_SPECIMEN_ORGANISM.get(specimen, [])
    for org_check, severity, detail in unusual:
        if org_check.lower() == organism.lower():
            issues.append(QAIssue(
                level=9, severity=severity,
                category="Sample Consistency",
                message=f"{organism} in {specimen} — unusual isolate",
                detail=detail,
                drug="",
                reference="CLSI M22 2024 / Murray-Washington Criteria",
            ))
    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 11 — QC Rules
# ══════════════════════════════════════════════════════════════════════════════
def _check_qc_rules(sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    # Duplicate drug detection (same drug appearing with different aliases)
    normalized = {}
    for drug, result in sir.items():
        key = re.sub(r"[^a-z0-9]", "", drug.lower())
        if key in normalized:
            issues.append(QAIssue(
                level=11, severity="MEDIUM",
                category="QC — Duplicate",
                message=f"Duplicate antibiotic detected: '{drug}' vs '{normalized[key]}'",
                detail=(
                    f"The antibiotic '{drug}' appears more than once in the AST results "
                    f"(possible OCR double-read). Only one result should be reported. "
                    f"Keep the result with the more reliable SIR value."
                ),
                drug=drug,
                reference="CLSI M2 2024",
            ))
        else:
            normalized[key] = drug

    # Contradictory S+R for same drug (if somehow both appear)
    for drug, result in sir.items():
        for drug2, result2 in sir.items():
            if (drug != drug2 and drug.lower() == drug2.lower()
                    and result != result2):
                issues.append(QAIssue(
                    level=11, severity="HIGH",
                    category="QC — Contradiction",
                    message=f"Contradictory results for same drug: {drug}={result} vs {drug2}={result2}",
                    detail=(
                        f"The same antibiotic has two contradictory AST results. "
                        f"This is a critical reporting error. Choose the validated result."
                    ),
                    drug=drug,
                    reference="CLSI M2 2024",
                ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 12 — Biological Plausibility (Class Level)
# ══════════════════════════════════════════════════════════════════════════════
_GRAM_NEG_ORGANISMS = {
    "E. coli", "Klebsiella spp.", "Pseudomonas aeruginosa",
    "Acinetobacter baumannii", "Proteus mirabilis", "Stenotrophomonas maltophilia",
    "Salmonella spp.", "Shigella spp.", "Campylobacter jejuni",
    "H. influenzae", "Legionella pneumophila",
}
_GRAM_POS_ORGANISMS = {
    "Staphylococcus aureus", "MRSA", "Streptococcus pneumoniae",
    "Enterococcus faecalis", "VRE",
}

def _check_biological_plausibility(organism: str, sir: Dict[str, str]) -> List[QAIssue]:
    issues = []
    is_gn = organism in _GRAM_NEG_ORGANISMS
    is_gp = organism in _GRAM_POS_ORGANISMS

    # Gram-negative reporting Vancomycin=S
    if is_gn and _is_S("Vancomycin", sir):
        issues.append(QAIssue(
            level=12, severity="CRITICAL",
            category="Biological Plausibility",
            message=f"Gram-negative {organism}: Vancomycin=S — impossible",
            detail=(
                "Vancomycin cannot penetrate the outer membrane of Gram-negative bacteria. "
                "Gram-negative + Vancomycin=S is biologically impossible. "
                "Critical error in AST or organism identification."
            ),
            drug="Vancomycin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Gram-negative reporting Linezolid=S
    if is_gn and _is_S("Linezolid", sir):
        issues.append(QAIssue(
            level=12, severity="CRITICAL",
            category="Biological Plausibility",
            message=f"Gram-negative {organism}: Linezolid=S — biologically impossible",
            detail=(
                "Linezolid has no clinically relevant activity against Gram-negative organisms. "
                "Linezolid=S for any Gram-negative is a critical AST error."
            ),
            drug="Linezolid",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Gram-positive reporting Aztreonam=S
    if is_gp and _is_S("Aztreonam", sir):
        issues.append(QAIssue(
            level=12, severity="CRITICAL",
            category="Biological Plausibility",
            message=f"Gram-positive {organism}: Aztreonam=S — impossible",
            detail=(
                "Aztreonam (monobactam) has absolutely no activity against Gram-positive organisms. "
                "Aztreonam=S for any Gram-positive is a critical AST error."
            ),
            drug="Aztreonam",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    # Gram-positive reporting Colistin=S
    if is_gp and _is_S("Colistin", sir):
        issues.append(QAIssue(
            level=12, severity="CRITICAL",
            category="Biological Plausibility",
            message=f"Gram-positive {organism}: Colistin=S — impossible",
            detail=(
                "Colistin (Polymyxin E) targets lipopolysaccharide (LPS) in Gram-negative outer membrane. "
                "It has no activity against Gram-positive organisms. Colistin=S for Gram-positives "
                "is a critical reporting error."
            ),
            drug="Colistin",
            reference="EUCAST Breakpoint Tables v16.0",
        ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 14 — AST Completeness
# ══════════════════════════════════════════════════════════════════════════════
def _check_ast_completeness(organism: str, sir: Dict[str, str]) -> List[QAIssue]:
    issues = []

    # MRSA testing completeness: if Oxacillin present without Cefoxitin
    is_staph = "staphylococcus aureus" in organism.lower() or "mrsa" in organism.lower()
    if is_staph:
        has_oxa = "Oxacillin" in sir
        has_cfx = "Cefoxitin" in sir
        has_clinda = "Clindamycin" in sir
        has_ery = "Erythromycin" in sir or "Erythromycin" in sir
        has_dtest = "D-test" in sir or "D test" in sir

        if has_oxa and not has_cfx:
            issues.append(QAIssue(
                level=14, severity="MEDIUM",
                category="AST Completeness",
                message="Oxacillin tested but Cefoxitin missing — MRSA screen may be incomplete",
                detail=(
                    "CLSI/EUCAST recommend Cefoxitin disk diffusion as the preferred "
                    "surrogate marker for mecA-mediated MRSA (higher sensitivity). "
                    "Testing both Oxacillin and Cefoxitin is recommended for complete MRSA detection."
                ),
                drug="Cefoxitin",
                reference="CLSI M100 Ed36 Table 2B · EUCAST Breakpoint Tables v16.0",
            ))

        if has_clinda and has_ery and not has_dtest:
            ery_r = sir.get("Erythromycin") == "R"
            clinda_s = sir.get("Clindamycin") == "S"
            if ery_r and clinda_s:
                issues.append(QAIssue(
                    level=14, severity="HIGH",
                    category="AST Completeness",
                    message="D-test missing: Erythromycin=R + Clindamycin=S pattern requires D-test",
                    detail=(
                        "When Erythromycin=R and Clindamycin=S, CLSI mandates D-test (double-disk "
                        "diffusion) to detect inducible MLSB resistance. Without D-test, "
                        "Clindamycin should NOT be reported as susceptible."
                    ),
                    drug="D-test",
                    reference="CLSI M100 Ed36",
                ))

    # Pseudomonas: Ceftazidime should be tested
    if organism == "Pseudomonas aeruginosa" and "Ceftazidime" not in sir:
        if any(d in sir for d in ("Meropenem", "Cefepime", "Piperacillin + Tazobactam")):
            issues.append(QAIssue(
                level=14, severity="LOW",
                category="AST Completeness",
                message="Ceftazidime not tested for Pseudomonas aeruginosa",
                detail=(
                    "Ceftazidime is a key anti-pseudomonal agent and should be included "
                    "in Pseudomonas aeruginosa AST panels per CLSI recommendations."
                ),
                drug="Ceftazidime",
                reference="CLSI M100 Ed36 Pseudomonas panel",
            ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# LEVEL 15 — Clinical Context
# ══════════════════════════════════════════════════════════════════════════════
def _check_clinical_context(
    organism: str, specimen: str, sir: Dict[str, str]
) -> List[QAIssue]:
    issues = []

    # Colistin/Polymyxin as first-line in UTI
    if specimen == "Urine" and _is_S("Colistin", sir):
        issues.append(QAIssue(
            level=15, severity="MEDIUM",
            category="Clinical Context",
            message="Colistin=S in Urine: not recommended as first-line despite susceptibility",
            detail=(
                "Colistin achieves poor urinary concentrations (renal metabolism) and "
                "is not appropriate for UTI treatment despite in-vitro susceptibility. "
                "Use only as last resort for XDR organisms with no alternatives."
            ),
            drug="Colistin",
            reference="IDSA AMR Guidance v4.0 (2024) / EUCAST Breakpoint Tables v16.0",
        ))

    # Nitrofurantoin in Blood/Sputum/CSF — not systemic
    if specimen in ("Blood", "Sputum", "CSF") and "Nitrofurantoin" in sir:
        issues.append(QAIssue(
            level=15, severity="HIGH",
            category="Clinical Context",
            message=f"Nitrofurantoin in {specimen}: not clinically appropriate",
            detail=(
                f"Nitrofurantoin is a urinary antiseptic — it achieves therapeutic concentrations "
                f"ONLY in urine. Testing Nitrofurantoin for {specimen} specimens provides no "
                f"clinically meaningful information and should be suppressed from the report."
            ),
            drug="Nitrofurantoin",
            reference="BNF 2025 / EUCAST Breakpoint Tables v16.0",
        ))

    # Fusidic acid as only anti-Staph agent without combination
    if _is_S("Fusidic acid", sir) and not any(
        _is_S(d, sir)
        for d in ("Rifampicin", "Vancomycin", "Linezolid", "Clindamycin",
                  "Trimethoprim/Sulfamethoxazole", "Doxycycline")
    ):
        if specimen == "Blood":
            issues.append(QAIssue(
                level=15, severity="HIGH",
                category="Clinical Context",
                message="Fusidic acid=S without combination partner available",
                detail=(
                    "Fusidic acid must never be used as monotherapy for systemic infections "
                    "(rapid resistance selection within days). A combination antibiotic "
                    "showing susceptibility is required. Review AST panel completeness."
                ),
                drug="Fusidic acid",
                reference="BNF 2025 / EUCAST Breakpoint Tables v16.0",
            ))

    return issues


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════
def run_ast_qa_engine(
    organism: str,
    specimen: str,
    sir_map: Dict[str, str],
    esbl_result: Optional[Dict] = None,
    mdr_result: Optional[Dict] = None,
    skip_categories: Optional[set] = None,
) -> List[QAIssue]:
    """
    Run all QA checks and return issues sorted by severity then level.

    Args:
        organism:     Organism name (must match ORGANISM_PROFILE keys)
        specimen:     Specimen type (Urine, Blood, Sputum, Wound Swab, Pus, Stool, CSF)
        sir_map:      Dict of {drug_name: "S"|"I"|"R"}
        esbl_result:  Output from predict_esbl() — optional
        mdr_result:   Output from classify_mdr() — optional
        skip_categories: Categories to drop from the result. The host app passes
                      {"Intrinsic Resistance", "Clinical Context"} when the
                      ast_reportability module is loaded, because that module
                      already renders both in the AST Quality Control panel and
                      the two were printing every such finding twice.

    Returns:
        List[QAIssue] sorted: CRITICAL → HIGH → MEDIUM → LOW
    """
    if not organism or not sir_map:
        return []

    issues: List[QAIssue] = []

    issues += _check_intrinsic_resistance(organism, sir_map)
    issues += _check_phenotype_consistency(organism, sir_map, esbl_result, mdr_result)
    issues += _check_cross_resistance(sir_map)
    issues += _check_betalactam_patterns(sir_map)
    issues += _check_carbapenem_patterns(sir_map)
    issues += _check_aminoglycoside_patterns(sir_map)
    issues += _check_glycopeptide_patterns(sir_map)
    issues += _check_organism_plausibility(organism, sir_map)
    issues += _check_sample_consistency(organism, specimen)
    issues += _check_qc_rules(sir_map)
    issues += _check_biological_plausibility(organism, sir_map)
    issues += _check_ast_completeness(organism, sir_map)
    issues += _check_clinical_context(organism, specimen, sir_map)

    if skip_categories:
        issues = [i for i in issues if i.category not in skip_categories]

    issues.sort(key=lambda x: (_SEV_ORDER.get(x.severity, 4), x.level))
    return issues


__all__ = ["QAIssue", "run_ast_qa_engine"]
