"""Orange Lab — AST internal-consistency rules.

Answers a third question, distinct from both of its neighbours:

    ast_reportability : "should this agent be on this organism's panel?"
    ast_consistency   : "do these results contradict EACH OTHER?"   <- here
    AST_QC_RULES      : phenotype-level checks (ESBL/AmpC/carbapenemase logic)

Two kinds of contradiction, and the distinction decides the severity:

  * EQUIVALENCE — two agents so alike against this organism that they must give
    the same answer. Cefotaxime and ceftriaxone share MIC breakpoints and are
    hydrolysed near-identically by every common ESBL; one S and one R is not a
    resistance pattern, it is a laboratory error. Someone will act on whichever
    one reads S.

  * HIERARCHY — a logical impossibility. Adding a beta-lactamase inhibitor
    cannot make a drug work LESS well, so ampicillin-S with amox-clav-R is not
    a phenotype anyone has ever described.

What is deliberately NOT here matters as much as what is. Ceftazidime is a
third-generation cephalosporin, but CTX-M enzymes — the dominant ESBL family in
Egypt — hydrolyse cefotaxime far more efficiently than ceftazidime. So
cefotaxime-R with ceftazidime-S is a textbook CTX-M phenotype, NOT a
discrepancy, and flagging it would be flagging the single most common real ESBL
in the lab's population. Likewise ertapenem-R with meropenem-S is ordinary
OXA-48 or porin loss; only the REVERSE (meropenem-R, ertapenem-S) is impossible,
because ertapenem is the more labile of the two.

Separate module for the same reasons as ast_reportability: pure data plus a pure
function, testable without the clinical_data import wall, and every rule carries
the document it comes from so a microbiologist can overrule it.

Sources (verify against current editions):
  * EUCAST Clinical Breakpoint Tables v16.0 (valid 2026-01-01) — Enterobacterales
  * CLSI M100 Ed36 (2026) — Tables 2A/2B and the tetracycline-class predictive note
  * EUCAST Expert Rules and Intrinsic Resistance v3.3 (2021-10-18)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_NORM = re.compile(r"[^a-z0-9]")

ENTEROBACTERALES = [
    "escherichia", "e. coli", "e.coli", "klebsiella", "enterobacter",
    "citrobacter", "serratia", "proteus", "morganella", "providencia",
    "salmonella", "shigella", "hafnia", "pantoea", "raoultella", "yersinia",
]

# Imipenem is intrinsically less active against these, so an imipenem outlier is
# expected rather than suspicious.
_IMI_TOLERANT = ["proteus", "morganella", "providencia"]


def _nk(s: str) -> str:
    return _NORM.sub("", (s or "").lower())


def _org_in(organism: str, names: List[str]) -> bool:
    o = (organism or "").lower()
    return any(n in o for n in names)


def _find(sir_map: Dict[str, str], needle: str,
          exclude: Optional[List[str]] = None) -> Optional[str]:
    """First panel entry matching `needle`, honouring `exclude`.

    `exclude` is what stops "piperacillin" from matching
    "Piperacillin + Tazobactam" — the whole point of the hierarchy rules is that
    those two are DIFFERENT drugs, and a naive substring match collapses them
    into one and then finds no contradiction anywhere.
    """
    n = _nk(needle)
    for drug in sir_map:
        d = _nk(drug)
        if n not in d:
            continue
        if exclude and any(_nk(x) in d for x in exclude):
            continue
        return drug
    return None


_INHIBITORS = ["clav", "sulbactam", "tazobactam", "avibactam", "vaborbactam",
               "relebactam"]


# ── 1. EQUIVALENCE ───────────────────────────────────────────────────────────
EQUIVALENCE_RULES: List[Dict[str, Any]] = [
    {
        "id": "equiv_ctx_cro",
        "organisms": ENTEROBACTERALES,
        "a": "cefotaxime", "a_exclude": _INHIBITORS,
        "b": "ceftriaxone", "b_exclude": _INHIBITORS,
        "reason_ar": ("Cefotaxime و Ceftriaxone سيفالوسبورينان من الجيل الثالث "
                      "بنفس الـ MIC breakpoints تماماً ضد الـ Enterobacterales، "
                      "وكل الـ ESBL الشائعة تحلّلهما بنفس الكفاءة تقريباً. "
                      "استحالة أن يكون أحدهما S والآخر R على نفس العزلة."),
        "reason_en": ("Cefotaxime and ceftriaxone are third-generation "
                      "cephalosporins with identical MIC breakpoints against "
                      "Enterobacterales, and every common ESBL hydrolyses them "
                      "near-identically. One S and one R on the same isolate is "
                      "not possible."),
        "fix_ar": ("أعِد اختبار القرصين على نفس اللقاح. راجع: كثافة اللقاح "
                   "(0.5 McFarland) · صلاحية الأقراص وتخزينها · قياس الـ zone "
                   "(الحافة لا الظل) · نقاء المستعمرة. لا تُبلِّغ اللوحة قبل الحل."),
        "fix_en": ("Repeat both disks from the same inoculum. Check: inoculum "
                   "density (0.5 McFarland), disk potency and storage, zone edge "
                   "reading, colony purity. Do not report until resolved."),
        "reference": "EUCAST Breakpoint Tables v16.0 — Enterobacterales · CLSI M100 Ed36 Table 2A",
    },
]


# ── 2. HIERARCHY ─────────────────────────────────────────────────────────────
# `worse` is the agent that CANNOT be less active than `better`.
HIERARCHY_RULES: List[Dict[str, Any]] = [
    {
        "id": "hier_amp_vs_amc",
        "organisms": ENTEROBACTERALES,
        "better": "ampicillin", "better_exclude": _INHIBITORS,
        "worse": "amoxicillin", "worse_needle_extra": "clav",
        "reason_ar": ("Ampicillin حسّاس بينما Amoxicillin/Clavulanate مقاوم — "
                      "غير منطقي: إضافة مثبّط بيتا-لاكتاماز لا يمكن أن تقلّل "
                      "فاعلية الدواء."),
        "reason_en": ("Ampicillin susceptible while amoxicillin-clavulanate is "
                      "resistant is not possible: adding a beta-lactamase "
                      "inhibitor cannot reduce activity."),
        "fix_ar": "أعِد اختبار القرصين. غالباً خطأ قراءة أو قرص تالف.",
        "fix_en": "Repeat both disks. Usually a reading error or a degraded disk.",
        "reference": "EUCAST Expert Rules v3.3 — beta-lactam hierarchy",
    },
    {
        "id": "hier_pip_vs_tzp",
        "organisms": [],
        "better": "piperacillin", "better_exclude": _INHIBITORS,
        "worse": "piperacillin", "worse_needle_extra": "tazobactam",
        "reason_ar": ("Piperacillin حسّاس بينما Piperacillin/Tazobactam مقاوم — "
                      "غير منطقي لنفس السبب: المثبّط لا يقلّل الفاعلية."),
        "reason_en": ("Piperacillin susceptible while piperacillin-tazobactam is "
                      "resistant is not possible — the inhibitor cannot reduce "
                      "activity."),
        "fix_ar": "أعِد اختبار القرصين.",
        "fix_en": "Repeat both disks.",
        "reference": "EUCAST Expert Rules v3.3 — beta-lactam hierarchy",
    },
    {
        "id": "hier_mem_vs_etp",
        "organisms": ENTEROBACTERALES,
        "better": "ertapenem", "better_exclude": [],
        "worse": "meropenem", "worse_needle_extra": "",
        "reason_ar": ("Meropenem مقاوم بينما Ertapenem حسّاس — الاتجاه معكوس. "
                      "الإرتابينيم هو الأضعف أمام آليات مقاومة الكاربابينيم، "
                      "فالمعتاد هو العكس (Ertapenem-R مع Meropenem-S = "
                      "OXA-48 أو فقد بورين، وهذا طبيعي)."),
        "reason_en": ("Meropenem resistant with ertapenem susceptible is the wrong "
                      "way round. Ertapenem is the most labile carbapenem, so the "
                      "usual pattern is the reverse (ertapenem-R with meropenem-S "
                      "= OXA-48 or porin loss, which is normal)."),
        "fix_ar": "أعِد اختبار الكاربابينيمات وأكّد بـ MIC.",
        "fix_en": "Repeat the carbapenems and confirm with an MIC method.",
        "reference": "EUCAST Guidance on detection of resistance mechanisms · CLSI M100 Ed36",
    },
    {
        "id": "hier_tet_vs_doxy",
        "organisms": [],
        "better": "tetracycline", "better_exclude": ["oxytetracycline"],
        "worse": "doxycycline", "worse_needle_extra": "",
        "reason_ar": ("Tetracycline حسّاس بينما Doxycycline مقاوم — يخالف قاعدة "
                      "CLSI التنبّؤية: العزلة الحسّاسة للتتراسيكلين تُعتبر حسّاسة "
                      "للدوكسيسيكلين والمينوسيكلين. (العكس مسموح: Tetracycline-R "
                      "لا يتنبّأ بمقاومة الدوكسيسيكلين — يجب اختباره منفصلاً.)"),
        "reason_en": ("Tetracycline susceptible with doxycycline resistant "
                      "contradicts the CLSI predictive rule: an isolate "
                      "susceptible to tetracycline is considered susceptible to "
                      "doxycycline and minocycline. (The reverse IS allowed — "
                      "tetracycline-R does not predict doxycycline-R, which is why "
                      "doxycycline must be tested separately.)"),
        "fix_ar": "أعِد اختبار القرصين.",
        "fix_en": "Repeat both disks.",
        "reference": "CLSI M100 Ed36 — tetracycline-class predictive note",
    },
]


_RANK = {"S": 0, "I": 1, "R": 2}


def _worse_than(a: Optional[str], b: Optional[str]) -> bool:
    """True when result `a` is categorically worse than result `b`."""
    if a not in _RANK or b not in _RANK:
        return False
    return _RANK[a] > _RANK[b]


def check_consistency(organism: str, sir_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Find results on this panel that contradict each other.

    Every issue is an `error`, not a warning: unlike a missing breakpoint (which
    produces a meaningless result), a discrepancy means one of two printed
    results is actively WRONG — and there is no way to tell from the report
    which one. A clinician reading the S has no signal that anything is amiss.
    """
    if not sir_map or not organism:
        return []
    issues: List[Dict[str, Any]] = []

    for rule in EQUIVALENCE_RULES:
        if rule["organisms"] and not _org_in(organism, rule["organisms"]):
            continue
        da = _find(sir_map, rule["a"], rule.get("a_exclude"))
        db = _find(sir_map, rule["b"], rule.get("b_exclude"))
        if not da or not db:
            continue
        va, vb = sir_map[da], sir_map[db]
        # S vs R only. S vs I is a one-step drift that ordinary technical
        # variation explains — flagging it would bury the real signal.
        if {va, vb} == {"S", "R"}:
            issues.append({
                "id": f'{rule["id"]}:{da}|{db}',
                "category": "discrepancy",
                "severity": "error",
                "drugs": [da, db],
                "results": {da: va, db: vb},
                "reason_ar": rule["reason_ar"], "reason_en": rule["reason_en"],
                "fix_ar": rule["fix_ar"], "fix_en": rule["fix_en"],
                "reference": rule["reference"],
            })

    for rule in HIERARCHY_RULES:
        if rule["organisms"] and not _org_in(organism, rule["organisms"]):
            continue
        d_better = _find(sir_map, rule["better"], rule.get("better_exclude"))
        extra = rule.get("worse_needle_extra") or ""
        if extra:
            d_worse = next((d for d in sir_map
                            if _nk(rule["worse"]) in _nk(d) and _nk(extra) in _nk(d)),
                           None)
        else:
            d_worse = _find(sir_map, rule["worse"], _INHIBITORS)
        if not d_better or not d_worse or d_better == d_worse:
            continue
        if rule["id"] == "hier_mem_vs_etp" and _org_in(organism, _IMI_TOLERANT):
            continue
        if _worse_than(sir_map[d_worse], sir_map[d_better]) and \
                sir_map[d_better] == "S" and sir_map[d_worse] == "R":
            issues.append({
                "id": f'{rule["id"]}:{d_better}|{d_worse}',
                "category": "discrepancy",
                "severity": "error",
                "drugs": [d_better, d_worse],
                "results": {d_better: sir_map[d_better], d_worse: sir_map[d_worse]},
                "reason_ar": rule["reason_ar"], "reason_en": rule["reason_en"],
                "fix_ar": rule["fix_ar"], "fix_en": rule["fix_en"],
                "reference": rule["reference"],
            })

    return issues


def format_issue(issue: Dict[str, Any], lang: str = "ar") -> Dict[str, str]:
    """Render one discrepancy into the {message, fix} shape run_ast_qc uses."""
    drugs = " ↔ ".join(f'{d} [{issue["results"][d]}]' for d in issue["drugs"])
    head = ("🔴 **تناقض في اللوحة — أعِد الاختبار** — " if lang == "ar"
            else "🔴 **Panel discrepancy — repeat testing** — ")
    reason = issue["reason_ar"] if lang == "ar" else issue["reason_en"]
    fix = issue["fix_ar"] if lang == "ar" else issue["fix_en"]
    return {
        "message": f"{head}**{drugs}** — {reason}",
        "fix": f"{fix}  \n📖 {issue['reference']}",
    }


# ── 3. Corrections to AST_QC_RULES that live in clinical_data.py ─────────────
# TEMPORARY. These override rules whose text is wrong at source. Fix
# clinical_data.py and delete the entry — an override layer that outlives its
# cause becomes a second, invisible source of truth.
QC_RULE_OVERRIDES: Dict[str, Dict[str, str]] = {
    # QC006 told the user to "avoid ALL cephalosporins even if S in the AST" and
    # attributed that to EUCAST 2026. EUCAST says the opposite in the v16.0
    # tables: the Enterobacterales cephalosporin breakpoints detect the
    # clinically important mechanisms, isolates that produce a beta-lactamase but
    # test susceptible are REPORTED AS TESTED, and the presence or absence of an
    # ESBL does not by itself change the categorisation. ESBL detection is for
    # infection control and surveillance. Editing susceptible cephalosporins to R
    # on ESBL detection is the pre-2017 practice, withdrawn.
    #
    # There IS a real clinical argument for avoiding cephalosporins in ESBL
    # bacteraemia (IDSA 2024; the MERINO trial) — but that is a PRESCRIBING
    # decision for the treating physician, not a LABORATORY REPORTING rule, and
    # it is not EUCAST's. The old text fused the two and mis-cited the result.
    "QC006": {
        "message": ("⚠️ **نمط يستدعي الانتباه** — Cefoperazone-S مع Cefotaxime-R: "
                    "قد يشير إلى ESBL أو إلى تباين تقني. "
                    "**راجع أولاً وجود تناقض بين سيفالوسبورينات الجيل الثالث** "
                    "(انظر تنبيهات التناقض أعلاه إن وُجدت)."),
        "fix": ("**الإبلاغ المعملي:** بلِّغ النتائج **كما هي**. EUCAST v16.0: "
                "الـ breakpoints الحالية تكتشف آليات المقاومة المهمة إكلينيكياً، "
                "ووجود ESBL من عدمه **لا يغيّر التصنيف** بذاته — اكتشاف الـ ESBL "
                "لأغراض مكافحة العدوى والترصّد. لا تُحوِّل سيفالوسبورين حسّاس "
                "إلى R (ممارسة ما قبل 2017، أُلغيت).  \n"
                "**القرار العلاجي (منفصل — للطبيب):** في تجرثم الدم بـ ESBL "
                "يُفضَّل الكاربابينيم على السيفالوسبورينات/pip-tazo حتى مع S — "
                "IDSA AMR 2024 (4th update) · تجربة MERINO (JAMA 2018).  \n"
                "📖 EUCAST Breakpoint Tables v16.0 — Enterobacterales, note on "
                "cephalosporin breakpoints and ESBL"),
    },
}
