"""Orange Lab CDSS — clinical scenario matrix.

Generates the (organism x specimen x AST-archetype) grid that test_scenarios.py
snapshots and asserts invariants over.

WHY A MATRIX AND NOT EXHAUSTIVE ENUMERATION
-------------------------------------------
With 50 agents each S / I / R / untested, one organism-specimen pair alone has
4**50 ~= 1.3e30 states. Enumerating them is not slow, it is impossible. What IS
finite and worth covering is the set of CLINICAL SITUATIONS the engine claims to
recognise: wild type, ESBL, AmpC, carbapenemase, OXA-48-like, CRPA, DTR, MRSA,
VRE, MDR, XDR, PDR, a reported result that contradicts intrinsic resistance, a
urinary-only agent reported off-site, and a panel too thin to conclude anything.

Every archetype is built DETERMINISTICALLY from the organism's own profile, so
the grid regenerates identically on every machine and a snapshot diff always
means the engine changed — never that the test data drifted.

This module imports nothing from Streamlit. It is pure data construction.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from clinical_data import INTRINSIC_RESISTANCE
from organism_profile import ORGANISM_PROFILE
from specimen_organism_map import SPECIMEN_ORGANISM_MAP

# ── Drug groupings the archetypes manipulate ─────────────────────────────────
CEPH_3G      = ["Ceftriaxone", "Cefotaxime", "Cefixime"]
CEPH_AP      = ["Ceftazidime", "Cefoperazone", "Cefoperazone + Sulbactam"]
CEPH_4G      = ["Cefepime"]
CEPH_LOW     = ["Cephalexin", "Cefadroxil", "Cephradine", "Cefaclor",
                "Cefuroxime", "Cefuroxime sodium", "Cefazolin"]
CEPHAMYCIN   = ["Cefoxitin"]
CARBAPENEMS  = ["Imipenem/Cilastatin", "Meropenem", "Ertapenem"]
FLUOROQUIN   = ["Ciprofloxacin", "Levofloxacin", "Ofloxacin", "Norfloxacin"]
AMINOGLYC    = ["Gentamicin", "Amikacin", "Tobramycin"]
BLI_COMBOS   = ["Amoxicillin + Clavulanic acid", "Ampicillin/Sulbactam",
                "Piperacillin + Tazobactam"]
URINARY_ONLY = ["Nitrofurantoin", "Fosfomycin", "Norfloxacin"]
GRAM_POS_ONLY = ["Vancomycin", "Linezolid", "Teicoplanin", "Daptomycin"]
MRSA_MARKERS = ["Oxacillin", "Cefoxitin"]

# A broad but realistic Gram-negative panel — what an Egyptian private lab
# actually puts on the plate for an Enterobacterales / non-fermenter isolate.
GN_PANEL = [
    "Amoxicillin + Clavulanic acid", "Ampicillin/Sulbactam",
    "Piperacillin + Tazobactam", "Cefuroxime", "Cefoxitin",
    "Ceftriaxone", "Cefotaxime",
    "Ceftazidime", "Cefepime", "Cefoperazone + Sulbactam",
    "Imipenem/Cilastatin", "Meropenem", "Ertapenem",
    "Gentamicin", "Amikacin", "Ciprofloxacin", "Levofloxacin",
    "Trimethoprim/Sulfamethoxazole", "Doxycycline", "Minocycline",
    "Tetracycline", "Colistin",
]
GP_PANEL = [
    "Penicillin", "Oxacillin", "Amoxicillin + Clavulanic acid", "Cefoxitin",
    "Cephalexin", "Ceftriaxone", "Erythromycin", "Clindamycin",
    "Ciprofloxacin", "Levofloxacin", "Gentamicin",
    "Trimethoprim/Sulfamethoxazole", "Doxycycline", "Vancomycin", "Linezolid",
]
URINE_EXTRA = ["Nitrofurantoin", "Fosfomycin", "Norfloxacin"]

GRAM_POS_ORGS = ("staphylococcus", "staph", "mrsa", "mssa", "enterococc",
                 "streptococc", "listeria", "vre")


def _is_gram_pos(organism: str) -> bool:
    ol = organism.lower()
    return any(g in ol for g in GRAM_POS_ORGS)


def intrinsic_for(organism: str) -> set:
    """Drugs this organism is intrinsically resistant to (canonical table)."""
    ol = (organism or "").lower().strip()
    out: set = set()
    for key, drugs in INTRINSIC_RESISTANCE.items():
        if key and (key in ol or ol in key):
            out |= set(drugs)
    return out


def base_panel(organism: str, specimen: str) -> List[str]:
    """The agents a lab would actually report for this isolate and site.

    Intrinsically resistant agents are EXCLUDED here — a competent lab does not
    put them on the plate. The `intrinsic_violation` archetype adds one back on
    purpose, which is the only way to exercise the QC rule that catches it.
    """
    panel = list(GP_PANEL if _is_gram_pos(organism) else GN_PANEL)
    # The organism's own guideline drugs, so profile-specific agents are covered.
    prof = ORGANISM_PROFILE.get(organism) or {}
    for tier in ("first_line", "second_line", "third_line"):
        for drug in prof.get(tier, []):
            if drug not in panel:
                panel.append(drug)
    if "urine" in specimen.lower():
        panel += [d for d in URINE_EXTRA if d not in panel]
    intrinsic = intrinsic_for(organism)
    return [d for d in panel if d not in intrinsic]


# ── Archetypes ───────────────────────────────────────────────────────────────
# Each returns {drug: S/I/R} or None when the archetype does not apply to this
# organism (e.g. ESBL on a Gram-positive). None means "skip", not "fail".

def _all(panel: List[str], value: str) -> Dict[str, str]:
    return {d: value for d in panel}


def _set(sir: Dict[str, str], drugs: List[str], value: str) -> Dict[str, str]:
    for d in drugs:
        if d in sir:
            sir[d] = value
    return sir


def arch_wild_type(org, spec, panel):
    return _all(panel, "S")


def arch_esbl(org, spec, panel):
    if _is_gram_pos(org):
        return None
    sir = _all(panel, "S")
    _set(sir, CEPH_3G + CEPH_AP + CEPH_LOW, "R")
    _set(sir, ["Amoxicillin + Clavulanic acid", "Ampicillin/Sulbactam"], "R")
    _set(sir, CARBAPENEMS, "S")          # the defining feature of plain ESBL
    return sir


def arch_ampc(org, spec, panel):
    if _is_gram_pos(org):
        return None
    sir = _all(panel, "S")
    _set(sir, CEPH_3G + CEPH_LOW + CEPHAMYCIN, "R")
    _set(sir, BLI_COMBOS, "R")
    _set(sir, CEPH_4G + CARBAPENEMS, "S")   # cefepime spared = AmpC signature
    return sir


def arch_carbapenemase(org, spec, panel):
    if _is_gram_pos(org):
        return None
    sir = _all(panel, "S")
    _set(sir, CEPH_3G + CEPH_AP + CEPH_4G + CEPH_LOW + BLI_COMBOS, "R")
    _set(sir, CARBAPENEMS, "R")
    return sir


def arch_oxa48(org, spec, panel):
    if _is_gram_pos(org) or "Ertapenem" not in panel:
        return None
    sir = _all(panel, "S")
    _set(sir, CEPH_3G, "R")
    _set(sir, ["Ertapenem"], "R")
    _set(sir, ["Meropenem", "Imipenem/Cilastatin"], "S")
    return sir


def arch_crpa_non_dtr(org, spec, panel):
    """Carbapenem-R P. aeruginosa that still has an active traditional agent."""
    if "pseudomonas" not in org.lower():
        return None
    sir = _all(panel, "S")
    _set(sir, ["Meropenem", "Imipenem/Cilastatin"], "R")
    _set(sir, FLUOROQUIN, "R")
    _set(sir, ["Ceftazidime", "Cefepime", "Piperacillin + Tazobactam"], "S")
    return sir


def arch_dtr(org, spec, panel):
    """Non-susceptible to every first-line beta-lactam AND fluoroquinolone."""
    if "pseudomonas" not in org.lower():
        return None
    sir = _all(panel, "S")
    _set(sir, ["Piperacillin + Tazobactam", "Ceftazidime", "Cefepime",
               "Aztreonam", "Meropenem", "Imipenem/Cilastatin"], "R")
    _set(sir, FLUOROQUIN, "R")
    _set(sir, ["Colistin"], "S")
    return sir


def arch_mrsa(org, spec, panel):
    if not any(k in org.lower() for k in ("staphylococcus", "staph", "mrsa")):
        return None
    sir = _all(panel, "S")
    _set(sir, MRSA_MARKERS + ["Penicillin", "Cephalexin", "Ceftriaxone",
                              "Amoxicillin + Clavulanic acid"], "R")
    _set(sir, ["Vancomycin", "Linezolid"], "S")
    return sir


def arch_vre(org, spec, panel):
    if "enterococc" not in org.lower() and "vre" not in org.lower():
        return None
    sir = _all(panel, "S")
    _set(sir, ["Vancomycin"], "R")
    _set(sir, ["Linezolid"], "S")
    return sir


def arch_mdr(org, spec, panel):
    """Non-susceptible in >=3 antimicrobial categories (Magiorakos 2012)."""
    sir = _all(panel, "S")
    _set(sir, CEPH_3G + CEPH_LOW, "R")
    _set(sir, FLUOROQUIN, "R")
    _set(sir, AMINOGLYC, "R")
    return sir


def arch_xdr(org, spec, panel):
    """Susceptible to <=2 categories only."""
    sir = _all(panel, "R")
    _set(sir, ["Colistin"] if not _is_gram_pos(org) else ["Linezolid"], "S")
    return sir


def arch_pdr(org, spec, panel):
    return _all(panel, "R")


def arch_intrinsic_violation(org, spec, panel):
    """A drug the organism CANNOT respond to, reported Susceptible.

    This is the single most dangerous laboratory error the QC layer exists to
    catch, so every organism that has any intrinsic entry gets a case.
    """
    intr = sorted(intrinsic_for(org))
    if not intr:
        return None
    sir = _all(panel, "S")
    sir[intr[0]] = "S"
    return sir


def arch_urine_agent_offsite(org, spec, panel):
    """Nitrofurantoin reported on a non-urine isolate."""
    if "urine" in spec.lower():
        return None
    if "Nitrofurantoin" in intrinsic_for(org):
        return None
    sir = _all(panel, "S")
    sir["Nitrofurantoin"] = "S"
    return sir


def arch_thin_panel(org, spec, panel):
    """Two agents only — MDR/XDR must refuse to over-conclude."""
    keep = [d for d in panel if d in ("Ciprofloxacin", "Gentamicin")][:2]
    if len(keep) < 2:
        keep = panel[:2]
    return {d: "R" for d in keep}


ARCHETYPES: List[Tuple[str, object]] = [
    ("wild_type",           arch_wild_type),
    ("esbl",                arch_esbl),
    ("ampc",                arch_ampc),
    ("carbapenemase",       arch_carbapenemase),
    ("oxa48_like",          arch_oxa48),
    ("crpa_non_dtr",        arch_crpa_non_dtr),
    ("dtr_pseudomonas",     arch_dtr),
    ("mrsa",                arch_mrsa),
    ("vre",                 arch_vre),
    ("mdr",                 arch_mdr),
    ("xdr",                 arch_xdr),
    ("pdr",                 arch_pdr),
    ("intrinsic_violation", arch_intrinsic_violation),
    ("urine_agent_offsite", arch_urine_agent_offsite),
    ("thin_panel",          arch_thin_panel),
]


# ── Organisms the UI map does not reach ──────────────────────────────────────
#  SPECIMEN_ORGANISM_MAP lists only the 19 organisms the picker offers, but
#  clinical_data.INTRINSIC_RESISTANCE carries 34 keys. Serratia, Enterobacter,
#  Citrobacter, Morganella, Providencia, P. vulgaris, Listeria, S. pyogenes,
#  S. agalactiae and E. faecium therefore had rules that NO scenario exercised —
#  a Serratia tetracycline correction could be made and the snapshot would not
#  move. Every table key that the map cannot reach is run here against the
#  specimen it is most often isolated from, so no rule is left untested.
UNMAPPED_ORGANISMS: List[Tuple[str, str]] = [
    ("Escherichia coli",              "Urine"),
    ("Klebsiella pneumoniae",         "Sputum"),
    ("Klebsiella oxytoca",            "Urine"),
    ("Proteus vulgaris",              "Wound Swab"),
    ("Morganella morganii",           "Urine"),
    ("Providencia spp.",              "Urine"),
    ("Serratia marcescens",           "Blood"),
    ("Enterobacter cloacae",          "Blood"),
    ("Enterobacter aerogenes",        "Sputum"),
    ("Hafnia alvei",                  "Wound Swab"),
    ("Citrobacter freundii",          "Urine"),
    ("Citrobacter koseri",            "Urine"),
    ("Enterococcus faecium",          "Blood"),
    ("Streptococcus pyogenes",        "Wound Swab"),
    ("Streptococcus agalactiae",      "Urine"),
    ("Listeria monocytogenes",        "CSF"),
]


def build_matrix() -> List[Dict]:
    """Every (specimen, organism, archetype) case, in a stable order."""
    cases: List[Dict] = []
    pairs = [(sp, og) for sp in sorted(SPECIMEN_ORGANISM_MAP)
             for og in SPECIMEN_ORGANISM_MAP[sp]]
    pairs += [(sp, og) for og, sp in UNMAPPED_ORGANISMS]
    for specimen, organism in pairs:
        if True:
            panel = base_panel(organism, specimen)
            if not panel:
                continue
            for name, fn in ARCHETYPES:
                sir = fn(organism, specimen, panel)
                if not sir:
                    continue
                cases.append({
                    "id":        f"{specimen}|{organism}|{name}",
                    "specimen":  specimen,
                    "organism":  organism,
                    "archetype": name,
                    "sir_map":   {k: sir[k] for k in sorted(sir)},
                })
    return cases


if __name__ == "__main__":
    m = build_matrix()
    print(f"{len(m)} scenarios across "
          f"{len({(c['specimen'], c['organism']) for c in m})} organism x specimen pairs")
    from collections import Counter
    for k, v in Counter(c["archetype"] for c in m).most_common():
        print(f"  {k:22s} {v}")
