"""Rules about the patient: age, kidneys, pregnancy."""
from __future__ import annotations

from typing import Optional

from clinical_data import CHILD_BAN_REASONS

from .. import drugs as D
from .context import Context, DrugCase
from .findings import Finding, ban, preg_caution, warn


def rule_child(ctx: Context, d: DrugCase) -> Optional[Finding]:
    if not (ctx.age < 18 and not d.info.get("child_safe", True)):
        return None
    if d.family == D.FLUOROQUINOLONE:
        return ban("child_fluoroquinolone", "child", "غير مناسب < 18 سنة.",
                   CHILD_BAN_REASONS["fluoroquinolone"],
                   "Not suitable under 18 years.",
                   "Fluoroquinolones may affect growth cartilage under 18 years. "
                   "Use only when no alternative exists, on specialist advice.")
    if d.family == D.TETRACYCLINE:
        # The cut-off is 8 years, not 18: from 8 the tooth-staining risk no
        # longer applies and tetracyclines are first-line for several infections.
        if ctx.age < 8:
            return ban("child_tetracycline", "child", "غير مناسب < 8 سنوات.",
                       CHILD_BAN_REASONS["tetracycline"],
                       "Not suitable under 8 years.",
                       "Tetracyclines deposit in developing bone and teeth and can "
                       "cause permanent tooth discolouration. Generally avoided "
                       "under 8 years.")
        return None
    return ban("child_not_preferred", "child", "غير مفضل للأطفال.",
               "يحتاج تقييم متخصص أو لا يُنصح به روتينياً لهذه الفئة العمرية.",
               "Not preferred in children.",
               "Needs specialist assessment or is not routinely recommended "
               "for this age group.")


def rule_nitrofurantoin_renal(ctx: Context, d: DrugCase) -> Optional[Finding]:
    limit = d.info.get("renal_limit", 45)
    if not (ctx.is_renal and d.name == "Nitrofurantoin" and ctx.cl_cr < limit):
        return None
    c = ctx.cl_cr
    return ban(
        "renal_nitrofurantoin", "renal",
        f"ممنوع — CrCl {c:.1f} < {limit} ml/min",
        f"CrCl = {c:.1f} مل/د — أقل من الحد المطلوب ({limit} مل/د). "
        "خطر عدم كفاءة علاجية + تراكم سمي (EMA/BNF).",
        f"Contraindicated - CrCl {c:.1f} < {limit} mL/min",
        f"CrCl = {c:.1f} mL/min, below the required threshold "
        f"({limit} mL/min). Risk of therapeutic failure plus toxic "
        f"accumulation (EMA/BNF).",
    )


def rule_renal_adjustment(ctx: Context, d: DrugCase) -> Optional[Finding]:
    limit = d.info.get("renal_limit", 0) or 0
    if not (ctx.is_renal and limit > 0 and ctx.cl_cr <= limit):
        return None
    note = d.info.get("renal_note", "") or ""
    ar = f"تعديل جرعة كلوي (CrCl {ctx.cl_cr:.1f} ≤ {limit} مل/د)" + (f" — {note}" if note else "")
    en = f"Renal dose adjustment required (CrCl {ctx.cl_cr:.1f} ≤ {limit} mL/min)"
    return warn("renal_adjustment", ar, en,
                f"تعديل جرعة كلوي (CrCl {ctx.cl_cr:.1f} ≤ {limit} مل/د)", en)


# ── pregnancy ─────────────────────────────────────────────────────────────
_PREG_TETRACYCLINE_AR = (
    "Tetracyclines (Doxycycline / Tetracycline / Minocycline / Tigecycline):\n"
    "تترسّب في عظام وأسنان الجنين → تصبغ دائم للأسنان وتثبيط نمو العظام.\n"
    "محظورة في كل مراحل الحمل (خاصة بعد الأسبوع 15).\n"
    "ACOG 2023 / BNF 2025: contraindication مطلقة.\n"
    "البديل: Azithromycin (atypicals) | Amoxicillin-Clavulanate | Cephalosporin.")
_PREG_TETRACYCLINE_EN = (
    "Tetracyclines (Doxycycline / Tetracycline / Minocycline / Tigecycline):\n"
    "Deposit in fetal bone and teeth, causing permanent tooth "
    "discolouration and inhibition of bone growth.\n"
    "Contraindicated throughout pregnancy, particularly after week 15.\n"
    "ACOG 2023 / BNF 2025: absolute contraindication.\n"
    "Alternatives: Azithromycin (atypicals) | Amoxicillin-Clavulanate | Cephalosporin.")


def _preg_ban(code: str, note: str) -> Finding:
    first = (note.splitlines() or ["⛔ ممنوع في الحمل."])[0]
    return ban(code, "pregnancy", first, note, "Contraindicated in pregnancy.")


def rule_pregnancy(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """Pregnancy safety. Class-level bans come first and do not depend on the
    drug's `preg_status` field, so a data-entry slip cannot let a tetracycline
    or an aminoglycoside through."""
    if not ctx.is_preg:
        return None
    info, status = d.info, d.info.get("preg_status")

    if d.family == D.TETRACYCLINE:
        return ban("preg_tetracycline", "pregnancy",
                   "⛔ ممنوع في الحمل — Tetracyclines.", _PREG_TETRACYCLINE_AR,
                   "Contraindicated in pregnancy - tetracyclines.", _PREG_TETRACYCLINE_EN)
    if d.family == D.AMINOGLYCOSIDE:
        return _preg_ban("preg_aminoglycoside", info.get("preg_note") or (
            "⛔ ممنوع في الحمل — Aminoglycosides.\n"
            "يعبر المشيمة → سُمية للأذن الجنينية (ototoxicity) → فقدان سمع دائم.\n"
            "FDA Category D / ACOG: contraindication."))
    if d.family == D.FOLATE and status == "Banned":
        return _preg_ban("preg_folate", info.get("preg_note") or (
            "⛔ ممنوع في الحمل — TMP/SMX.\n"
            "Trimethoprim: مضاد حمض الفوليك → neural tube defects (1st trim).\n"
            "Sulfonamides: تنافس bilirubin → kernicterus نووي (3rd trim).\n"
            "البديل: Nitrofurantoin (1st/2nd trim) | Fosfomycin | Cephalexin."))
    if d.name == "Clarithromycin":
        return _preg_ban("preg_clarithromycin", info.get("preg_note") or (
            "⛔ ممنوع في الحمل — Clarithromycin.\n"
            "ارتبط بتشوهات قلبية خلقية (JAMA 2019 cohort study).\n"
            "BNF 2025: تجنّب في الحمل.\n"
            "البديل الآمن: Azithromycin."))
    if status == "Banned":
        return _preg_ban("preg_banned", info.get("preg_note") or "⛔ ممنوع في الحمل.")

    if d.family == D.FLUOROQUINOLONE:
        return preg_caution("preg_fluoroquinolone", info.get("preg_note") or (
            "⚠️ Use with Caution — Fluoroquinolone في الحمل:\n"
            "الأدلة الحديثة (ENTIS 2024): خطر التشوهات أقل مما كان يُعتقد.\n"
            "لا يُستخدم كخط أول — فقط عند غياب البديل الأكثر أمانًا.\n"
            ">>> القرار النهائي للطبيب المعالج حصراً. <<<"))
    if d.name == "Nitrofurantoin":
        return preg_caution("preg_nitrofurantoin", info.get("preg_note") or (
            "⚠️ Nitrofurantoin — Use with Caution في الحمل:\n"
            "✅ مسموح في الـ 1st و 2nd trimester (ACOG 2023).\n"
            "⛔ تجنّب في الـ 3rd trimester وعند الـ term (≥36 أسبوع):\n"
            "   خطر hemolytic anemia جنينية (G6PD) ونيونيتل hemolysis.\n"
            "البديل في 3rd trim: Fosfomycin جرعة واحدة أو Cephalexin.\n"
            ">>> القرار النهائي للطبيب المعالج حسب الـ trimester. <<<"))
    if d.family == D.NITROIMIDAZOLE:
        return preg_caution("preg_nitroimidazole", info.get("preg_note") or (
            "⚠️ Metronidazole — Use with Caution:\n"
            "ACOG 2021: مقبول في كل trimesters عند الضرورة.\n"
            "يُفضل تجنبه في الـ 1st trimester إن وُجد بديل آمن.\n"
            ">>> القرار النهائي للطبيب المعالج حصراً. <<<"))
    # "Caution" is the same decision as "Warn" (it used to match no branch at
    # all, so Aztreonam was listed for a pregnant patient with no note).
    if status in ("Warn", "Caution"):
        return preg_caution("preg_physician_decision", info.get("preg_note") or (
            "⚠️ يُستخدم بحذر في الحمل — القرار للطبيب المعالج."))
    return None
