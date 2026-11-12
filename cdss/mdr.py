"""MDR / XDR / PDR classification - Magiorakos et al. 2012 (ECDC/CDC).

Definitions implemented exactly as published:

    MDR  non-susceptible to >=1 agent in >=3 antimicrobial categories
    XDR  non-susceptible to >=1 agent in all but <=2 categories
    PDR  non-susceptible to ALL agents in ALL categories

and three safeguards on top:

  * intrinsic resistance is removed before counting;
  * the category panel is organism-specific (Enterobacterales / P. aeruginosa /
    Acinetobacter / Gram-positive), as in the paper's separate tables;
  * XDR/PDR are held at MDR when the panel is too thin to support them.

WHAT "NON-SUSCEPTIBLE" MEANS DEPENDS ON THE STANDARD. Magiorakos (2012) counts
I together with R. Under EUCAST since 2019, "I" is "susceptible, increased
exposure" - a SUSCEPTIBLE category - and counting it as non-susceptible
inflates MDR/XDR for isolates EUCAST expects to read I. So `interp_std`
decides: CLSI -> I is non-susceptible; EUCAST -> only R is.

`conservative_resistant_categories` (categories with NO susceptible agent left)
is returned as metadata for the therapeutic read-out. It never sets the level.
"""
from __future__ import annotations

from typing import Any, Dict

from clinical_data import MDR_CATEGORIES, get_mdr_panel

from .organisms import identify, strip_intrinsic
from .sir import normalize_sir_map

_MAGIORAKOS_GROUPS = ("enterobacterales", "pseudomonas", "acinetobacter",
                      "s_aureus", "enterococcus")


def _empty(gram: str = "") -> Dict[str, Any]:
    return {
        "level": None, "resistant_categories": [], "susceptible_categories": [],
        "total_tested": 0, "total_categories_evaluable": 0, "resistant_count": 0,
        "single_drug_categories": [], "conservative_resistant_categories": [],
        "reliable": False, "warnings": [], "gram": gram,
    }


def classify_mdr(organism: str, sir_map: Dict[str, str],
                 interp_std: str = "CLSI") -> Dict[str, Any]:
    sir = normalize_sir_map(sir_map)
    if not sir:
        return _empty()

    org = identify(organism)
    clean = strip_intrinsic(organism, sir)
    is_gram_pos = org.gram == "positive"
    gram = "positive" if is_gram_pos else "negative"
    applicable = get_mdr_panel(org.key or organism, is_gram_pos)
    non_susceptible = ("R",) if str(interp_std).upper() == "EUCAST" else ("R", "I")

    resistant, susceptible, single, conservative = [], [], [], []
    for cat, drugs in MDR_CATEGORIES.items():
        if cat not in applicable:
            continue
        tested = [d for d in drugs if clean.get(d) in ("S", "I", "R")]
        if not tested:
            continue
        if len(tested) == 1:
            single.append(cat)
        if any(clean[d] in non_susceptible for d in tested):
            resistant.append(cat)
        else:
            susceptible.append(cat)
        if all(clean[d] in non_susceptible for d in tested):
            conservative.append(cat)

    total = len(resistant) + len(susceptible)
    r_count = len(resistant)
    if total == 0:
        out = _empty(gram)
        return out

    enough_cats = total >= 6
    multi_agent_resistant = [c for c in resistant if c not in set(single)]
    enough_multi = len(multi_agent_resistant) >= 3
    no_susceptible_anywhere = len(conservative) == total
    looks_extreme = r_count >= 3 and (total - r_count) <= 2

    if no_susceptible_anywhere and enough_cats and enough_multi:
        level = "PDR"
    elif looks_extreme and enough_cats and enough_multi:
        level = "XDR"
    elif r_count >= 3:
        level = "MDR"
    else:
        level = None

    capped = looks_extreme and not (enough_cats and enough_multi)
    reliable = total >= 4
    warnings = []
    if not reliable:
        warnings.append(f"⚠️ Only {total} categories testable — MDR classification may be unreliable.")
    if single:
        warnings.append(f"⚠️ Categories judged on a single agent: {', '.join(single)}")
    if capped:
        warnings.append("⚠️ Resistance pattern suggests XDR/PDR, but the evidence is too thin "
                        "(few categories, or resistant categories rest on a single agent each) — "
                        "reported as MDR. Expand the panel with ≥2 agents per category to confirm.")
    if level and not any(org.is_(g) for g in _MAGIORAKOS_GROUPS):
        warnings.append("ℹ️ MDR/XDR/PDR definitions (Magiorakos 2012) are published for "
                        "S. aureus, Enterococcus, Enterobacterales, P. aeruginosa and "
                        "Acinetobacter only — the label is indicative for this organism.")

    return {
        "level": level,
        "resistant_categories": resistant,
        "susceptible_categories": susceptible,
        "total_tested": total,
        "total_categories_evaluable": total,
        "resistant_count": r_count,
        "single_drug_categories": single,
        "conservative_resistant_categories": conservative,
        "reliable": reliable,
        "warnings": warnings,
        "gram": gram,
        "interp_std": str(interp_std).upper(),
    }
