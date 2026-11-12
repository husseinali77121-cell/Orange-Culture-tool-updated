"""Rules about whether the drug reaches the site of infection."""
from __future__ import annotations

from typing import Optional

from .. import drugs as D
from .context import Context, DrugCase
from .findings import Finding, ban


def rule_urine_only(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """Nitrofurantoin / oral Fosfomycin / Norfloxacin reach therapeutic levels
    only in urine. The specimen is classified by the shared classifier, so
    "MSU" / "CSU" / "Urinary catheter sample" are urine here exactly as they
    are everywhere else (a bare `"urine" in name` test used to ban
    nitrofurantoin for an MSU)."""
    if d.name not in D.URINE_ONLY or ctx.specimen == "urine":
        return None
    if ctx.specimen == "stool":
        if d.name in D.URINE_ONLY_EXCEPT_GI:
            return None
        detail = ("عامل بولي فقط — لا يصل لتركيز علاجي داخل الأمعاء؛ "
                  "غير مناسب لعدوى الجهاز الهضمي.")
        detail_en = ("Urinary agent only — does not reach therapeutic levels in "
                     "the gut; not appropriate for gastrointestinal infection.")
    else:
        detail = ("عامل بولي فقط — لا يحقق تركيزاً علاجياً في الدم أو الأنسجة؛ "
                  "غير مناسب للعدوى الجهازية (دم / رئة / جرح / سائل نخاعي). "
                  "(ملاحظة: Fosfomycin الوريدي استثناء غير متوفر في هذه القائمة.)")
        detail_en = ("Urinary agent only — does not reach therapeutic levels in "
                     "blood or tissue; not appropriate for systemic infection "
                     "(blood / lung / wound / CSF). (IV fosfomycin is an "
                     "exception that is not in this formulary.)")
    return ban("urine_only", "specimen",
               "عامل بولي فقط — غير مناسب لهذه العينة.", detail,
               "Urinary agent only - not appropriate for this specimen.", detail_en)
