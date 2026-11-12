"""AST quality control: reportability, internal consistency, phenotype rules, confidence."""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from ast_consistency import QC_RULE_OVERRIDES, check_consistency
from ast_consistency import format_issue as format_consistency_issue
from ast_reportability import check_reportability, format_issue
from clinical_data import AST_QC_RULES
from .organisms import matches_any
from .sir import normalize_sir_map

logger = logging.getLogger("orange_lab.engines")

def run_ast_qc(organism: str, sir_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Check the reported S/I/R panel and return every problem found.

    Two independent passes:

      1. REPORTABILITY — should this agent be on this organism's panel at all?
         Intrinsic resistance, agents with no breakpoints for this organism, and
         agents that test susceptible but fail in vivo. This runs FIRST because
         a result that should never have been produced is a bigger problem than
         one that merely contradicts another result, and because the intrinsic
         data was already in the codebase (INTRINSIC_RESISTANCE) being used
         SILENTLY by _remove_intrinsic_resistance() to clean the MDR count —
         known to the software, never told to the user.

      2. INTERNAL CONSISTENCY — do the results contradict each other?
         (AST_QC_RULES: cephalosporin discrepancies, carbapenem logic, and so on.)
    """
    sir_map = normalize_sir_map(sir_map)
    if not sir_map:
        return []
    organism = organism or ""
    issues = []

    # ── Pass 1: reportability (see ast_reportability.py) ──────────────────────
    for _rep in check_reportability(organism, sir_map):
        _fmt = format_issue(_rep, lang="ar")
        issues.append({
            "id":        _rep["id"],
            "severity":  _rep["severity"],
            "message":   _fmt["message"],
            "fix":       _fmt["fix"],
            "category":  _rep["category"],
            "drugs":     _rep["drugs"],
            "reference": _rep["reference"],
        })

    # ── Pass 2: internal consistency — do the results contradict each other?
    # Ahead of the phenotype rules on purpose: an ESBL/AmpC pattern read off a
    # panel that contradicts itself is an interpretation of noise. If
    # cefotaxime and ceftriaxone disagree, "possible ESBL" is the wrong headline
    # — "repeat the test" is.
    for _dis in check_consistency(organism, sir_map):
        _fmt = format_consistency_issue(_dis, lang="ar")
        issues.append({
            "id":        _dis["id"],
            "severity":  _dis["severity"],
            "message":   _fmt["message"],
            "fix":       _fmt["fix"],
            "category":  _dis["category"],
            "drugs":     _dis["drugs"],
            "reference": _dis["reference"],
        })

    # ── Pass 3: phenotype rules (AST_QC_RULES, clinical_data.py) ─────────────
    for rule in AST_QC_RULES:
        # تحقق من الكائن (لو فاضية → ينطبق على الكل)
        if rule["organisms"] and not matches_any(organism, rule["organisms"]):
            continue
        # `not_organisms`: explicit exclusions (e.g. species intrinsically
        # resistant to the agent the rule is about).
        if rule.get("not_organisms") and matches_any(organism, rule["not_organisms"]):
            continue
        try:
            if rule["condition"](sir_map):
                # ORDER MATTERS. The override is picked FIRST and the placeholders
                # are filled AFTERWARDS. Doing it the other way round (the old
                # code) meant the override's static text replaced the message that
                # had just been correctly populated with the real drug names, so
                # QC006 always printed the two drugs hardcoded in the override —
                # even when neither was on the panel. Any override text must
                # therefore carry the same {drugs}/{r_drug} placeholders as the
                # rule it overrides (see QC_RULE_OVERRIDES in ast_consistency.py).
                _ovr = QC_RULE_OVERRIDES.get(rule["id"])
                if _ovr:
                    logger.info("QC rule %s served from override layer "
                                "(fix at source in clinical_data.py)", rule["id"])
                _msg = (_ovr or {}).get("message", rule["message"])
                _fix = (_ovr or {}).get("fix",     rule["fix"])
                # استبدال {r_drug} (بـ str.replace وليس format) بالدواء المقاوم الفعلي
                if "trigger_r_fn" in rule and "{r_drug}" in _msg:
                    _r_trig = rule["trigger_r_fn"](sir_map)
                    _r_str  = " / ".join(_r_trig) if _r_trig else "Cephalosporin"
                    _msg = _msg.replace("{r_drug}", _r_str)
                # ثم استبدال {drugs} باسم الدواء (أو الأدوية) الحساس المسبب للتناقض
                if "trigger_fn" in rule and "{drugs}" in _msg:
                    _triggered = rule["trigger_fn"](sir_map)
                    _drugs_str = " / ".join(_triggered) if _triggered else "Cephalosporin"
                    _msg = _msg.replace("{drugs}", _drugs_str)
                issues.append({
                    "id":       rule["id"],
                    "severity": rule["severity"],
                    "message":  _msg,
                    "fix":      _fix,
                })
        except Exception as _exc:
            # لا تبلع الخطأ بصمت — قاعدة QC تعطّلت يجب أن تظهر في اللوج بوضوح
            # مع رقم القاعدة، وإلا يختفي عطل حقيقي (كما حدث مع KeyError في format).
            logger.warning("AST QC rule %s failed and was skipped: %s",
                           rule.get("id", "?"), _exc, exc_info=True)
            continue
    return issues

def compute_qa_confidence(
    qc_issues: List[Dict[str, Any]],
    sir_map: Dict[str, str],
    organism: str,
) -> Dict[str, Any]:
    """
    Confidence Score للتوصية العلاجية — بناءً على:
      1. عدد وشدة الـ QA issues المكتشفة (errors تخفض أكتر من warnings)
      2. اكتمال الـ AST panel (عدد المضادات المختبرة)
    يرجع: {level: High/Moderate/Low, score: 0-100, reasons: [...]}
    """
    score = 100
    reasons = []

    n_errors   = sum(1 for i in qc_issues if i.get("severity") == "error")
    n_warnings = sum(1 for i in qc_issues if i.get("severity") == "warning")

    if n_errors:
        score -= n_errors * 30
        reasons.append(f"{n_errors} تناقض حرج (error) في نتائج الـ AST")
    if n_warnings:
        score -= n_warnings * 12
        reasons.append(f"{n_warnings} ملاحظة (warning) تستدعي المراجعة")

    # اكتمال الـ AST panel
    n_tested = sum(1 for v in normalize_sir_map(sir_map).values() if v in ("S", "I", "R"))
    if n_tested == 0:
        score -= 50
        reasons.append("لا توجد نتائج AST مدخلة")
    elif n_tested <= 2:
        score -= 35
        reasons.append(f"عدد المضادات المختبرة قليل جداً ({n_tested}) — لا يكفي لتوصية موثوقة")
    elif n_tested < 5:
        score -= 20
        reasons.append(f"عدد المضادات المختبرة قليل ({n_tested}) — قد لا يغطي كل الخيارات العلاجية")
    elif n_tested < 8:
        score -= 8
        reasons.append(f"عدد المضادات المختبرة محدود ({n_tested})")

    score = max(0, min(100, score))

    if score >= 80:
        level, icon, color = "High Confidence", "🟢", "#1e8449"
    elif score >= 50:
        level, icon, color = "Moderate Confidence", "🟡", "#b7770d"
    else:
        level, icon, color = "Low Confidence", "🔴", "#922b21"

    if not reasons:
        reasons.append("لا توجد مشاكل مكتشفة — تقرير AST مكتمل ومتسق")

    return {
        "level": level, "icon": icon, "color": color,
        "score": score, "reasons": reasons,
        "n_errors": n_errors, "n_warnings": n_warnings, "n_tested": n_tested,
    }
