"""Orange Lab — AST reportability rules.

Answers one question the AST-QA engine could not previously ask:

    "Should this antibiotic have been on this organism's panel at all?"

Two ways the answer is no, and they are clinically different:

  1. INTRINSIC RESISTANCE — the species is resistant by nature, not by anything
     it acquired. A zone can still be measured, and it can still read S. That S
     is a laboratory error, and acting on it is a treatment failure with a
     susceptible-looking report to justify it.

  2. NO BREAKPOINTS — no interpretive criteria exist for this agent against this
     organism. There is nothing to compare the zone against, so the resulting
     S/I/R is not a weak result: it is not a result. It looks identical on the
     report to a validated one.

Why this is its own module: it is reference data plus one pure function over it.
It reads no session, imports nothing from the app, and every rule carries the
document it comes from — which is exactly what a reviewing microbiologist needs
in order to argue with it. Rules are meant to be argued with; that is why the
`reference` field is mandatory rather than a nicety.

Scope note: the intrinsic-resistance tables below cover the organisms and agents
a general clinical lab actually panels. They are NOT a complete transcription of
EUCAST Expert Rules — where a species is absent here, this module stays silent
rather than guessing, because a false "this drug is invalid" alert costs
credibility that a QA engine cannot afford to spend.

Primary sources (verify against the current editions before clinical use):
  * EUCAST Intrinsic Resistance and Unusual Phenotypes, v3.3 (2021-10-18)
  * EUCAST Clinical Breakpoint Tables v16.0, valid from 2026-01-01 — Notes
  * CLSI M100, Ed36 (2026) — Appendix B; Tables 2A-2J organism-specific notes
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Organism families ────────────────────────────────────────────────────────
# Substring-matched against the reported organism name, lowercased.
ENTEROBACTERALES = [
    "escherichia", "e. coli", "e.coli", "klebsiella", "enterobacter",
    "citrobacter", "serratia", "proteus", "morganella", "providencia",
    "salmonella", "shigella", "hafnia", "pantoea", "raoultella", "yersinia",
    "cronobacter", "edwardsiella", "kluyvera", "leclercia",
]

_NORM = re.compile(r"[^a-z0-9]")


def _nk(s: str) -> str:
    """Normalize a drug name for matching: lowercase, alphanumerics only."""
    return _NORM.sub("", (s or "").lower())


def _org_matches(organism: str, names: List[str]) -> bool:
    o = (organism or "").lower()
    return any(n in o for n in names)


def _drug_matches(drug: str, needles: List[str], excludes: List[str]) -> bool:
    d = _nk(drug)
    if not d:
        return False
    if any(_nk(x) in d for x in excludes):
        return False
    return any(_nk(n) in d for n in needles)


# ── 1. INTRINSIC RESISTANCE ──────────────────────────────────────────────────
# `exclude` exists because a beta-lactamase inhibitor changes the answer:
# Klebsiella is intrinsically resistant to ampicillin, NOT to
# amoxicillin-clavulanate. A naive substring match on "amoxicillin" would
# condemn amox-clav and be wrong in the direction that removes a working drug.
INTRINSIC_RULES: List[Dict[str, Any]] = [
    {
        "id": "intr_entero_gram_pos_agents",
        "organisms": ENTEROBACTERALES,
        "drugs": ["erythromycin", "clarithromycin", "clindamycin", "lincomycin",
                  "vancomycin", "teicoplanin", "linezolid", "daptomycin",
                  "fusidic acid", "rifampicin", "rifampin",
                  "quinupristin", "benzylpenicillin", "penicillin g",
                  "oxacillin", "cloxacillin", "methicillin"],
        "exclude": [],
        "reason_ar": ("الـ Enterobacterales مقاومة بطبيعتها لهذه المجموعات "
                      "(ماكروليدات · لينكوزاميدات · جلايكوببتيدات · "
                      "أوكسازوليدينونات · daptomycin · fusidic acid · rifampicin) — "
                      "الغشاء الخارجي يمنع نفاذ الدواء."),
        "reason_en": ("Enterobacterales are intrinsically resistant to these classes "
                      "(macrolides, lincosamides, glycopeptides, oxazolidinones, "
                      "daptomycin, fusidic acid, rifampicin) — the outer membrane "
                      "excludes them."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2 · CLSI M100 App. B",
    },
    {
        # Found by the expanded scenario matrix (INV-9): clinical_data lists
        # ampicillin/amoxicillin/ticarcillin as intrinsic for C. koseri, but the
        # only Citrobacter rule here was the AmpC one, which matches
        # "citrobacter freundii" — so C. koseri had no rule at all.
        #
        # The two species are NOT the same problem. C. koseri (and K. oxytoca)
        # carry a chromosomal CLASS A beta-lactamase, so aminopenicillins fail
        # but the inhibitor combinations still work. C. freundii carries an
        # inducible AmpC, which clavulanate and sulbactam do not inhibit. Giving
        # C. koseri its own rule keeps amoxicillin-clavulanate reportable for it,
        # which the AmpC rule would have wrongly suppressed.
        "id": "intr_citrobacter_koseri_klebsiella_oxytoca_classA",
        "organisms": ["citrobacter koseri", "citrobacter diversus",
                      "klebsiella oxytoca"],
        "drugs": ["ampicillin", "amoxicillin", "ticarcillin", "carbenicillin"],
        "exclude": ["clav", "sulbactam", "tazobactam", "avibactam"],
        "reason_ar": ("C. koseri و K. oxytoca يحملان بيتا-لاكتاماز كروموسومي من "
                      "الفئة A — مقاومة جوهرية للأمينوبنسلينات. توليفات المثبِّط "
                      "(Amox-clav · Pip-Tazo) تظل فعّالة لأن المثبِّط يعمل على "
                      "الفئة A، بعكس AmpC في C. freundii."),
        "reason_en": ("C. koseri and K. oxytoca carry a chromosomal CLASS A "
                      "beta-lactamase — intrinsic aminopenicillin resistance. "
                      "Inhibitor combinations (amox-clav, pip-tazo) remain active "
                      "because the inhibitor works on class A, unlike the AmpC of "
                      "C. freundii."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_klebsiella_ampicillin",
        "organisms": ["klebsiella"],
        "drugs": ["ampicillin", "amoxicillin", "ticarcillin", "carbenicillin"],
        # An inhibitor restores activity — those combinations are NOT intrinsic.
        "exclude": ["clav", "sulbactam", "tazobactam", "avibactam", "vaborbactam",
                    "relebactam"],
        "reason_ar": ("Klebsiella spp. تحمل بيتا-لاكتاماز SHV-1 كروموسومياً — "
                      "مقاومة جوهرية للأمينوبنسلينات. (التركيبات مع مثبط ليست "
                      "مقاومة جوهرية.)"),
        "reason_en": ("Klebsiella spp. carry chromosomal SHV-1 — intrinsic "
                      "aminopenicillin resistance. (Inhibitor combinations are not "
                      "intrinsically resistant.)"),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_proteus_mirabilis",
        "organisms": ["proteus mirabilis"],
        "drugs": ["tetracycline", "doxycycline", "minocycline", "tigecycline",
                  "colistin", "polymyxin", "nitrofurantoin"],
        "exclude": [],
        "reason_ar": "Proteus mirabilis مقاوم جوهرياً للتتراسيكلينات · colistin · nitrofurantoin.",
        "reason_en": ("Proteus mirabilis is intrinsically resistant to tetracyclines, "
                      "colistin, nitrofurantoin, tetracycline and doxycycline "
                      "(minocycline and tigecycline remain active)."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_morganella_providencia_proteus_vulgaris",
        "organisms": ["morganella", "providencia", "proteus vulgaris",
                      "proteus penneri"],
        # "amoxicillin" and the oral 1st-gen cephalosporins were absent, so
        # amox-clav / cephalexin / cefadroxil / cefaclor / cefoxitin escaped the
        # rule here while clinical_data.INTRINSIC_RESISTANCE banned them. Sulbactam
        # is NOT excluded: chromosomal AmpC is not inhibited by it, so
        # ampicillin-sulbactam stays intrinsically resistant for this tribe.
        "drugs": ["ampicillin", "amoxicillin", "cephalexin", "cefadroxil",
                  "cephradine", "cefaclor", "cefuroxime", "cefazolin",
                  "cephalothin", "cefoxitin",
                  "tetracycline", "doxycycline", "minocycline", "tigecycline",
                  "colistin", "polymyxin", "nitrofurantoin"],
        "exclude": ["tazobactam", "avibactam"],
        "reason_ar": ("مقاومة جوهرية (AmpC كروموسومي + خصائص نوعية) — "
                      "أمينوبنسلينات · سيفالوسبورين ١/٢ · تتراسيكلينات · "
                      "colistin · nitrofurantoin."),
        "reason_en": ("Intrinsic (chromosomal AmpC plus species traits) — "
                      "aminopenicillins, 1st/2nd-gen cephalosporins, tetracyclines, "
                      "colistin, nitrofurantoin."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_serratia",
        "organisms": ["serratia"],
        "drugs": ["ampicillin", "amoxicillin", "cephalexin", "cefadroxil",
                  "cephradine", "cefaclor", "cefazolin", "cephalothin",
                  "cefuroxime", "cefoxitin", "colistin", "polymyxin",
                  "nitrofurantoin",
                  # EUCAST v3.3 Table 2 fn.5 -- tetracycline and doxycycline ARE
                  # intrinsic for S. marcescens; minocycline and tigecycline are
                  # NOT, and are excluded below so they stay reportable.
                  "tetracycline", "doxycycline"],
        "exclude": ["tazobactam", "avibactam", "minocycline", "tigecycline"],
        "reason_ar": ("Serratia marcescens: AmpC كروموسومي — مقاومة جوهرية "
                      "للأمينوبنسلينات وسيفالوسبورين ١/٢ والسيفاميسين، "
                      "و colistin و nitrofurantoin."),
        "reason_en": ("Serratia marcescens: chromosomal AmpC — intrinsic to "
                      "aminopenicillins, 1st/2nd-gen cephalosporins, cephamycins, "
                      "colistin and nitrofurantoin."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_enterobacter_citrobacter_ampc",
        "organisms": ["enterobacter", "klebsiella aerogenes", "citrobacter freundii",
                      "hafnia"],
        # Chromosomal AmpC is not inhibited by sulbactam either, so ampicillin-
        # sulbactam must NOT be exempted (it was, via the "sulbactam" exclude).
        # Cefoperazone-sulbactam is protected by the explicit exclude below
        # instead, because cefoperazone is a 3rd-gen agent judged on its own AST.
        "drugs": ["ampicillin", "amoxicillin", "cephalexin", "cefadroxil",
                  "cephradine", "cefaclor", "cefazolin", "cephalothin",
                  "cefuroxime", "cefoxitin"],
        "exclude": ["tazobactam", "avibactam", "cefoperazone"],
        "reason_ar": ("AmpC كروموسومي مُحدَث — مقاومة جوهرية للأمينوبنسلينات "
                      "وسيفالوسبورين الجيل الأول والسيفاميسين."),
        "reason_en": ("Inducible chromosomal AmpC — intrinsic to aminopenicillins, "
                      "1st-gen cephalosporins and cephamycins."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 2",
    },
    {
        "id": "intr_pseudomonas",
        "organisms": ["pseudomonas aeruginosa"],
        "drugs": ["ampicillin", "amoxicillin", "cefazolin", "cephalothin",
                  "cefuroxime", "cefoxitin", "cefotaxime", "ceftriaxone",
                  "ertapenem", "tetracycline", "doxycycline", "tigecycline",
                  "trimethoprim", "chloramphenicol", "kanamycin", "nitrofurantoin"],
        "exclude": ["tazobactam", "avibactam"],
        "reason_ar": ("P. aeruginosa مقاوم جوهرياً — لا تُبلَّغ هذه المضادات "
                      "حتى لو ظهرت حسّاسة. (Ceftazidime و Cefepime فقط من "
                      "السيفالوسبورينات لها فاعلية.)"),
        "reason_en": ("P. aeruginosa is intrinsically resistant — do not report these "
                      "even if they test susceptible. (Only ceftazidime and cefepime "
                      "among the cephalosporins are active.)"),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 3",
    },
    {
        "id": "intr_acinetobacter",
        "organisms": ["acinetobacter"],
        # EUCAST v3.3 Table 2 fn.2 -- "Acinetobacter is intrinsically resistant to
        # tetracycline and doxycycline but not to minocycline and tigecycline."
        # Minocycline/tigecycline are excluded below so they stay reportable; they
        # are the tetracyclines that actually work here and IDSA v4.0 lists
        # minocycline among CRAB options.
        "drugs": ["ampicillin", "amoxicillin", "aztreonam", "ertapenem",
                  "trimethoprim", "fosfomycin", "chloramphenicol",
                  "tetracycline", "doxycycline"],
        # BUG FIXED: "clav" used to sit in this exclude list, which exempted
        # amoxicillin-clavulanate from the rule. That is backwards. Clavulanate
        # has NO useful activity against Acinetobacter, so amox-clav IS
        # intrinsically resistant and EUCAST lists it explicitly. Sulbactam is
        # the exception -- it has intrinsic anti-Acinetobacter activity of its
        # own -- so only "sulbactam" belongs here. Leaving "clav" in made this
        # module contradict clinical_data.INTRINSIC_RESISTANCE, which correctly
        # bans amox-clav: the recommendation panel refused the drug while the QC
        # panel stayed silent about a Susceptible result for it.
        "exclude": ["sulbactam", "sulfamethoxazole", "sulphamethoxazol",
                    "minocycline", "tigecycline"],
        "reason_ar": ("Acinetobacter مقاوم جوهرياً — بما في ذلك "
                      "Amoxicillin/Clavulanate (الـ clavulanate بلا فاعلية هنا). "
                      "(ملاحظة: Ampicillin/Sulbactam استثناء — الـ sulbactam نفسه "
                      "فعّال ضد Acinetobacter.)"),
        "reason_en": ("Acinetobacter is intrinsically resistant — "
                      "amoxicillin-clavulanate included (clavulanate adds nothing "
                      "here). (Note: ampicillin-sulbactam is an exception — "
                      "sulbactam itself has intrinsic activity against "
                      "Acinetobacter.)"),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 3",
    },
    {
        "id": "intr_nonfermenter_narrow_spectrum",
        "organisms": ["pseudomonas", "acinetobacter", "stenotrophomonas",
                      "burkholderia"],
        "drugs": ["benzylpenicillin", "cephalexin", "cefadroxil", "cephradine",
                  "cephalothin", "cefazolin", "cefaclor", "cefuroxime",
                  "cefoxitin", "vancomycin", "teicoplanin", "dalbavancin",
                  "fusidic", "erythromycin", "clarithromycin", "azithromycin",
                  "clindamycin", "rifampicin", "rifampin", "linezolid"],
        "exclude": [],
        "reason_ar": ("اللا-مُخمِّرات (Pseudomonas · Acinetobacter · "
                      "Stenotrophomonas · Burkholderia) مقاومة جوهرياً للبنسلين G "
                      "وسيفالوسبورينات الجيل الأول والثاني والجلايكوببتيدات "
                      "والماكروليدات واللينكوزاميدات والريفامبيسين "
                      "والأوكسازوليدينونات. نتيجة S هنا خطأ معملي."),
        "reason_en": ("Non-fermentative Gram-negatives (Pseudomonas, "
                      "Acinetobacter, Stenotrophomonas, Burkholderia) are "
                      "intrinsically resistant to benzylpenicillin, 1st- and "
                      "2nd-generation cephalosporins, glycopeptides, "
                      "lipoglycopeptides, fusidic acid, macrolides, lincosamides, "
                      "rifampicin and oxazolidinones. A Susceptible result here is "
                      "a laboratory error."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 3 (header)",
    },
    {
        "id": "intr_stenotrophomonas",
        "organisms": ["stenotrophomonas"],
        "drugs": ["imipenem", "meropenem", "ertapenem", "gentamicin", "amikacin",
                  "tobramycin", "ampicillin", "amoxicillin", "cefotaxime",
                  "ceftriaxone", "aztreonam", "piperacillin",
                  # EUCAST v3.3 Table 2 fn.7 -- S. maltophilia is
                  # intrinsically resistant to TETRACYCLINE ONLY. Unlike
                  # Acinetobacter and Serratia, doxycycline IS active here
                  # and must stay reportable, so it is excluded below.
                  "tetracycline"],
        "exclude": ["doxycycline", "minocycline", "tigecycline"],
        "reason_ar": ("S. maltophilia مقاوم جوهرياً لمعظم البيتا-لاكتام "
                      "(بما فيها الكاربابينيمات — L1 metallo-β-lactamase) "
                      "والأمينوجلايكوسيدات. الخيار المعتمد: Trimethoprim/Sulfamethoxazole."),
        "reason_en": ("S. maltophilia is intrinsically resistant to most beta-lactams "
                      "(carbapenems included — L1 metallo-beta-lactamase) and to "
                      "aminoglycosides. The established option is "
                      "trimethoprim-sulfamethoxazole."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 3",
    },
    {
        # clinical_data now bans all beta-lactams for MRSA, but this module had no
        # matching rule, so a "Ceftriaxone S" on an MRSA passed QC in silence while
        # the recommendation panel refused it. Same two-engine split as the
        # Acinetobacter and Enterococcus cases.
        "id": "intr_mrsa_betalactams",
        "organisms": ["mrsa", "methicillin-resistant staph", "methicillin resistant staph"],
        "not_organisms": [],
        "drugs": ["penicillin", "oxacillin", "ampicillin", "amoxicillin",
                  "piperacillin", "cephalexin", "cefadroxil", "cephradine",
                  "cefazolin", "cefaclor", "cefuroxime", "cefoxitin",
                  "ceftriaxone", "cefotaxime", "ceftazidime", "cefixime",
                  "cefepime", "cefoperazone", "imipenem", "meropenem",
                  "ertapenem", "aztreonam"],
        # The anti-MRSA cephalosporins retain activity and must stay reportable.
        "exclude": ["ceftaroline", "ceftobiprole"],
        "reason_ar": ("MRSA يحمل mecA/mecC المنتج لـ PBP2a منخفض الألفة — كل "
                      "البيتا-لاكتام غير فعّال (عدا Ceftaroline/Ceftobiprole). "
                      "نتيجة S لأي بنسلين أو سيفالوسبورين تقليدي أو كاربابينيم "
                      "هنا خطأ معملي ولا تُبلَّغ."),
        "reason_en": ("MRSA carries mecA/mecC encoding low-affinity PBP2a — ALL "
                      "beta-lactams are inactive (except ceftaroline/ceftobiprole). "
                      "A Susceptible result for any conventional penicillin, "
                      "cephalosporin or carbapenem is a laboratory error and must "
                      "not be reported."),
        "reference": "EUCAST Expert Rules -- staphylococci; CLSI M100 Ed36 Table 2C",
    },
    {
        "id": "intr_mycoplasma_cellwall_agents",
        "organisms": ["mycoplasma", "ureaplasma"],
        "not_organisms": [],
        "drugs": ["penicillin", "oxacillin", "ampicillin", "amoxicillin",
                  "piperacillin", "cephalexin", "cefadroxil", "cephradine",
                  "cefazolin", "cefaclor", "cefuroxime", "cefoxitin",
                  "ceftriaxone", "cefotaxime", "ceftazidime", "cefixime",
                  "cefepime", "cefoperazone", "imipenem", "meropenem",
                  "ertapenem", "aztreonam", "vancomycin", "teicoplanin",
                  "fosfomycin"],
        "exclude": [],
        "reason_ar": ("الـ Mycoplasma و Ureaplasma ليس لهما جدار خلوي "
                      "(peptidoglycan) — فكل مضاد يعمل على جدار الخلية "
                      "(بيتا-لاكتام · جلايكوببتيد · فوسفومايسين) غير فعّال "
                      "جوهرياً. العلاج: ماكروليد أو تتراسيكلين أو فلوروكينولون."),
        "reason_en": ("Mycoplasma and Ureaplasma have NO peptidoglycan cell wall, "
                      "so every cell-wall-active agent (beta-lactams, "
                      "glycopeptides, fosfomycin) is intrinsically inactive. "
                      "Treat with a macrolide, tetracycline or fluoroquinolone."),
        "reference": "EUCAST Intrinsic Resistance v3.3 -- organisms without a cell wall",
    },
    {
        "id": "intr_staph_gram_neg_agents",
        "organisms": ["staphylococcus", "staph"],
        "drugs": ["aztreonam", "colistin", "polymyxin", "nalidixic acid",
                  "temocillin"],
        "exclude": [],
        "reason_ar": "المكوّرات العنقودية مقاومة جوهرياً لمضادات سالبة الجرام هذه.",
        "reason_en": "Staphylococci are intrinsically resistant to these Gram-negative agents.",
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 4",
    },
    {
        "id": "intr_enterococcus_cephalosporins",
        "organisms": ["enterococc"],
        "drugs": ["cephalexin", "cefazolin", "cefuroxime", "cefoxitin",
                  "cefotaxime", "ceftriaxone", "ceftazidime", "cefepime",
                  "cefoperazone", "clindamycin", "fusidic acid", "aztreonam"],
        "exclude": [],
        "reason_ar": ("الـ Enterococci مقاومة جوهرياً لكل السيفالوسبورينات "
                      "و clindamycin و aztreonam — لا تُبلَّغ أبداً كحسّاسة."),
        "reason_en": ("Enterococci are intrinsically resistant to ALL cephalosporins, "
                      "clindamycin and aztreonam — never report as susceptible."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 4 · CLSI M100 App. B",
    },
    {
        # Found by the scenario matrix (INV-9): clinical_data bans aminoglycosides
        # for streptococci and enterococci, but this module had no matching rule,
        # so a standard-disk "Gentamicin S" on an Enterococcus passed QC in
        # silence while the recommendation panel refused the drug.
        #
        # EUCAST Expert Rules Table 4 lists Enterococcus spp. and Streptococcus
        # spp. as intrinsically resistant to aminoglycosides (low-level). The
        # clinically important consequence is NOT simply "resistant": an
        # aminoglycoside is never monotherapy for these organisms, but combined
        # with a cell-wall-active agent it is synergistic and bactericidal --
        # PROVIDED the isolate has no HIGH-level aminoglycoside resistance.
        #
        # That is a different test. HLAR needs high-content disks (gentamicin
        # 120 ug, streptomycin 300 ug) or an agar screen; the routine 10 ug disk
        # is explicitly not valid for it. And CLSI defines an HLAR screen only
        # for gentamicin and streptomycin -- amikacin, tobramycin, kanamycin and
        # netilmicin have none, and E. faecium's chromosomal AAC(6')-Ie abolishes
        # their synergy anyway. So a routine S/I/R for any aminoglycoside on
        # these organisms is uninterpretable however it is read.
        "id": "intr_strep_enterococcus_aminoglycosides",
        "organisms": ["enterococc", "streptococc", "vre"],
        "drugs": ["gentamicin", "amikacin", "tobramycin", "kanamycin",
                  "netilmicin", "streptomycin", "neomycin"],
        "exclude": [],
        "reason_ar": ("الـ Enterococci والـ Streptococci مقاومة جوهرياً "
                      "(low-level) للأمينوجلايكوسيدات — لا تصلح **أبداً** "
                      "كعلاج منفرد. قرص الـ 10 ميكروجرام الروتيني غير صالح "
                      "للتفسير هنا. التوليفة مع مضاد فعّال على جدار الخلية "
                      "(Ampicillin / Vancomycin) تعطي تآزراً قاتلاً، وتُقيَّم "
                      "بفحص HLAR عالي التركيز فقط (Gentamicin 120µg · "
                      "Streptomycin 300µg). الـ Amikacin و Tobramycin ليس لهما "
                      "فحص HLAR أصلاً."),
        "reason_en": ("Enterococci and streptococci are intrinsically (low-level) "
                      "resistant to aminoglycosides — never valid as monotherapy. "
                      "The routine 10 ug disk is not interpretable for them. "
                      "Combined with a cell-wall-active agent (ampicillin, "
                      "vancomycin) an aminoglycoside is synergistic and "
                      "bactericidal, but that is predicted ONLY by a high-content "
                      "HLAR screen (gentamicin 120 ug, streptomycin 300 ug). "
                      "Amikacin and tobramycin have no HLAR screen at all."),
        "reference": ("EUCAST Expert Rules / Intrinsic Resistance v3.3, Table 4 · "
                      "CLSI M100 Ed36 Table 2D (HLAR screen)"),
    },
    {
        "id": "intr_enterococcus_sxt_invivo",
        "organisms": ["enterococc"],
        "drugs": ["trimethoprim", "sulfamethoxazole", "sulphamethoxazol",
                  "cotrimoxazole", "co-trimoxazole"],
        "exclude": [],
        "reason_ar": ("Enterococci تظهر حسّاسة لـ TMP-SMX في المزرعة لكنها "
                      "**غير فعّالة سريرياً** — البكتيريا تستهلك الفولات الجاهز "
                      "من الوسط وتتخطى المسار المُثبَّط. لا تُبلَّغ."),
        "reason_en": ("Enterococci test susceptible to TMP-SMX in vitro but it is "
                      "NOT clinically effective — they take up exogenous folate and "
                      "bypass the blocked pathway. Do not report."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 4 · CLSI M100 App. B",
    },
    {
        "id": "intr_listeria_cephalosporins",
        "organisms": ["listeria"],
        "drugs": ["cephalexin", "cefazolin", "cefuroxime", "cefoxitin",
                  "cefotaxime", "ceftriaxone", "ceftazidime", "cefepime",
                  "cefoperazone", "fosfomycin"],
        "exclude": [],
        "reason_ar": ("Listeria monocytogenes مقاومة جوهرياً لكل السيفالوسبورينات — "
                      "سبب معروف لفشل علاج التهاب السحايا. الخيار: Ampicillin."),
        "reason_en": ("Listeria monocytogenes is intrinsically resistant to ALL "
                      "cephalosporins — a known cause of meningitis treatment "
                      "failure. The option is ampicillin."),
        "reference": "EUCAST Intrinsic Resistance v3.3, Table 4",
    },
]


# ── 2. NO BREAKPOINTS ────────────────────────────────────────────────────────
# Distinct from intrinsic resistance: the drug may well work. The point is that
# nobody has published a validated zone/MIC cut-off for this pairing, so the
# S/I/R printed against it was produced by reading the zone against a table that
# does not cover it — or against nothing at all.
NO_BREAKPOINT_RULES: List[Dict[str, Any]] = [
    {
        # Added to close a silence in the QC panel: clinical_data.INTRINSIC_RESISTANCE
        # routes these to Avoid for Acinetobacter / Stenotrophomonas, but neither
        # EUCAST nor CLSI publishes criteria for the pairing, so the honest label
        # is "no breakpoints" rather than "intrinsic". Before this rule the QC
        # panel said nothing while the recommendation panel refused the drug --
        # exactly the kind of split that makes a reviewer distrust both.
        "id": "nobp_nonfermenter_narrow_spectrum",
        "organisms": ["acinetobacter", "stenotrophomonas", "burkholderia"],
        "not_organisms": [],
        # The narrow-spectrum cephalosporins moved OUT of this rule and into
        # intr_nonfermenter_narrow_spectrum: EUCAST v3.3 Table 3 states outright
        # that non-fermenters are intrinsically resistant to 1st/2nd-generation
        # cephalosporins -- a stronger claim than "no breakpoints published".
        "drugs": ["cefixime", "cefpodoxime", "nitrofurantoin", "norfloxacin"],
        "exclude": [],
        "reason_ar": ("لا توجد breakpoints في EUCAST ولا CLSI لهذه المضادات ضد "
                      "اللا-مُخمِّرات (Acinetobacter · Stenotrophomonas · "
                      "Burkholderia). الـ S/I/R المطبوع هنا قُرِئ على جدول لا "
                      "يغطي هذا الاقتران — النتيجة غير مُعايَرة ولا يُبنى عليها علاج."),
        "reason_en": ("Neither EUCAST nor CLSI publishes breakpoints for these "
                      "agents against the non-fermenters (Acinetobacter, "
                      "Stenotrophomonas, Burkholderia). Any S/I/R printed here was "
                      "read against a table that does not cover the pairing — it "
                      "is uncalibrated and must not guide therapy."),
        "reference": "EUCAST Breakpoint Tables v16.0 · CLSI M100 Ed36 Table 2B-2 / 2B-3",
    },
    {
        "id": "nobp_azithromycin_enterobacterales",
        "organisms": ENTEROBACTERALES,
        # Breakpoints exist ONLY for typhoidal Salmonella (Typhi / Paratyphi) and
        # Shigella. Non-typhoidal Salmonella has no validated azithromycin
        # breakpoint, so it must NOT be exempted here (see commit note).
        "not_organisms": ["salmonella typhi", "salmonella paratyphi",
                          "salmonella enterica serovar typhi",
                          "salmonella enterica serovar paratyphi", "shigella"],
        "drugs": ["azithromycin"],
        "exclude": [],
        "reason_ar": ("breakpoints الأزيثرومايسين مُحدَّدة فقط لـ Salmonella Typhi/Paratyphi "
                      "و Shigella. لأي عزلة أخرى من الـ Enterobacterales (بما فيها "
                      "السالمونيلا غير التيفية) لا يوجد جدول تفسير — أكِّد النوع "
                      "(serovar) قبل الاعتماد على النتيجة."),
        "reason_en": ("Azithromycin breakpoints are defined only for Salmonella "
                      "Typhi / Paratyphi and Shigella. For any other Enterobacterales "
                      "isolate (non-typhoidal Salmonella included) there is no "
                      "interpretive table — confirm the serovar before relying on "
                      "this result."),
        "reference": "EUCAST Breakpoint Tables v16.0 — Enterobacterales, azithromycin note",
    },
    {
        "id": "nobp_cefoperazone",
        "organisms": [],
        "not_organisms": [],
        "drugs": ["cefoperazone"],
        "exclude": [],
        "reason_ar": ("Cefoperazone (منفرداً أو مع sulbactam): لا توجد breakpoints "
                      "في EUCAST، و CLSI سحبت breakpoints الـ cefoperazone. "
                      "التركيبة مع sulbactam ليس لها breakpoints في أي من المرجعين. "
                      "شائع في مصر لكن النتيجة غير مُعايَرة."),
        "reason_en": ("Cefoperazone (alone or with sulbactam): EUCAST has no "
                      "breakpoints and CLSI withdrew the cefoperazone breakpoints. "
                      "The sulbactam combination has none in either. Widely used in "
                      "Egypt, but the result is uncalibrated."),
        "reference": "EUCAST Breakpoint Tables v16.0 · CLSI M100 Ed36",
    },
    {
        "id": "nobp_nitrofurantoin_non_ecoli",
        "organisms": ENTEROBACTERALES,
        "not_organisms": ["escherichia", "e. coli", "e.coli"],
        "drugs": ["nitrofurantoin"],
        "exclude": [],
        "reason_ar": ("breakpoints النيتروفورانتوين في EUCAST مُحدَّدة لـ E. coli "
                      "فقط (عدوى مسالك بولية غير معقّدة). لا تُستقرأ لأنواع أخرى."),
        "reason_en": ("EUCAST nitrofurantoin breakpoints are for E. coli only "
                      "(uncomplicated UTI). They do not extrapolate to other species."),
        "reference": "EUCAST Breakpoint Tables v16.0 — Enterobacterales",
    },
    {
        "id": "nobp_fosfomycin_oral_non_ecoli",
        "organisms": ENTEROBACTERALES,
        "not_organisms": ["escherichia", "e. coli", "e.coli"],
        "drugs": ["fosfomycin"],
        "exclude": [],
        "reason_ar": ("breakpoints الفوسفومايسين الفموي في EUCAST و CLSI مُحدَّدة "
                      "لـ E. coli فقط. (EUCAST قصرَتها على E. coli في 2020 بعد أن "
                      "كانت لكل الـ Enterobacterales.) استقراؤها لأنواع أخرى غير مدعوم."),
        "reason_en": ("Oral fosfomycin breakpoints in both EUCAST and CLSI are for "
                      "E. coli only. (EUCAST restricted them to E. coli in 2020, "
                      "having previously covered all Enterobacterales.) Extrapolation "
                      "is unsupported."),
        "reference": "EUCAST Breakpoint Tables v16.0 · CLSI M100 Ed36",
    },
    {
        "id": "nobp_imipenem_proteae",
        "organisms": ["proteus", "morganella", "providencia"],
        "not_organisms": [],
        "drugs": ["imipenem"],
        "exclude": ["relebactam"],
        "reason_ar": ("EUCAST v16.0 (ملاحظة Enterobacterales رقم 2): نشاط "
                      "الإيميبينيم ضد Proteus و Morganella و Providencia منخفض "
                      "جوهرياً — MICs أعلى من باقي الـ Enterobacterales حتى بدون "
                      "أي آلية مقاومة مكتسبة. لا تعتمد على نتيجة S هنا؛ "
                      "الميروبينيم هو الكاربابينيم المفضّل لهذه الأنواع."),
        "reason_en": ("EUCAST v16.0 Enterobacterales note 2: imipenem has "
                      "intrinsically LOW activity against Proteus spp., "
                      "Morganella morganii and Providencia spp. -- MICs run higher "
                      "than for other Enterobacterales even with no acquired "
                      "mechanism. Do not rely on a Susceptible imipenem result "
                      "here; meropenem is the preferred carbapenem."),
        "reference": "EUCAST Breakpoint Tables v16.0 -- Enterobacterales note 2",
    },
    {
        # EUCAST v16.0 note 3/A verbatim: "the activity of tigecycline varies from
        # INSUFFICIENT in Serratia spp., Proteus spp., Morganella morganii and
        # Providencia spp. to variable in other species." Serratia was missing.
        "id": "nobp_tigecycline_proteae",
        "organisms": ["proteus", "morganella", "providencia", "serratia"],
        "not_organisms": [],
        "drugs": ["tigecycline"],
        "exclude": [],
        "reason_ar": ("نشاط التيجيسيكلين ضد Proteus / Morganella / Providencia "
                      "غير كافٍ — لا breakpoints."),
        "reason_en": ("Tigecycline activity against Proteus, Morganella and "
                      "Providencia is insufficient — no breakpoints."),
        "reference": "EUCAST Breakpoint Tables v16.0 — Enterobacterales, tigecycline note",
    },
]


# ── 3. Tests S in vitro, fails in vivo ───────────────────────────────────────
# Neither intrinsic nor missing a breakpoint: the breakpoint exists, the zone is
# real, and the drug still does not work in the patient. The most dangerous of
# the three, because nothing about the result looks wrong.
INEFFECTIVE_INVIVO_RULES: List[Dict[str, Any]] = [
    {
        "id": "invivo_salmonella_shigella_aminoglycoside_ceph12",
        "organisms": ["salmonella", "shigella"],
        "not_organisms": [],
        "drugs": ["gentamicin", "amikacin", "tobramycin", "netilmicin",
                  "kanamycin", "streptomycin", "cefazolin", "cephalexin",
                  "cefuroxime", "cefoxitin", "cephalothin"],
        "exclude": [],
        "reason_ar": ("Salmonella و Shigella: الأمينوجلايكوسيدات وسيفالوسبورين "
                      "الجيل ١/٢ والسيفاميسين قد تظهر **حسّاسة في المزرعة لكنها "
                      "غير فعّالة سريرياً** (لا تصل داخل الخلية حيث تختبئ البكتيريا). "
                      "لا تُبلَّغ كحسّاسة."),
        "reason_en": ("Salmonella and Shigella: aminoglycosides, 1st/2nd-gen "
                      "cephalosporins and cephamycins may appear ACTIVE IN VITRO but "
                      "are NOT clinically effective (they do not reach the "
                      "intracellular compartment where the organism sits). Do not "
                      "report as susceptible."),
        "reference": "CLSI M100 Ed36 — Table 2A, Salmonella/Shigella note",
    },
]


# ── 4. WRONG SPECTRUM — Gram-stain level ─────────────────────────────────────
# The species-keyed tables above cannot fire when the isolate is only identified
# to Gram-stain level (e.g. "Gram-negative bacilli"), which is exactly when a
# wrong-spectrum agent slips through unflagged. An anti-staphylococcal penicillin
# or a glycopeptide has no activity and no breakpoint against ANY Gram-negative;
# a monobactam or a polymyxin likewise against ANY Gram-positive. This pass keys
# on the Gram reaction (explicit "gram negative/positive" text, or a genus that
# implies it) so it also covers unidentified isolates.
_WS_GP_ONLY = {   # no Gram-NEGATIVE activity / breakpoint  (needle -> class label)
    "vancomycin": "glycopeptide", "teicoplanin": "glycopeptide",
    "linezolid": "oxazolidinone", "daptomycin": "lipopeptide",
    "oxacillin": "isoxazolyl-penicillin",       # also catches cl-/dicl-/flucloxacillin
    "flucloxacillin": "isoxazolyl-penicillin", "nafcillin": "anti-staphylococcal penicillin",
    "flumox": "anti-staphylococcal penicillin combination",
}
_WS_GN_ONLY = {   # no Gram-POSITIVE activity  (needle -> class label)
    "aztreonam": "monobactam", "colistin": "polymyxin", "polymyxin": "polymyxin",
    "temocillin": "penicillin (Gram-negative only)",
}
# Genus lists used ONLY to infer the Gram reaction of a named isolate.
_WS_GN_GENERA = [
    "escherichia", "e. coli", "e.coli", "klebsiella", "raoultella", "enterobacter",
    "citrobacter", "serratia", "proteus", "morganella", "providencia", "hafnia",
    "pantoea", "salmonella", "shigella", "yersinia", "pseudomonas", "acinetobacter",
    "stenotrophomonas", "burkholderia", "haemophilus", "moraxella", "neisseria",
    "campylobacter", "vibrio", "aeromonas", "bacteroides", "achromobacter",
    "kingella", "pasteurella", "brucella", "bordetella", "legionella",
    "enterobacterales", "coliform",
]
_WS_GP_GENERA = [
    "staphylococc", "staph ", "mrsa", "mssa", "streptococc", "strep ",
    "enterococc", "vre", "listeria", "corynebacter", "diphther", "bacillus",
    "clostridi", "peptostrept", "micrococc",
]


def _is_gram_positive(org: str) -> bool:
    o = (org or "").lower()
    if "gram positive" in o or "gram-positive" in o or "gram +ve" in o:
        return True
    return any(g in o for g in _WS_GP_GENERA)


def _is_gram_negative(org: str) -> bool:
    o = (org or "").lower()
    if "gram negative" in o or "gram-negative" in o or "gram -ve" in o:
        return True
    if _is_gram_positive(o):
        return False
    return any(g in o for g in _WS_GN_GENERA)


def _check_wrong_spectrum(organism: str, sir_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """One issue per offending drug (per-drug so the caller can de-duplicate)."""
    out: List[Dict[str, Any]] = []
    gn, gp = _is_gram_negative(organism), _is_gram_positive(organism)
    if not gn and not gp:
        return out
    agents = _WS_GP_ONLY if gn else _WS_GN_ONLY
    side_en = "Gram-negative" if gn else "Gram-positive"
    side_ar = "سالبة الجرام" if gn else "موجبة الجرام"
    seen = set()
    for drug in sir_map:
        if not (sir_map.get(drug) or "").strip():
            continue
        klass = None
        for needle, kl in agents.items():
            if _nk(needle) in _nk(drug):
                klass = kl
                break
        if klass is None or drug in seen:
            continue
        seen.add(drug)
        out.append({
            "id": f"wrongspectrum_{side_en.lower()}:{drug}",
            "category": "wrong_spectrum",
            "severity": "error",   # refined to warning below if the result is R
            "drugs": [drug],
            "results": {drug: sir_map[drug]},
            "reason_ar": (f"{drug} من فئة ({klass}) لا فاعلية لها ولا breakpoints ضد "
                          f"البكتيريا {side_ar} — يجب ألا يظهر على لوحة كائن {side_ar}."),
            "reason_en": (f"{drug} is a {klass} with no activity and no breakpoint against "
                          f"{side_en} bacteria — it must not appear on a {side_en} panel."),
            "reference": "EUCAST Intrinsic Resistance v3.3 · Breakpoint Tables v16.0",
        })
    return out


def _check(rules, organism, sir_map, category, severity):
    out: List[Dict[str, Any]] = []
    for rule in rules:
        if rule["organisms"] and not _org_matches(organism, rule["organisms"]):
            continue
        if rule.get("not_organisms") and _org_matches(organism, rule["not_organisms"]):
            continue
        hits = [d for d in sir_map
                if _drug_matches(d, rule["drugs"], rule.get("exclude", []))]
        if not hits:
            continue
        out.append({
            "id": f'{rule["id"]}:{"|".join(sorted(hits))}',
            "category": category,
            "severity": severity,
            "drugs": sorted(hits),
            "results": {d: sir_map[d] for d in sorted(hits)},
            "reason_ar": rule["reason_ar"],
            "reason_en": rule["reason_en"],
            "reference": rule["reference"],
        })
    return out


def check_reportability(organism: str, sir_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Flag agents on this panel that should not be reported for this organism.

    Returns a list of issues, each naming the offending drug(s), the reported
    S/I/R, why the pairing is invalid, and the document that says so.

    Severity is deliberately split. An intrinsic-resistance hit reported as S is
    an `error` — a wrong result that a clinician can act on. A no-breakpoint hit
    is a `warning` — the result is meaningless rather than wrong, and the drug
    may still be the right choice on other grounds. An intrinsic hit correctly
    reported R is still worth surfacing (the panel is wasting a disk and a slot)
    but it is not a patient-safety event, so it drops to `warning` too.
    """
    if not sir_map or not organism:
        return []

    issues: List[Dict[str, Any]] = []
    issues += _check(INTRINSIC_RULES, organism, sir_map, "intrinsic", "error")
    issues += _check(NO_BREAKPOINT_RULES, organism, sir_map, "no_breakpoint", "warning")
    issues += _check(INEFFECTIVE_INVIVO_RULES, organism, sir_map, "ineffective_in_vivo", "error")

    # Gram-stain-level wrong-spectrum pass — fires for unidentified isolates too.
    # De-duplicate against any drug already named by a species-keyed rule so an
    # agent is never reported twice (e.g. oxacillin on E. coli).
    _already = {d for iss in issues for d in iss["drugs"]}
    for ws in _check_wrong_spectrum(organism, sir_map):
        if ws["drugs"][0] in _already:
            continue
        issues.append(ws)

    for iss in issues:
        if iss["category"] in ("intrinsic", "wrong_spectrum"):
            # Reported R on an intrinsically-resistant / wrong-spectrum drug is the
            # right answer for the wrong reason — no patient is harmed, but the
            # disk should not be on the plate. A non-R result IS misleading.
            if all(v == "R" for v in iss["results"].values()):
                iss["severity"] = "warning"
                iss["misreported"] = False
            else:
                iss["severity"] = "error"
                iss["misreported"] = True
    return issues


def format_issue(issue: Dict[str, Any], lang: str = "ar") -> Dict[str, str]:
    """Render one reportability issue into the {message, fix} shape run_ast_qc uses."""
    drugs = " · ".join(f'{d} [{issue["results"][d]}]' for d in issue["drugs"])
    reason = issue["reason_ar"] if lang == "ar" else issue["reason_en"]

    if issue["category"] == "wrong_spectrum":
        head = ("🚫 **مضاد خارج الطيف** — " if lang == "ar"
                else "🚫 **Wrong-spectrum agent** — ")
        if issue.get("misreported"):
            fix = ("هذا المضاد لا فاعلية له إطلاقاً ضد هذه المجموعة من البكتيريا، "
                   "ونتيجة غير-R عليه مضللة. احذفه من التقرير واللوحة."
                   if lang == "ar" else
                   "This agent has no activity whatsoever against this Gram group, so a "
                   "non-R result on it is misleading. Remove it from the report and the panel.")
        else:
            fix = ("النتيجة (R) صحيحة لكن هذا المضاد لا يُختبر أصلاً لهذه المجموعة — "
                   "احذف القرص ووفّر المكان لمضاد مفيد."
                   if lang == "ar" else
                   "The R is correct, but this agent is never tested for this Gram group — "
                   "drop the disk and use the slot for an agent that informs a decision.")
        return {
            "message": f"{head}**{drugs}** — {reason}",
            "fix": f"{fix}  \n📖 {issue['reference']}",
        }

    if issue["category"] == "intrinsic":
        head = ("🚫 **مقاومة جوهرية** — " if lang == "ar"
                else "🚫 **Intrinsic resistance** — ")
        if issue.get("misreported"):
            fix = ("راجع اللوحة: هذا المضاد لا يُختبر أصلاً لهذا الكائن، ونتيجة "
                   "غير-R عليه خطأ معملي. احذفه من التقرير."
                   if lang == "ar" else
                   "Review the panel: this agent should not be tested against this "
                   "organism, and a non-R result on it is a laboratory error. Remove "
                   "it from the report.")
        else:
            fix = ("النتيجة (R) صحيحة لكنها متوقّعة سلفاً — احذف القرص من اللوحة "
                   "ووفّر المساحة لمضاد مفيد."
                   if lang == "ar" else
                   "The R is correct but was a foregone conclusion — drop the disk "
                   "and use the slot for an agent that informs a decision.")
    elif issue["category"] == "no_breakpoint":
        head = ("⚠️ **لا توجد breakpoints** — " if lang == "ar"
                else "⚠️ **No breakpoints** — ")
        fix = ("احذف هذا المضاد من التقرير أو أضِف تعليقاً بأن النتيجة غير "
               "قابلة للتفسير. لا تبنِ عليها قراراً علاجياً."
               if lang == "ar" else
               "Remove this agent from the report, or annotate it as "
               "uninterpretable. Do not base a treatment decision on it.")
    else:
        head = ("🚫 **حسّاس معملياً / غير فعّال سريرياً** — " if lang == "ar"
                else "🚫 **Susceptible in vitro / ineffective in vivo** — ")
        fix = ("لا تُبلَّغ كحسّاسة مهما كانت نتيجة القرص."
               if lang == "ar" else
               "Do not report as susceptible regardless of the disk result.")

    return {
        "message": f"{head}**{drugs}** — {reason}",
        "fix": f"{fix}  \n📖 {issue['reference']}",
    }
