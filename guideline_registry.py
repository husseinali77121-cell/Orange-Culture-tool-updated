"""Orange Lab CDSS — guideline citation registry.

WHAT THIS FILE IS FOR
---------------------
A test suite can prove the code matches its rule tables. It cannot prove the
rule tables match EUCAST v16. Only a human reading the source document can do
that. This registry is where that human judgement is recorded so it is
auditable, attributable and expirable instead of living in someone's memory.

Every clinical rule in the engine gets one row: which document it comes from,
which edition, which table, who checked it against the actual PDF, and when.

VERIFICATION LEVELS
-------------------
  "source"    — the assertion was checked against the text of the source document
                itself (the EUCAST PDF, the guideline paper).
  "secondary" — checked against an authoritative published account of the source
                (a guideline summary, a national body's clarification, the
                journal article that carries the table) but not the primary PDF.
  "pending"   — inherited from earlier code. Probably right, but unverified.
                NOT a failure — this is the review queue.

ATTRIBUTION, HONESTLY
---------------------
`checked_by` records who or what performed the check. Where it reads
"AI-assisted review", the verification was done by a language model reading
published sources during a code review session — NOT by a clinician reading the
standard. That is genuinely useful and genuinely not the same thing.

`countersigned_by` is for the human who takes clinical responsibility. It is
empty on every row right now. test_guidelines.py reports the count and does not
fail, because an unsigned row is honest and a falsely signed one is not. Fill it
in as you review; do not fill it in for rows you have not read.

test_guidelines.py fails when a rule has no row at all, when a row points at an
undefined source, or when a "primary" row has gone stale. It reports the
"pending" count so the queue stays visible instead of quietly growing.

WHY THE SOURCE STRINGS ARE CENTRALISED HERE
-------------------------------------------
Free-text citations drift. An audit of this codebase found "EUCAST 2026" (21
occurrences — which document? breakpoints? expert rules?), "CLSI M100 2026"
alongside "CLSI M100 Ed36" for the same standard, and "IDSA AMR 2025" for a
document published in August 2024. Meanwhile "WHO AWaRe 2025" looked wrong from
memory and turned out to be correct — WHO published the 2025 edition on
2025-09-05. Memory is not a citation. A dated URL is.
"""
from __future__ import annotations

from typing import Any, Dict

# A "primary" verification older than this is treated as stale and must be
# re-checked. Eighteen months is one EUCAST breakpoint cycle plus a margin.
STALE_AFTER_MONTHS = 18

# ── Source documents ─────────────────────────────────────────────────────────
SOURCES: Dict[str, Dict[str, str]] = {
    "EUCAST_INTRINSIC": {
        "title": "EUCAST Intrinsic Resistance and Unusual Phenotypes",
        "version": "v3.3",
        "dated": "2021-10-18",
        "url": "https://www.eucast.org/expert_rules_and_expected_phenotypes",
    },
    "EUCAST_EXPERT": {
        "title": "EUCAST Expert Rules in Antimicrobial Susceptibility Testing "
                 "(Leclercq et al., Clin Microbiol Infect 2013;19:141-160)",
        "version": "v3.1 (2016) tables; v2 paper CMI 2013",
        "dated": "2016-10-29",
        "url": "https://www.clinicalmicrobiologyandinfection.org/article/S1198-743X(14)60249-4/fulltext",
    },
    "EUCAST_BP": {
        "title": "EUCAST Clinical Breakpoint Tables",
        "version": "v16.1",
        "dated": "2026",   # v16.0 valid from 2026-01-01; v16.1 adds anaerobe species
        "note": "Re-validate agent tables against v16.1 before the next release.",
        "url": "https://www.eucast.org/clinical_breakpoints",
    },
    "EUCAST_DETECT": {
        "title": "EUCAST guidelines for detection of resistance mechanisms and "
                 "specific resistances of clinical and/or epidemiological importance",
        "version": "v2.0",
        "dated": "2017-07-11",
        "url": "https://www.eucast.org/fileadmin/src/media/PDFs/EUCAST_files/"
               "Resistance_mechanisms/EUCAST_detection_of_resistance_mechanisms_170711.pdf",
    },
    "CLSI_M100": {
        "title": "CLSI M100 — Performance Standards for Antimicrobial Susceptibility Testing",
        "version": "Ed36",
        "dated": "2026",
        "url": "https://clsi.org/standards/products/microbiology/documents/m100/",
    },
    "IDSA_AMR": {
        "title": "IDSA Guidance on the Treatment of Antimicrobial-Resistant "
                 "Gram-Negative Infections (Tamma et al., Clin Infect Dis)",
        "version": "v4.0 — ciae403",
        "dated": "2024-08-07",
        "url": "https://www.idsociety.org/practice-guideline/amr-guidance/",
    },
    "WHO_AWARE": {
        "title": "WHO AWaRe (Access, Watch, Reserve) classification of antibiotics "
                 "for evaluation and monitoring of use",
        "version": "2025 edition",
        "dated": "2025-09-05",
        "url": "https://www.who.int/publications/i/item/B09489",
    },
    "MAGIORAKOS": {
        "title": "Magiorakos et al. — Multidrug-resistant, extensively drug-resistant "
                 "and pandrug-resistant bacteria: an international expert proposal "
                 "(Clin Microbiol Infect 2012;18:268-281)",
        "version": "final",
        "dated": "2012-03",
        "url": "https://www.clinicalmicrobiologyandinfection.org/article/S1198-743X(14)61632-3/fulltext",
    },
    "CDC_EIP_CRPA": {
        "title": "Carbapenem-Resistant Pseudomonas aeruginosa at US Emerging "
                 "Infections Program Sites, 2015 (Emerg Infect Dis 2019;25:1281)",
        "version": "final",
        "dated": "2019-07",
        "url": "https://wwwnc.cdc.gov/eid/article/25/7/18-1200_article",
    },
}

# ── Rule rows ────────────────────────────────────────────────────────────────
# key = the rule id used in the engine. Keep these in sync; test_guidelines.py
# fails the build if an engine rule has no row here.
_AI = "AI-assisted review (Claude, code-review session 2026-07-23)"

RULES: Dict[str, Dict[str, Any]] = {

    # ── Intrinsic resistance (ast_reportability.INTRINSIC_RULES) ─────────────
    "intr_entero_gram_pos_agents": {
        "assertion": "Enterobacterales are intrinsically resistant to macrolides, "
                     "lincosamides, glycopeptides, oxazolidinones, daptomycin, "
                     "fusidic acid, rifampicin and the anti-staphylococcal penicillins.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST Expert Rules names Enterobacterales resistant to glycopeptides and linezolid as a worked example.',
    },
    "intr_klebsiella_ampicillin": {
        "assertion": "Klebsiella spp. carry chromosomal SHV-1 -> intrinsic "
                     "aminopenicillin resistance; inhibitor combinations are NOT intrinsic.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'Chromosomal class-A beta-lactamase; inhibitor combinations remain reportable. Same mechanism class as C. koseri/K. oxytoca.',
    },
    "intr_proteus_mirabilis": {
        "assertion": "P. mirabilis is intrinsically resistant to tetracyclines, "
                     "colistin/polymyxin and nitrofurantoin.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST Expert Rules paper names P. mirabilis resistant to nitrofurantoin and colistin as a worked example of intrinsic resistance.',
    },
    "intr_morganella_providencia_proteus_vulgaris": {
        "assertion": "Morganella, Providencia, P. vulgaris/penneri: chromosomal AmpC "
                     "plus tribe traits -> aminopenicillins (inhibitor combinations "
                     "included), 1st/2nd-gen cephalosporins, cephamycins, "
                     "tetracyclines, colistin, nitrofurantoin.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST v3.2 changelog moved Providencia cefuroxime/tigecycline out of the intrinsic table into the expert rules — verify the current placement when the v16 tables are read.',
    },
    "intr_serratia": {
        "assertion": "Serratia marcescens: chromosomal AmpC -> aminopenicillins, "
                     "1st/2nd-gen cephalosporins, cephamycins; plus colistin and "
                     "nitrofurantoin.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST v3.3 Table 2 fn.5: intrinsically R to tetracycline and doxycycline but NOT minocycline or tigecycline. The code had both halves wrong — tigecycline was banned, tetracycline/doxycycline were missing. Corrected.',
    },
    "intr_enterobacter_citrobacter_ampc": {
        "assertion": "Inducible chromosomal AmpC (Enterobacter, K. aerogenes, "
                     "C. freundii, Hafnia) -> aminopenicillins, amoxicillin-clavulanate, "
                     "ampicillin-sulbactam, 1st/2nd-gen cephalosporins and cephamycins. "
                     "Sulbactam does not inhibit AmpC, so amp-sulbactam is NOT exempt.",
        "source": "IDSA_AMR", "locus": "AmpC-E section",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "IDSA v4.0 states basal AmpC production confers intrinsic resistance "
                "to ampicillin, amoxicillin-clavulanate, ampicillin-sulbactam and "
                "1st/2nd-generation cephalosporins.",
    },
    "intr_pseudomonas": {
        "assertion": "P. aeruginosa is intrinsically resistant to aminopenicillins, "
                     "1st/2nd/non-antipseudomonal 3rd-gen cephalosporins, ertapenem, "
                     "tetracyclines, trimethoprim, chloramphenicol, nitrofurantoin. "
                     "Ceftazidime and cefepime remain active.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 3",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST v3.3 Table 3 header: non-fermenters are intrinsically resistant to benzylpenicillin, 1st/2nd-gen cephalosporins, glycopeptides, lipoglycopeptides, fusidic acid, macrolides, lincosamides, streptogramins, rifampicin and oxazolidinones.',
    },
    "intr_acinetobacter": {
        "assertion": "Acinetobacter spp. are intrinsically resistant to ampicillin, "
                     "amoxicillin, AMOXICILLIN-CLAVULANATE, aztreonam, ertapenem, "
                     "trimethoprim, chloramphenicol and fosfomycin. "
                     "Ampicillin-SULBACTAM is the exception — sulbactam has intrinsic "
                     "anti-Acinetobacter activity of its own. ALSO (Table 2 fn.2): "
                     "intrinsically resistant to TETRACYCLINE and DOXYCYCLINE but "
                     "NOT to minocycline and tigecycline.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 3",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Two separate defects fixed here. (1) The code EXCLUDED 'clav', "
                "exempting amox-clav from a restriction EUCAST applies to it -- "
                "clavulanate has no useful activity against Acinetobacter, "
                "sulbactam does. (2) Doxycycline was ABSENT from the table and was "
                "being offered as an active option, contradicting fn.2 verbatim: "
                "'Acinetobacter is intrinsically resistant to tetracycline and "
                "doxycycline but not to minocycline and tigecycline.' Minocycline "
                "was not in the formulary at all and has been added, since it is "
                "the tetracycline that actually works here.",
    },
    "intr_stenotrophomonas": {
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "assertion": "S. maltophilia: L1 metallo-beta-lactamase -> all carbapenems, "
                     "plus intrinsic aminoglycoside and most beta-lactam resistance. "
                     "TMP-SMX is the established agent. Table 2 fn.7 is NARROWER "
                     "than fn.2/fn.5: intrinsically resistant to TETRACYCLINE only "
                     "-- doxycycline, minocycline and tigecycline stay active.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 3",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST Expert Rules names S. maltophilia resistant to carbapenems as a worked example of intrinsic resistance.',
    },
    "intr_mrsa_betalactams": {
        "assertion": "MRSA carries mecA/mecC encoding low-affinity PBP2a, so ALL "
                     "conventional beta-lactams are inactive; only ceftaroline and "
                     "ceftobiprole retain activity.",
        "source": "EUCAST_EXPERT", "locus": "staphylococci; CLSI M100 Ed36 Table 2C",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Added after an audit found the UI label 'MRSA' shared no substring "
                "with the table key 'staphylococcus aureus', so MRSA received NO "
                "intrinsic filtering at all -- aztreonam and colistin were offered "
                "for it while S. aureus correctly refused them.",
    },
    "intr_mycoplasma_cellwall_agents": {
        "assertion": "Mycoplasma and Ureaplasma have no peptidoglycan cell wall, so "
                     "beta-lactams, glycopeptides and fosfomycin are intrinsically "
                     "inactive.",
        "source": "EUCAST_INTRINSIC", "locus": "organisms without a cell wall",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Textbook microbiology; the table had no Mycoplasma key so the "
                "engine could have recommended ampicillin for atypical pneumonia.",
    },
    "intr_staph_gram_neg_agents": {
        "assertion": "Staphylococci are intrinsically resistant to aztreonam, "
                     "colistin/polymyxin, nalidixic acid and temocillin.",
        "source": "EUCAST_EXPERT", "locus": "Table 4",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Table 4 header states Gram-positive bacteria are additionally "
                "intrinsically resistant to aztreonam, temocillin, polymyxin "
                "B/colistin and nalidixic acid.",
    },
    "intr_enterococcus_cephalosporins": {
        "assertion": "Enterococci are intrinsically resistant to ALL cephalosporins, "
                     "clindamycin, fusidic acid and aztreonam.",
        "source": "EUCAST_EXPERT", "locus": "Table 4",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "CLSI M100 Enterococcus WARNING verbatim: 'For Enterococcus spp., aminoglycosides (except for high-level resistance testing), cephalosporins, clindamycin, and trimethoprim-sulfamethoxazole may appear active in vitro, but are not effective clinically and should not be reported as susceptible.' EUCAST v3.3 Table 4 rows 4.7-4.9 carry R in the cephalosporin and clindamycin columns; aztreonam comes from the Table 4 header for all Gram-positives.",
    },
    "intr_strep_enterococcus_aminoglycosides": {
        "assertion": "Enterococci and streptococci have intrinsic LOW-LEVEL "
                     "aminoglycoside resistance: never valid as monotherapy, and the "
                     "routine 10 ug disk is not interpretable. Synergy with a "
                     "cell-wall-active agent is real but is predicted only by a "
                     "HIGH-CONTENT HLAR screen (gentamicin 120 ug / streptomycin "
                     "300 ug). Amikacin and tobramycin have no HLAR screen.",
        "source": "EUCAST_EXPERT", "locus": "Table 4 (+ CLSI M100 Ed36 Table 2D)",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Added after the scenario matrix (INV-9) found clinical_data banning "
                "aminoglycosides for these organisms with no matching QC rule. "
                "EUCAST Table 4 footnote: aminoglycoside + cell-wall-inhibitor "
                "combinations are synergistic and bactericidal against isolates "
                "susceptible to the cell-wall agent and without high-level "
                "aminoglycoside resistance.",
    },
    "intr_enterococcus_sxt_invivo": {
        "assertion": "Enterococci test susceptible to TMP-SMX in vitro but are not "
                     "clinically responsive — they take up exogenous folate and "
                     "bypass the blocked pathway. Do not report.",
        "source": "EUCAST_EXPERT", "locus": "Table 4 / CLSI M100 Appendix B",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Same CLSI Enterococcus WARNING names trimethoprim-sulfamethoxazole explicitly and says do not report as susceptible. Confirms both the phenomenon and the 'do not report' instruction.",
    },
    "intr_listeria_cephalosporins": {
        "assertion": "L. monocytogenes is intrinsically resistant to all "
                     "cephalosporins — a known cause of meningitis treatment failure. "
                     "Ampicillin is the agent.",
        "source": "EUCAST_EXPERT", "locus": "Table 4",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "CAVEAT: the clinical fact is not in doubt -- cephalosporins fail against Listeria and this drives the 'add ampicillin' rule in empiric meningitis therapy. However EUCAST v3.3 Table 4 row 4.11 shows only two R marks for L. monocytogenes and the column alignment could NOT be resolved from the flattened PDF text, so the exact cell mapping is unconfirmed. Verify against the PDF before countersigning.",
    },

    "intr_nonfermenter_narrow_spectrum": {
        "assertion": "Non-fermentative Gram-negatives (Pseudomonas, Acinetobacter, "
                     "Stenotrophomonas, Burkholderia) are intrinsically resistant to "
                     "benzylpenicillin, 1st/2nd-generation cephalosporins, "
                     "glycopeptides, lipoglycopeptides, fusidic acid, macrolides, "
                     "lincosamides, rifampicin and oxazolidinones.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 3 (header)",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Promoted from a 'no breakpoints' rule: EUCAST states these are "
                "intrinsically resistant, which is a stronger and more useful claim.",
    },
    "intr_citrobacter_koseri_klebsiella_oxytoca_classA": {
        "assertion": "C. koseri and K. oxytoca carry a chromosomal CLASS A "
                     "beta-lactamase — intrinsic aminopenicillin resistance, but "
                     "inhibitor combinations remain active (unlike the AmpC species).",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "Added after the expanded scenario matrix found C. koseri matched no "
                "rule at all — the only Citrobacter rule targeted C. freundii's AmpC.",
    },

    # ── No breakpoints (ast_reportability.NO_BREAKPOINT_RULES) ───────────────
    "nobp_nonfermenter_narrow_spectrum": {
        "assertion": "Neither EUCAST nor CLSI publishes breakpoints for narrow-spectrum "
                     "cephalosporins, nitrofurantoin or norfloxacin against "
                     "Acinetobacter / Stenotrophomonas / Burkholderia.",
        "source": "EUCAST_BP", "locus": "non-fermenter tables; CLSI M100 Table 2B-2/2B-3",
        "verified": "pending",
    },
    "nobp_azithromycin_enterobacterales": {
        "assertion": "Azithromycin breakpoints exist only for Salmonella Typhi/Paratyphi "
                     "and Shigella. Non-typhoidal Salmonella has none.",
        "source": "EUCAST_BP", "locus": "Enterobacterales — azithromycin note",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "CLSI M100 azithromycin footnote p verbatim: 'For reporting against Salmonella enterica ser. Typhi and Shigella spp. only.' Confirms non-typhoidal Salmonella has no azithromycin reporting criterion.",
    },
    "nobp_cefoperazone": {
        "assertion": "Cefoperazone alone or with sulbactam has no EUCAST breakpoints; "
                     "CLSI withdrew the cefoperazone breakpoints. Widely used in Egypt, "
                     "but the result is uncalibrated.",
        "source": "EUCAST_BP", "locus": "absent from tables; CLSI M100 Ed36",
        "verified": "pending",
    },
    "nobp_nitrofurantoin_non_ecoli": {
        "assertion": "EUCAST nitrofurantoin breakpoints are for E. coli only "
                     "(uncomplicated UTI) and do not extrapolate to other species.",
        "source": "EUCAST_BP", "locus": "Enterobacterales",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'BSAC clarification of EUCAST guidance: after review the nitrofurantoin breakpoints could NOT be extended beyond E. coli; Proteeae, some Klebsiella and Pseudomonas carry intrinsic resistance.',
    },
    "nobp_fosfomycin_oral_non_ecoli": {
        "assertion": "Oral fosfomycin breakpoints are restricted to E. coli in both "
                     "EUCAST and CLSI.",
        "source": "EUCAST_BP", "locus": "Enterobacterales",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "EUCAST guidance on fosfomycin i.v. breakpoints (May 2024) verbatim: 'The currently revised breakpoint of fosfomycin applies only to E. coli in infections originating from the urinary tract.' Breakpoint tables add: 'Zone diameter breakpoints apply to E. coli only.'",
    },
    "nobp_imipenem_proteae": {
        "assertion": "Imipenem has intrinsically LOW activity against Proteus spp., "
                     "Morganella morganii and Providencia spp.; do not rely on a "
                     "Susceptible imipenem result -- meropenem is preferred.",
        "source": "EUCAST_BP", "locus": "Enterobacterales note 2",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "NEW RULE added this round; the engine had no equivalent.",
    },
    "nobp_tigecycline_proteae": {
        "assertion": "Tigecycline has no breakpoint for the Proteae "
                     "(Proteus / Providencia / Morganella), which are intrinsically "
                     "less susceptible via efflux.",
        "source": "EUCAST_BP", "locus": "Enterobacterales — tigecycline note",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'EUCAST v16.0 Enterobacterales note 3/A verbatim: activity is INSUFFICIENT in Serratia spp., Proteus spp., Morganella morganii and Providencia spp. SERRATIA was missing from the rule and has been added. Breakpoint is validated for E. coli and C. koseri only.',
    },

    # ── Ineffective in vivo ──────────────────────────────────────────────────
    "invivo_salmonella_shigella_aminoglycoside_ceph12": {
        "assertion": "Aminoglycosides and 1st/2nd-gen cephalosporins may test "
                     "susceptible against Salmonella/Shigella but are clinically "
                     "ineffective for invasive infection — do not report S.",
        "source": "CLSI_M100", "locus": "Table 2A organism-specific notes",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "CLSI M100 WARNING verbatim: 'For Salmonella and Shigella spp., aminoglycosides, first- and second-generation cephalosporins, and cephamycins may appear active in vitro but are not effective clinically and should not be reported as susceptible.' Carried into Ed36 (2026).",
    },

    # ── Internal consistency (ast_consistency) ───────────────────────────────
    "equiv_ctx_cro": {
        "assertion": "Cefotaxime and ceftriaxone share MIC breakpoints against "
                     "Enterobacterales and are hydrolysed near-identically by common "
                     "ESBLs; one S and one R on the same isolate is a laboratory error.",
        "source": "EUCAST_BP", "locus": "Enterobacterales; CLSI M100 Table 2A",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'Cefotaxime and ceftriaxone share Enterobacterales breakpoints in both EUCAST and CLSI. Treated as a VERIFY flag rather than a hard error, since rare enzyme-specific discordance exists.',
    },
    "equiv_amc_sam": {
        "assertion": "Amoxicillin-clavulanate and ampicillin-sulbactam behave "
                     "near-identically against Enterobacterales; a split result is a "
                     "laboratory error, not a resistance pattern.",
        "source": "EUCAST_EXPERT", "locus": "beta-lactam interpretive rules",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'DOWNGRADED to a verify-flag this round. Sulbactam and clavulanate differ in potency and carry different breakpoints and dosing, so a split result is unusual rather than impossible.',
    },
    "hier_amp_vs_amc": {
        "assertion": "Ampicillin S with amoxicillin-clavulanate R is impossible — "
                     "adding a beta-lactamase inhibitor cannot reduce activity.",
        "source": "EUCAST_EXPERT", "locus": "beta-lactam hierarchy",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'Adding a beta-lactamase inhibitor cannot reduce activity, so the pattern indicates a testing error. Kept as a verify-flag.',
    },
    "hier_pip_vs_tzp": {
        "assertion": "Piperacillin S with piperacillin-tazobactam R is impossible, "
                     "for the same reason.",
        "source": "EUCAST_EXPERT", "locus": "beta-lactam hierarchy",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'Same logic as hier_amp_vs_amc. Rare tazobactam inoculum effects are described, so verify rather than declare impossible.',
    },
    "hier_mem_vs_etp": {
        "assertion": "Meropenem R with ertapenem S is the wrong way round; ertapenem "
                     "is the most labile carbapenem, so the usual pattern is the "
                     "reverse (ertapenem-R with meropenem-S = OXA-48 or porin loss).",
        "source": "EUCAST_EXPERT", "locus": "carbapenem interpretive rules",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": 'Ertapenem is the most labile carbapenem; the ertapenem-R/meropenem-S direction is the recognised OXA-48 or porin-loss signature. The reverse warrants a repeat.',
    },
    "hier_tet_vs_doxy": {
        "assertion": "Tetracycline S predicts doxycycline/minocycline S; the reverse "
                     "combination is a reading error.",
        "source": "EUCAST_EXPERT", "locus": "tetracycline interpretive rules",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "CLSI M100 footnote q VERBATIM: 'Organisms that are susceptible to tetracycline are also considered susceptible to doxycycline and minocycline. However, some organisms that are intermediate or resistant to tetracycline may be susceptible to doxycycline, minocycline, or both.' The code already flags ONLY the safe direction (tet-S + doxy-R) and states the reverse is allowed, so it matches the footnote exactly and does NOT suppress an active minocycline.",
    },

    # ── Inline rules in streamlit_app.py ─────────────────────────────────────
    "QC003": {
        "assertion": "A carbapenem susceptible while colistin is resistant amid broad "
                     "resistance is an atypical pattern; confirm the identification.",
        "source": "EUCAST_EXPERT", "locus": "unusual phenotypes",
        "verified": "pending",
    },
    "QC004": {
        "assertion": "Carbapenem R with a cephalosporin S in Enterobacterales is "
                     "uncommon (OXA-48-like or porin loss) and should be confirmed by "
                     "a carbapenemase assay.",
        "source": "EUCAST_DETECT", "locus": "carbapenemase detection",
        "verified": "pending",
    },
    "QC005": {
        "assertion": "Linezolid resistance in S. aureus is very rare; confirm by a "
                     "reference method before reporting.",
        "source": "CLSI_M100", "locus": "Table 2C notes",
        "verified": "pending",
    },
    "QC006": {
        "assertion": "A susceptible cephalosporin in a suspected ESBL producer is "
                     "reported AS TESTED. Current breakpoints already detect the "
                     "clinically important mechanisms; editing S to R on mechanism "
                     "detection is the pre-2017 practice and was withdrawn. ESBL "
                     "detection is for infection control and surveillance. Preferring "
                     "a carbapenem in serious ESBL infection is a prescribing decision, "
                     "not a reporting edit.",
        "source": "EUCAST_BP", "locus": "Enterobacterales — cephalosporin/ESBL note",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
    },
    "SPEC-URN": {
        "assertion": "Nitrofurantoin, oral fosfomycin and norfloxacin reach "
                     "therapeutic concentrations only in urine (and, for norfloxacin, "
                     "the GI tract); a result on a systemic isolate is not clinically "
                     "actionable.",
        "source": "EUCAST_BP", "locus": "agent site-of-infection notes",
        "verified": "secondary", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "EUCAST breakpoint tables label these agents '(uncomplicated UTI only)' in the Enterobacterales table headers (nitrofurantoin, trimethoprim, oral fosfomycin), which carries the site restriction. The pharmacology claim itself is textbook but was not read from a primary PK document.",
    },
    "REP-GPO-GN": {
        "assertion": "Glycopeptides, oxazolidinones and daptomycin have no activity "
                     "and no breakpoint against Gram-negative bacteria and must never "
                     "be tested or reported for them.",
        "source": "EUCAST_INTRINSIC", "locus": "Table 2/3",
        "verified": "source", "checked_by": _AI, "checked_on": "2026-07-22",
        "countersigned_by": "",
        "note": "EUCAST Table 1 header verbatim: 'Enterobacterales are also intrinsically resistant to benzylpenicillin, glycopeptides, fusidic acid, macrolides, lincosamides, streptogramins, rifampicin, daptomycin and linezolid.' Table 3 header carries the same for non-fermenters.",
    },
}

# ── Citation strings the engine must NOT use in free text ────────────────────
# Each maps an ambiguous or incorrect string to the row that replaces it. The
# test greps the codebase for these and reports every remaining occurrence.
DEPRECATED_CITATIONS: Dict[str, str] = {
    "IDSA AMR 2025":
        "IDSA_AMR is v4.0, published in Clin Infect Dis on 2024-08-07 (ciae403). "
        "There is no 2025 edition — use 'IDSA AMR Guidance v4.0 (2024)'.",
    "IDSA 2025":
        "Ambiguous. Name the specific IDSA document and its year.",
    "EUCAST 2026":
        "Ambiguous — EUCAST publishes several documents. Use 'EUCAST Breakpoint "
        "Tables v16.0 (2026)' or 'EUCAST Intrinsic Resistance v3.3 (2021)'.",
    "CLSI M100 2026":
        "Use the edition, not the year: 'CLSI M100 Ed36'.",
    "EUCAST Expert Rules v3.3":
        "v3.3 is the Intrinsic Resistance and Unusual Phenotypes document, not the "
        "Expert Rules. Use 'EUCAST Intrinsic Resistance v3.3' for intrinsic claims "
        "and 'EUCAST Expert Rules v3.1 (2016)' for interpretive/hierarchy rules.",
}


def source_for(rule_id: str) -> Dict[str, str]:
    """Full citation for a rule id, or {} if the rule is unregistered."""
    row = RULES.get(rule_id)
    if not row:
        return {}
    src = SOURCES.get(row.get("source", ""), {})
    return {**src, "locus": row.get("locus", ""), "assertion": row.get("assertion", "")}


def citation_line(rule_id: str) -> str:
    """One-line human citation, e.g. for a PDF footer."""
    s = source_for(rule_id)
    if not s:
        return ""
    bits = [s.get("title", ""), s.get("version", ""), s.get("locus", "")]
    return " · ".join(b for b in bits if b)
