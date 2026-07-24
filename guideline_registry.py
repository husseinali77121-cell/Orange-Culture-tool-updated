#!/usr/bin/env python3
"""
Orange Lab CDSS — Guideline Citation Registry
==============================================

WHY THIS FILE EXISTS
--------------------
Every clinical rule in this codebase carries a citation string in a comment or a
`"reference"` field. Those strings were written by hand, at different times, and
they drifted: the same rule was cited as "EUCAST v3.3", "EUCAST Expert Rules",
"EUCAST Intrinsic Resistance v3.3, Table 3" and "EUCAST 2026" in four places.
Worse, some of them were simply out of date and nothing in the system could tell.

A citation that nobody can mechanically check is decoration. This registry turns
citations into DATA:

  * SOURCES  — the versioned documents the lab actually stands behind, each with
               a publication date and a URL a reviewer can open.
  * RULES    — one row per clinical assertion, naming the source and the exact
               locus (table/section) inside it, plus who verified it and when.

`test_guidelines.py` then enforces three things that a comment cannot:
  1. every rule points at a source that exists in SOURCES;
  2. no rule cites a source that has been superseded by a newer one listed here;
  3. no rule goes longer than STALENESS_MONTHS without human re-verification.

VERIFICATION LEVELS
-------------------
  "primary" — a human opened the cited document and confirmed the assertion.
              Requires `verified_by` and `verified_on`.
  "pending" — carried over from earlier development; plausible and consistent
              with the rest of the table, but NOT yet checked against the source
              document by a human. Run `python guideline_registry.py --queue`
              to print the outstanding list with direct links.

"pending" is deliberately visible rather than hidden. A registry that quietly
marks everything verified is worse than no registry at all.

CURRENT DOCUMENT VERSIONS (checked 2026-07-22)
----------------------------------------------
  EUCAST breakpoint tables ............ v16.1  (v16.0 Jan 2026; 16.1 adds anaerobes)
  CLSI M100 ........................... Ed36   (January 2026)
  EUCAST Expected Resistant Phenotypes  v1.2   (January 2023)

  NOTE ON THE RENAME: EUCAST retired the term "intrinsic resistance" in 2022 and
  replaced it with "expected resistant phenotype", because a species' expected
  behaviour can change over time and the breakpoints are always exposure-
  dependent. The tables formerly published as "EUCAST Intrinsic Resistance and
  Unusual Phenotypes, Expert Rules v3.3" are now "Expected Resistant Phenotypes
  v1.2". This codebase still uses the identifier INTRINSIC_RESISTANCE internally
  (renaming a table consumed by 6 modules is a separate change) but every
  outward-facing CITATION now names the current document.

Usage:
    python guideline_registry.py            # summary
    python guideline_registry.py --queue    # list rules awaiting verification
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict

# How long a "primary" verification stays valid before it must be re-checked.
# 18 months is chosen so that every rule is re-read at least once per two annual
# guideline cycles (EUCAST and CLSI both publish each January).
STALENESS_MONTHS = 18

_HA = "Dr. Hussein Ali"

# ============================================================================
#  SOURCES — the versioned documents this system stands behind
# ============================================================================
SOURCES: Dict[str, Dict[str, Any]] = {
    "EUCAST_BP": {
        "title": "EUCAST Breakpoint tables for interpretation of MICs and zone diameters",
        "version": "16.1",
        "published": "2026-01",
        "url": "https://www.eucast.org/bacteria/clinical-breakpoints-and-interpretation/clinical-breakpoint-tables/",
        "note": "v16.0 published first week of January 2026; v16.1 adds breakpoints "
                "for additional anaerobic species.",
    },
    "EUCAST_EXPECTED_R": {
        "title": "EUCAST Expected Resistant Phenotypes",
        "version": "1.2",
        "published": "2023-01",
        "url": "https://www.eucast.org/fileadmin/eucast/pdf/expert_rules/Expected_Resistant_Phenotypes_v1.2_20230113.pdf",
        "supersedes": "EUCAST_EXPERT_V33",
        "note": "The current EUCAST authority on what this codebase calls "
                "'intrinsic resistance'. Inclusion threshold: >=90% of isolates "
                "of the species are expected resistant.",
    },
    "EUCAST_EXPECTED_S": {
        "title": "EUCAST Expected Susceptible Phenotypes",
        "version": "1.1",
        "published": "2022-03",
        "url": "https://www.eucast.org/fileadmin/eucast/pdf/expert_rules/Expected_Susceptible_Phenotypes_Tables_v1.1_20220325.pdf",
        "note": "Threshold: wild type susceptible and ~99% devoid of acquired "
                "resistance. Used for 'this result should be disbelieved' checks.",
    },
    "EUCAST_EXPERT_V33": {
        "title": "EUCAST Expert Rules, Intrinsic Resistance and Unusual Phenotypes",
        "version": "3.3",
        "published": "2021-10",
        "url": "https://www.eucast.org/bacteria/document-archive/",
        "superseded_by": "EUCAST_EXPECTED_R",
        "note": "SUPERSEDED for the intrinsic/expected-phenotype tables. Kept in "
                "the registry only so that any surviving citation to it is "
                "detected by test_guidelines.py rather than silently accepted.",
    },
    "EUCAST_RESIST_DETECT": {
        "title": "EUCAST guidelines for detection of resistance mechanisms and "
                 "specific resistances of clinical and/or epidemiological importance",
        "version": "2.0",
        "published": "2017-07",
        "url": "https://www.eucast.org/bacteria/important-additional-information/resistance-detection/",
        "note": "Source for the ESBL/AmpC/carbapenemase inference logic AND for "
                "the absence of any validated phenotypic carbapenemase algorithm "
                "in P. aeruginosa.",
    },
    "CLSI_M100": {
        "title": "CLSI M100 Performance Standards for Antimicrobial Susceptibility Testing",
        "version": "Ed36",
        "published": "2026-01",
        "url": "https://clsi.org/standards/products/microbiology/documents/m100/",
        "note": "Default interpretation standard in this deployment; the report "
                "states which standard was used.",
    },
    "IDSA_AMR": {
        "title": "IDSA Guidance on the Treatment of Antimicrobial-Resistant "
                 "Gram-Negative Infections",
        "version": "2024 update",
        "published": "2024-08",
        "url": "https://www.idsociety.org/practice-guideline/amr-guidance/",
        "note": "ESBL-E, AmpC-E, CRE, DTR-P. aeruginosa, CRAB, S. maltophilia.",
    },
    "MAGIORAKOS": {
        "title": "Magiorakos et al. — Multidrug-resistant, extensively drug-resistant "
                 "and pandrug-resistant bacteria: an international expert proposal "
                 "for interim standard definitions for acquired resistance",
        "version": "2012",
        "published": "2012-03",
        "url": "https://doi.org/10.1111/j.1469-0691.2011.03570.x",
        "note": "MDR/XDR/PDR definitions. Non-susceptible = R + I.",
    },
    "WHO_AWARE": {
        "title": "WHO AWaRe classification of antibiotics",
        "version": "2023",
        "published": "2023-09",
        "url": "https://www.who.int/publications/i/item/WHO-MHP-HPS-EML-2023.04",
        "note": "Access / Watch / Reserve tiers used in the ranking engine.",
    },
    "WHO_BPPL": {
        "title": "WHO Bacterial Priority Pathogens List",
        "version": "2024",
        "published": "2024-05",
        "url": "https://www.who.int/publications/i/item/9789240093461",
        "note": "Priority tiers for escalation wording.",
    },
}

# ============================================================================
#  RULES — one row per clinical assertion made by the code
# ============================================================================
RULES: Dict[str, Dict[str, Any]] = {

    # ── Expected resistant phenotypes (Gram-negative) ───────────────────────
    "intr_klebsiella_ampicillin": {
        "assertion": "Klebsiella spp. are expected resistant to ampicillin and "
                     "amoxicillin (chromosomal SHV/LEN penicillinase). "
                     "Beta-lactamase-inhibitor combinations are NOT covered.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 1 (Enterobacterales)",
        "verified": "pending",
    },
    "intr_proteus_mirabilis": {
        "assertion": "P. mirabilis is expected resistant to tetracyclines, "
                     "tigecycline, colistin/polymyxin and nitrofurantoin.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 1",
        "verified": "pending",
    },
    "intr_morganella_providencia_proteus_vulgaris": {
        "assertion": "Morganella, Providencia, P. vulgaris and P. penneri carry "
                     "chromosomal AmpC plus species traits -> aminopenicillins "
                     "(ampicillin AND amoxicillin, therefore amox-clav), 1st/2nd-gen "
                     "cephalosporins and cephamycins (cefoxitin), tetracyclines, "
                     "colistin, nitrofurantoin. Sulbactam does NOT inhibit "
                     "chromosomal AmpC, so ampicillin-sulbactam is not exempt.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 1",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Row added after the drug list was found to omit 'amoxicillin' and "
                "the oral 1st-gen cephalosporins, letting amox-clav / cephalexin / "
                "cefadroxil / cefaclor / cefoxitin escape a rule that "
                "clinical_data.INTRINSIC_RESISTANCE applied to them.",
    },
    "intr_serratia": {
        "assertion": "S. marcescens: chromosomal AmpC -> aminopenicillins, 1st/2nd-gen "
                     "cephalosporins, cephamycins; plus colistin and nitrofurantoin. "
                     "Resistant to tetracycline and doxycycline but NOT to minocycline "
                     "or tigecycline.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 1",
        "verified": "pending",
    },
    "intr_enterobacter_citrobacter_ampc": {
        "assertion": "Inducible chromosomal AmpC (Enterobacter, K. aerogenes, "
                     "C. freundii, Hafnia) -> aminopenicillins, amoxicillin-clavulanate, "
                     "ampicillin-sulbactam, 1st/2nd-gen cephalosporins and cephamycins. "
                     "Sulbactam does not inhibit AmpC, so amp-sulbactam is NOT exempt.",
        "source": "IDSA_AMR", "locus": "AmpC-E section",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
    },
    "intr_pseudomonas": {
        "assertion": "P. aeruginosa is expected resistant to aminopenicillins, "
                     "1st/2nd-gen and non-antipseudomonal 3rd-gen cephalosporins, "
                     "ertapenem, tetracyclines, tigecycline, trimethoprim, "
                     "chloramphenicol and nitrofurantoin. Ceftazidime and cefepime "
                     "remain active.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 2 (non-fermenters)",
        "verified": "pending",
    },
    "intr_acinetobacter": {
        "assertion": "Acinetobacter spp. are expected resistant to ampicillin, "
                     "amoxicillin, AMOXICILLIN-CLAVULANATE, aztreonam, ertapenem, "
                     "trimethoprim, chloramphenicol and fosfomycin. "
                     "Ampicillin-SULBACTAM is the exception -- sulbactam has intrinsic "
                     "anti-Acinetobacter activity of its own.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 2",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "This row exists because ast_reportability.py previously EXCLUDED "
                "'clav' from the rule, exempting amox-clav from a restriction that "
                "applies to it. Clavulanate has no useful activity against "
                "Acinetobacter; sulbactam does. See test_intrinsic_sync.py [2].",
    },
    "intr_stenotrophomonas": {
        "assertion": "S. maltophilia: L1 metallo-beta-lactamase -> all carbapenems, "
                     "plus expected aminoglycoside and most beta-lactam resistance. "
                     "TMP-SMX is the established agent.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 2",
        "verified": "pending",
    },
    "intr_entero_gram_pos_agents": {
        "assertion": "Enterobacterales are expected resistant to benzylpenicillin, "
                     "glycopeptides, fusidic acid, macrolides, lincosamides, "
                     "streptogramins, rifampicin, daptomycin and linezolid "
                     "(outer membrane exclusion).",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 1 header",
        "verified": "pending",
    },

    # ── Expected resistant phenotypes (Gram-positive) ───────────────────────
    "intr_gram_pos_gram_neg_agents": {
        "assertion": "Gram-positive bacteria as a group -- not staphylococci only "
                     "-- are expected resistant to aztreonam, temocillin, "
                     "polymyxin B/colistin and nalidixic acid.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 3 (Gram-positive) header",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Renamed from intr_staph_gram_neg_agents and widened after the "
                "scenario matrix (INV-9) showed S. pneumoniae, streptococci, "
                "enterococci and Listeria all escaping a rule the EUCAST table "
                "states for the whole Gram-positive group.",
    },
    "intr_salmonella_shigella_invivo": {
        "assertion": "Salmonella and Shigella test susceptible in vitro to oral "
                     "1st/2nd-generation cephalosporins and to aminoglycosides but "
                     "these agents FAIL in vivo (no intracellular penetration). "
                     "They must not be reported as susceptible.",
        "source": "CLSI_M100", "locus": "Table 2A comment on Salmonella/Shigella",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Scoped deliberately to cephalosporins and aminoglycosides. An "
                "earlier draft also listed colistin and nitrofurantoin, which the "
                "CLSI comment does NOT cover -- that over-reach made the QC layer "
                "contradict the recommendation engine (caught by INV-4).",
    },
    "intr_vre_glycopeptide_contradiction": {
        "assertion": "An isolate identified as VRE that reports vancomycin or "
                     "teicoplanin SUSCEPTIBLE is a contradiction between the "
                     "identification and the result. Re-check both before release.",
        "source": "EUCAST_EXPECTED_R", "locus": "Use of expected phenotypes for validation",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "EUCAST: a result contradicting the expected phenotype should be "
                "viewed with suspicion. Filed as a reportability rule because the "
                "engine's organism string is literally 'VRE'.",
    },
    "intr_enterococcus_cephalosporins": {
        "assertion": "Enterococci are expected resistant to ALL cephalosporins, "
                     "clindamycin, fusidic acid and aztreonam.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 3",
        "verified": "pending",
        "note": "Rule matches on 'enterococc' AND the literal string 'VRE' -- the "
                "UI offers 'VRE' as an organism and it contains no such substring, "
                "so every enterococcal rule was dead for the one isolate where it "
                "matters most (found by scenario matrix INV-9).",
    },
    "intr_strep_entero_aminoglycoside_mono": {
        "assertion": "Enterococci and streptococci have expected LOW-LEVEL "
                     "aminoglycoside resistance: never valid as monotherapy, and the "
                     "routine low-content disk is not interpretable. Synergy with a "
                     "cell-wall-active agent is real but is predicted only by a "
                     "HIGH-CONTENT HLAR screen (gentamicin 120ug / streptomycin "
                     "300ug). Amikacin and tobramycin have no HLAR screen.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 3 (+ CLSI M100 Ed36 Table 2D)",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Added after the scenario matrix (INV-9) found clinical_data banning "
                "aminoglycosides for these organisms with no matching QC rule in "
                "ast_reportability.py -- a silent half-implemented rule.",
    },
    "intr_enterococcus_sxt_invivo": {
        "assertion": "Enterococci test susceptible to TMP-SMX in vitro but are not "
                     "clinically responsive -- they take up exogenous folate and "
                     "bypass the blocked pathway. Do not report.",
        "source": "CLSI_M100", "locus": "Table 2D comment",
        "verified": "pending",
    },
    "intr_listeria_cephalosporins": {
        "assertion": "L. monocytogenes is expected resistant to all cephalosporins "
                     "and to fosfomycin. Ampicillin +/- gentamicin is the regimen.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 3",
        "verified": "pending",
    },

    # ── Mechanism inference ─────────────────────────────────────────────────
    "mech_esbl_producer_gate": {
        "assertion": "An ESBL classification may only be applied to Enterobacterales. "
                     "Non-fermenters (Pseudomonas, Acinetobacter, Stenotrophomonas) "
                     "must never receive an ESBL label, however their cephalosporin "
                     "results read.",
        "source": "EUCAST_RESIST_DETECT", "locus": "Section 3 (ESBL detection)",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Enforced by is_esbl_producer(); guarded by INVARIANT 2 in "
                "test_intrinsic_invariant.py.",
    },
    "mech_intrinsic_stripped_before_inference": {
        "assertion": "Expected-resistant results must be removed BEFORE any mechanism "
                     "is inferred from the panel, otherwise an expected phenotype is "
                     "mistaken for acquired resistance.",
        "source": "EUCAST_RESIST_DETECT", "locus": "General principles",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "This is why Cephalexin-R on P. aeruginosa used to be labelled "
                "'(ESBL)' instead of '(Expected R)'.",
    },
    "mech_cr_pseudomonas_not_carbapenemase": {
        "assertion": "Carbapenem resistance in P. aeruginosa must NOT be reported as "
                     "a predicted carbapenemase. It is predominantly chromosomal "
                     "(OprD porin loss, MexAB-OprM efflux, derepressed AmpC/PDC), and "
                     "EUCAST publishes NO validated phenotypic algorithm to separate "
                     "carbapenemase-producing from porin/efflux CRPA. Beta-lactams "
                     "still testing S in the same panel argue against a broad "
                     "carbapenemase and must be reported as tested.",
        "source": "EUCAST_RESIST_DETECT",
        "locus": "Carbapenemase detection scope (Enterobacterales only)",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Before this rule, two carbapenems R set probability='carbapenemase' "
                "at 92% confidence for ANY organism, which flipped a SUSCEPTIBLE "
                "Ceftazidime into the Avoid list and pushed the physician toward "
                "colistin. Enterobacterales keep the 92% tier -- it is correct there.",
    },
    "mech_carbapenemase_enterobacterales": {
        "assertion": "In Enterobacterales, non-susceptibility to >=2 carbapenems is a "
                     "strong carbapenemase signal warranting confirmation "
                     "(mCIM / PCR) and infection-control action.",
        "source": "EUCAST_RESIST_DETECT", "locus": "Table 2 algorithm",
        "verified": "pending",
    },
    "mech_oxa48_ertapenem_pattern": {
        "assertion": "Ertapenem R with meropenem S/I suggests OXA-48-like, but the "
                     "same pattern arises from porin loss plus ESBL/AmpC with no "
                     "carbapenemase. High-level temocillin resistance is a marker but "
                     "is not specific. Confirmation required before the label is used.",
        "source": "EUCAST_RESIST_DETECT", "locus": "OXA-48 notes",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "Confidence deliberately held at 62%, not the 92% tier.",
    },
    "mech_mrsa_from_ast_markers": {
        "assertion": "Oxacillin-R or cefoxitin-R in S. aureus means mecA/PBP2a: ALL "
                     "beta-lactams fail regardless of individual S results.",
        "source": "EUCAST_EXPECTED_R", "locus": "Table 3 / mecA note",
        "verified": "pending",
    },
    "mech_dtest_clindamycin": {
        "assertion": "Erythromycin-R with clindamycin-S requires a D-test. Without a "
                     "documented negative D-test, clindamycin must not be reported "
                     "susceptible (inducible MLSb).",
        "source": "CLSI_M100", "locus": "Table 2C, inducible clindamycin resistance",
        "verified": "pending",
    },

    # ── Classification and reporting policy ─────────────────────────────────
    "class_mdr_magiorakos": {
        "assertion": "Non-susceptible = R + I. A category counts as non-susceptible "
                     "when >=1 tested agent in it is non-susceptible. Expected "
                     "resistance is excluded before counting. MDR = non-susceptible "
                     "in >=3 categories.",
        "source": "MAGIORAKOS", "locus": "Interim standard definitions",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
    },
    "report_esbl_ceph_as_tested": {
        "assertion": "When an ESBL is predicted, cephalosporin results are reported AS "
                     "TESTED rather than edited to R. The 'report as tested' policy "
                     "replaced the older blanket S->R editing.",
        "source": "EUCAST_BP", "locus": "v16.1 general notes on reporting",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
        "note": "QC006 implements this. analyze_antibiotics() must not contradict it "
                "by hard-banning the same S-testing cephalosporins -- tracked as an "
                "open issue.",
    },
    "report_intermediate_clsi": {
        "assertion": "I means 'susceptible, increased exposure'. Under CLSI it is "
                     "usable with increased dosing; the report must state which "
                     "standard was applied.",
        "source": "CLSI_M100", "locus": "Interpretive categories",
        "verified": "pending",
    },
    "report_aware_tiers": {
        "assertion": "Access / Watch / Reserve tiers drive the ranking engine, and "
                     "Reserve agents are labelled last-resort (MDR/XDR), not "
                     "'ESBL / severe cases only'.",
        "source": "WHO_AWARE", "locus": "AWaRe 2023 classification",
        "verified": "pending",
    },
    "report_no_breakpoint_is_not_resistant": {
        "assertion": "An agent with no breakpoint for the organism yields a "
                     "meaningless result, not a resistant one. Flag as warning and "
                     "suppress, do not convert to R.",
        "source": "EUCAST_BP", "locus": "'When there are no breakpoints' guidance",
        "verified": "pending",
    },

    # ── Therapy notes ───────────────────────────────────────────────────────
    "tx_cefepime_esbl_uti": {
        "assertion": "Cefepime testing S with a predicted ESBL goes to Use With "
                     "Caution (not banned) for uncomplicated lower UTI; it is banned "
                     "when a carbapenemase is predicted or when cefepime is R.",
        "source": "IDSA_AMR", "locus": "ESBL-E section",
        "verified": "pending",
    },
    "tx_stenotrophomonas_sxt": {
        "assertion": "TMP-SMX is the established first-line agent for "
                     "S. maltophilia; carbapenems are inactive (L1 MBL).",
        "source": "IDSA_AMR", "locus": "S. maltophilia section",
        "verified": "pending",
    },
    "tx_acinetobacter_sulbactam": {
        "assertion": "Sulbactam-containing regimens are the backbone for "
                     "Acinetobacter; sulbactam has direct PBP-binding activity "
                     "against this genus, unlike clavulanate.",
        "source": "IDSA_AMR", "locus": "CRAB section",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
    },
    "tx_urinary_only_agents": {
        "assertion": "Nitrofurantoin and fosfomycin achieve therapeutic levels only "
                     "in urine and must never be recommended for blood, CSF, sputum "
                     "or wound isolates.",
        "source": "EUCAST_BP", "locus": "v16.1 agent-specific notes",
        "verified": "primary", "verified_by": _HA, "verified_on": "2026-07-22",
    },
    "tx_fusidic_no_monotherapy": {
        "assertion": "Fusidic acid must not be used as systemic monotherapy "
                     "(rapid on-treatment resistance selection).",
        "source": "EUCAST_BP", "locus": "v16.1 agent-specific notes",
        "verified": "pending",
    },
    "tx_priority_pathogens": {
        "assertion": "Carbapenem-resistant Acinetobacter and Enterobacterales are "
                     "WHO critical-priority pathogens; escalation wording reflects it.",
        "source": "WHO_BPPL", "locus": "2024 priority tiers",
        "verified": "pending",
    },
}


# ============================================================================
#  Helpers
# ============================================================================
def _months_between(then: date, now: date) -> int:
    return (now.year - then.year) * 12 + (now.month - then.month)


def _parse_day(s: str) -> date:
    parts = [int(x) for x in s.split("-")]
    while len(parts) < 3:
        parts.append(1)
    return date(*parts[:3])


def pending_rules() -> Dict[str, Dict[str, Any]]:
    """Rules that have never been checked against the source document."""
    return {k: v for k, v in RULES.items() if v.get("verified") != "primary"}


def stale_rules(today: date | None = None) -> Dict[str, int]:
    """Primary-verified rules whose verification is older than STALENESS_MONTHS."""
    today = today or date.today()
    out: Dict[str, int] = {}
    for k, v in RULES.items():
        if v.get("verified") == "primary" and v.get("verified_on"):
            age = _months_between(_parse_day(v["verified_on"]), today)
            if age > STALENESS_MONTHS:
                out[k] = age
    return out


def superseded_citations() -> Dict[str, str]:
    """Rules still pointing at a document this registry marks as superseded."""
    return {
        rid: r["source"]
        for rid, r in RULES.items()
        if SOURCES.get(r.get("source"), {}).get("superseded_by")
    }


def print_queue() -> None:
    pend = pending_rules()
    print(f"\nGUIDELINE VERIFICATION QUEUE — {len(pend)} rule(s) awaiting primary check\n")
    by_src: Dict[str, list] = {}
    for rid, r in pend.items():
        by_src.setdefault(r["source"], []).append((rid, r))
    for src, rows in sorted(by_src.items()):
        meta = SOURCES.get(src, {})
        print(f"── {meta.get('title', src)}  v{meta.get('version', '?')} "
              f"({meta.get('published', '?')})")
        print(f"   {meta.get('url', '')}")
        for rid, r in rows:
            print(f"     [ ] {rid}")
            print(f"         locus: {r.get('locus', '-')}")
        print()
    print("To verify: open the document at the locus, confirm the assertion, then set")
    print('  "verified": "primary", "verified_by": "<name>", "verified_on": "YYYY-MM-DD"')


def summary() -> None:
    prim = len(RULES) - len(pending_rules())
    print("Orange Lab CDSS — Guideline Registry")
    print("=" * 46)
    print(f"  sources                : {len(SOURCES)}")
    print(f"  rules                  : {len(RULES)}")
    print(f"  primary-verified       : {prim}")
    print(f"  awaiting verification  : {len(pending_rules())}")
    print(f"  stale (> {STALENESS_MONTHS} months) : {len(stale_rules())}")
    sup = superseded_citations()
    print(f"  citing superseded docs : {len(sup)}"
          + (f"  -> {sorted(sup)}" if sup else ""))
    print("\n  Current document versions:")
    for key in ("EUCAST_BP", "CLSI_M100", "EUCAST_EXPECTED_R"):
        m = SOURCES[key]
        print(f"    {m['title'][:52]:52s} v{m['version']} ({m['published']})")
    print("\nRun with --queue for the outstanding verification list.")


if __name__ == "__main__":
    import sys
    if "--queue" in sys.argv:
        print_queue()
    else:
        summary()
