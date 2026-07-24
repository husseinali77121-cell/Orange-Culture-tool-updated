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
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2 · CLSI M100 App. B",
    },
    {
        # Salmonella and Shigella test susceptible in vitro to oral 1st/2nd-gen
        # cephalosporins and to aminoglycosides, but these agents FAIL in vivo:
        # they do not reach the intracellular compartment where the organism
        # lives. Reporting them susceptible is the classic enteric-fever
        # reporting error, and it is the kind of error that gets a patient
        # treated with a drug that cannot work.
        "id": "intr_salmonella_shigella_invivo",
        "organisms": ["salmonella", "shigella"],
        "drugs": ["cephalexin", "cefadroxil", "cephradine", "cefaclor",
                  "cefazolin", "cefuroxime", "cephalothin",
                  "gentamicin", "tobramycin", "amikacin", "kanamycin"],
        "exclude": [],
        "reason_ar": ("Salmonella / Shigella: هذه المضادات تظهر حسّاسة معملياً "
                      "لكنها تفشل داخل الجسم (لا تصل للتجويف داخل الخلوي حيث "
                      "توجد الجرثومة). لا تُبلَّغ كحسّاسة — الخيارات المعتمدة: "
                      "fluoroquinolone أو ceftriaxone أو azithromycin."),
        "reason_en": ("Salmonella / Shigella: these agents test susceptible in "
                      "vitro but fail in vivo (they do not reach the "
                      "intracellular compartment). Do not report as susceptible "
                      "— the established options are a fluoroquinolone, "
                      "ceftriaxone, or azithromycin."),
        "reference": "CLSI M100 Ed36, Table 2A comment · EUCAST Expected Resistant Phenotypes v1.2 (2023)",
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
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2",
    },
    {
        "id": "intr_proteus_mirabilis",
        "organisms": ["proteus mirabilis"],
        "drugs": ["tetracycline", "doxycycline", "minocycline", "tigecycline",
                  "colistin", "polymyxin", "nitrofurantoin"],
        "exclude": [],
        "reason_ar": "Proteus mirabilis مقاوم جوهرياً للتتراسيكلينات · colistin · nitrofurantoin.",
        "reason_en": ("Proteus mirabilis is intrinsically resistant to tetracyclines, "
                      "colistin and nitrofurantoin."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2",
    },
    {
        "id": "intr_morganella_providencia_proteus_vulgaris",
        "organisms": ["morganella", "providencia", "proteus vulgaris",
                      "proteus penneri"],
        # "amoxicillin" and the oral 1st-gen cephalosporins were absent, so
        # amox-clav / cephalexin / cefadroxil / cefaclor / cefoxitin escaped this
        # rule while clinical_data.INTRINSIC_RESISTANCE banned them. Sulbactam is
        # NOT excluded: chromosomal AmpC is not inhibited by it, so
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
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2",
    },
    {
        "id": "intr_serratia",
        "organisms": ["serratia"],
        "drugs": ["ampicillin", "amoxicillin", "cefazolin", "cephalothin",
                  "cefuroxime", "cefoxitin", "colistin", "polymyxin",
                  "nitrofurantoin",
                  "cephalexin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "tetracycline",
                  "doxycycline"
                  ],
        "exclude": ["tazobactam", "avibactam"],
        "reason_ar": ("Serratia marcescens: AmpC كروموسومي — مقاومة جوهرية "
                      "للأمينوبنسلينات وسيفالوسبورين ١/٢ والسيفاميسين، "
                      "و colistin و nitrofurantoin."),
        "reason_en": ("Serratia marcescens: chromosomal AmpC — intrinsic to "
                      "aminopenicillins, 1st/2nd-gen cephalosporins, cephamycins, "
                      "colistin and nitrofurantoin."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2",
    },
    {
        "id": "intr_enterobacter_citrobacter_ampc",
        "organisms": ["enterobacter", "klebsiella aerogenes", "citrobacter freundii",
                      "hafnia"],
        "drugs": ["ampicillin", "amoxicillin", "cefazolin", "cephalothin",
                  "cefoxitin",
                  "cephalexin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "cefuroxime",
                  "sulbactam"
                  ],
        # Sulbactam does NOT inhibit chromosomal AmpC -- IDSA states that basal
        # AmpC production confers resistance to ampicillin, amoxicillin-
        # clavulanate AND ampicillin-sulbactam. Excluding "sulbactam" here
        # exempted amp-sulbactam from a rule that does apply to it.
        "exclude": ["tazobactam", "avibactam"],
        "reason_ar": ("AmpC كروموسومي مُحدَث — مقاومة جوهرية للأمينوبنسلينات "
                      "وسيفالوسبورين الجيل الأول والسيفاميسين."),
        "reason_en": ("Inducible chromosomal AmpC — intrinsic to aminopenicillins, "
                      "1st-gen cephalosporins and cephamycins."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 2",
    },
    {
        "id": "intr_pseudomonas",
        "organisms": ["pseudomonas aeruginosa"],
        "drugs": ["ampicillin", "amoxicillin", "cefazolin", "cephalothin",
                  "cefuroxime", "cefoxitin", "cefotaxime", "ceftriaxone",
                  "ertapenem", "tetracycline", "doxycycline", "tigecycline",
                  "trimethoprim", "chloramphenicol", "kanamycin", "nitrofurantoin",
                  "cephalexin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "cefixime",
                  "cefpodoxime",
                  "ceftibuten",
                  "erythromycin",
                  "clarithromycin",
                  "azithromycin",
                  "minocycline"
                  ],
        "exclude": ["tazobactam", "avibactam"],
        "reason_ar": ("P. aeruginosa مقاوم جوهرياً — لا تُبلَّغ هذه المضادات "
                      "حتى لو ظهرت حسّاسة. (Ceftazidime و Cefepime فقط من "
                      "السيفالوسبورينات لها فاعلية.)"),
        "reason_en": ("P. aeruginosa is intrinsically resistant — do not report these "
                      "even if they test susceptible. (Only ceftazidime and cefepime "
                      "among the cephalosporins are active.)"),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 3",
    },
    {
        "id": "intr_acinetobacter",
        "organisms": ["acinetobacter"],
        "drugs": ["ampicillin", "amoxicillin", "aztreonam", "ertapenem",
                  "trimethoprim", "fosfomycin", "chloramphenicol",
                  "cephalexin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "cefazolin",
                  "cefuroxime",
                  "cefoxitin",
                  "cefotaxime",
                  "ceftriaxone",
                  "nitrofurantoin"
                  ],
        # BUG FIXED: "clav" used to sit in this exclude list, which exempted
        # amoxicillin-clavulanate from the rule. That is backwards. Clavulanate
        # has NO useful activity against Acinetobacter, so amox-clav IS
        # intrinsically resistant and EUCAST lists it explicitly. Sulbactam is
        # the exception -- it has intrinsic anti-Acinetobacter activity of its
        # own -- so only "sulbactam" belongs here. Leaving "clav" in made this
        # module contradict clinical_data.INTRINSIC_RESISTANCE, which correctly
        # bans amox-clav: the recommendation panel refused the drug while the QC
        # panel stayed silent about a Susceptible result for it.
        "exclude": ["sulbactam", "sulfamethoxazole", "sulphamethoxazol"],
        "reason_ar": ("Acinetobacter مقاوم جوهرياً — بما في ذلك "
                      "Amoxicillin/Clavulanate (الـ clavulanate بلا فاعلية هنا). "
                      "(ملاحظة: Ampicillin/Sulbactam استثناء — الـ sulbactam نفسه "
                      "فعّال ضد Acinetobacter.)"),
        "reason_en": ("Acinetobacter is intrinsically resistant — "
                      "amoxicillin-clavulanate included (clavulanate adds nothing "
                      "here). (Note: ampicillin-sulbactam is an exception — "
                      "sulbactam itself has intrinsic activity against ",
                      "Acinetobacter.)"),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 3",
    },
    {
        "id": "intr_stenotrophomonas",
        "organisms": ["stenotrophomonas"],
        "drugs": ["imipenem", "meropenem", "ertapenem", "gentamicin", "amikacin",
                  "tobramycin", "ampicillin", "amoxicillin", "cefotaxime",
                  "ceftriaxone", "aztreonam", "piperacillin",
                  "cephalexin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "cefazolin",
                  "cefuroxime",
                  "ceftazidime",
                  "cefepime",
                  "ciprofloxacin",
                  "norfloxacin",
                  "ofloxacin",
                  "fosfomycin",
                  "nitrofurantoin"
                  ],
        "exclude": [],
        "reason_ar": ("S. maltophilia مقاوم جوهرياً لمعظم البيتا-لاكتام "
                      "(بما فيها الكاربابينيمات — L1 metallo-β-lactamase) "
                      "والأمينوجلايكوسيدات. الخيار المعتمد: Trimethoprim/Sulfamethoxazole."),
        "reason_en": ("S. maltophilia is intrinsically resistant to most beta-lactams "
                      "(carbapenems included — L1 metallo-beta-lactamase) and to "
                      "aminoglycosides. The established option is "
                      "trimethoprim-sulfamethoxazole."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 3",
    },
    {
        "id": "intr_gram_pos_gram_neg_agents",
        "organisms": ["staphylococcus", "staph", "streptococc", "pneumoniae",
                      "enterococc", "vre", "listeria", "corynebacterium"],
        "drugs": ["aztreonam", "colistin", "polymyxin", "nalidixic acid",
                  "temocillin", "fusidic acid"],
        "exclude": [],
        "reason_ar": "إيجابيات الجرام مقاومة جوهرياً لمضادات سالبة الجرام هذه (aztreonam · colistin/polymyxin · nalidixic acid · temocillin).",
        "reason_en": "Gram-positive bacteria are expected resistant to these Gram-negative agents (aztreonam, colistin/polymyxin, nalidixic acid, temocillin).",
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 4",
    },
    {
        # A result of "Vancomycin S" on an isolate reported as VRE is not an
        # expected-phenotype question -- it is a direct contradiction between
        # the identification and the susceptibility result. Exactly the case
        # EUCAST means by "a result which contradicts the expected phenotype
        # should be viewed with suspicion": either the ID or the AST is wrong,
        # and the isolate should be re-checked before the report leaves the lab.
        "id": "intr_vre_glycopeptide_contradiction",
        "organisms": ["vre"],
        "drugs": ["vancomycin", "teicoplanin"],
        "exclude": [],
        "reason_ar": ("تناقض: العزلة مُبلَّغة كـ VRE (مقاومة للجلايكوببتيد) "
                      "بينما النتيجة تقول حسّاسة. راجع التعريف والنتيجة معاً "
                      "قبل إصدار التقرير — أحدهما خطأ."),
        "reason_en": ("Contradiction: the isolate is reported as VRE "
                      "(glycopeptide-resistant) while the result reads "
                      "susceptible. Re-check the identification and the AST "
                      "together before releasing — one of them is wrong."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023) · CLSI M100 Ed36",
    },
    {
        "id": "intr_enterococcus_cephalosporins",
        "organisms": ["enterococc", "vre"],
        "drugs": ["cephalexin", "cefazolin", "cefuroxime", "cefoxitin",
                  "cefotaxime", "ceftriaxone", "ceftazidime", "cefepime",
                  "cefoperazone", "clindamycin", "fusidic acid", "aztreonam",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "cefixime",
                  "cefpodoxime",
                  "ceftibuten"
                  ],
        "exclude": [],
        "reason_ar": ("الـ Enterococci مقاومة جوهرياً لكل السيفالوسبورينات "
                      "و clindamycin و aztreonam — لا تُبلَّغ أبداً كحسّاسة."),
        "reason_en": ("Enterococci are intrinsically resistant to ALL cephalosporins, "
                      "clindamycin and aztreonam — never report as susceptible."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 4 · CLSI M100 App. B",
    },
    {
        "id": "intr_enterococcus_sxt_invivo",
        "organisms": ["enterococc", "vre"],
        "drugs": ["trimethoprim", "sulfamethoxazole", "sulphamethoxazol",
                  "cotrimoxazole", "co-trimoxazole"],
        "exclude": [],
        "reason_ar": ("Enterococci تظهر حسّاسة لـ TMP-SMX في المزرعة لكنها "
                      "**غير فعّالة سريرياً** — البكتيريا تستهلك الفولات الجاهز "
                      "من الوسط وتتخطى المسار المُثبَّط. لا تُبلَّغ."),
        "reason_en": ("Enterococci test susceptible to TMP-SMX in vitro but it is "
                      "NOT clinically effective — they take up exogenous folate and "
                      "bypass the blocked pathway. Do not report."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 4 · CLSI M100 App. B",
    },
    {
        # Missing rule found by the cross-table scenario matrix: clinical_data
        # lists Gentamicin/Tobramycin as intrinsic for streptococci and
        # enterococci, but ast_reportability had no matching row, so a lab that
        # reported "Gentamicin S" on a Strep or Enterococcus panel got no QC
        # flag at all. Low-level aminoglycoside resistance is a species trait
        # (poor uptake across the cell wall); the drug is only ever used in
        # SYNERGY with a cell-wall agent, and only when HLAR screening is
        # negative. A bare "S" is therefore uninterpretable and must not stand.
        "id": "intr_strep_entero_aminoglycoside_mono",
        "organisms": ["streptococc", "enterococc", "vre"],
        "drugs": ["gentamicin", "tobramycin", "amikacin", "netilmicin",
                  "kanamycin", "streptomycin"],
        "exclude": [],
        "reason_ar": ("المكوّرات السبحية والمعوية مقاومة جوهرياً للأمينوجلايكوزيدات "
                      "كعلاج مفرد (ضعف النفاذ عبر جدار الخلية). تُستخدم فقط "
                      "بالتآزر مع مضاد يعمل على جدار الخلية (بنسلين/أمبيسيللين/"
                      "vancomycin) وبعد فحص HLAR. نتيجة S منفردة غير قابلة للتفسير "
                      "ولا تُبلَّغ — بلّغ فحص HLAR (Gentamicin 120µg / "
                      "Streptomycin 300µg) بدلاً منها."),
        "reason_en": ("Streptococci and enterococci are intrinsically resistant to "
                      "aminoglycoside MONOTHERAPY (poor cell-wall uptake). These "
                      "agents are used only in synergy with a cell-wall-active drug ",
                      "(penicillin/ampicillin/vancomycin) and only when HLAR "
                      "screening is negative. A standalone S is uninterpretable and "
                      "must not be reported — report the HLAR screen "
                      "(gentamicin 120µg / streptomycin 300µg) instead."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Tables 4-5 · CLSI M100 Ed36",
    },
    {
        "id": "intr_listeria_cephalosporins",
        "organisms": ["listeria"],
        "drugs": ["cephalexin", "cefazolin", "cefuroxime", "cefoxitin",
                  "cefotaxime", "ceftriaxone", "ceftazidime", "cefepime",
                  "cefoperazone", "fosfomycin",
                  "cefadroxil",
                  "cephradine",
                  "cefaclor",
                  "aztreonam"
                  ],
        "exclude": [],
        "reason_ar": ("Listeria monocytogenes مقاومة جوهرياً لكل السيفالوسبورينات — "
                      "سبب معروف لفشل علاج التهاب السحايا. الخيار: Ampicillin."),
        "reason_en": ("Listeria monocytogenes is intrinsically resistant to ALL "
                      "cephalosporins — a known cause of meningitis treatment "
                      "failure. The option is ampicillin."),
        "reference": "EUCAST Expected Resistant Phenotypes v1.2 (2023), Table 4",
    },
]


# ── 2. NO BREAKPOINTS ────────────────────────────────────────────────────────
# Distinct from intrinsic resistance: the drug may well work. The point is that
# nobody has published a validated zone/MIC cut-off for this pairing, so the
# S/I/R printed against it was produced by reading the zone against a table that
# does not cover it — or against nothing at all.
NO_BREAKPOINT_RULES: List[Dict[str, Any]] = [
    {
        "id": "nobp_azithromycin_enterobacterales",
        "organisms": ENTEROBACTERALES,
        "not_organisms": ["salmonella", "shigella"],
        "drugs": ["azithromycin"],
        "exclude": [],
        "reason_ar": ("لا توجد breakpoints للأزيثرومايسين مع الـ Enterobacterales "
                      "عدا Salmonella Typhi و Shigella. أي S/I/R هنا غير قابل "
                      "للتفسير — لا يوجد جدول يُقرأ عليه."),
        "reason_en": ("No azithromycin breakpoints exist for Enterobacterales other "
                      "than Salmonella Typhi and Shigella. Any S/I/R here is "
                      "uninterpretable — there is no table to read the zone against."),
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
        "id": "nobp_tigecycline_proteae",
        "organisms": ["proteus", "morganella", "providencia"],
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

    for iss in issues:
        if iss["category"] == "intrinsic":
            # Reported R on an intrinsically resistant drug is the right answer
            # for the wrong reason — no patient is harmed, but the disk should
            # not be on the plate.
            if all(v == "R" for v in iss["results"].values()):
                iss["severity"] = "warning"
                iss["misreported"] = False
            else:
                iss["misreported"] = True
    return issues


def format_issue(issue: Dict[str, Any], lang: str = "ar") -> Dict[str, str]:
    """Render one reportability issue into the {message, fix} shape run_ast_qc uses."""
    drugs = " · ".join(f'{d} [{issue["results"][d]}]' for d in issue["drugs"])
    reason = issue["reason_ar"] if lang == "ar" else issue["reason_en"]

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
