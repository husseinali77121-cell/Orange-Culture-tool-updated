"""Free-text alerts that accompany the lists (interactions, hepatic, notes).

An alert never moves a drug between lists; it is extra information for a drug
that is still on the table (alerts are not raised for a drug that is already
out on resistance or intrinsic inactivity).
"""
from __future__ import annotations

from typing import List

from .context import Context, DrugCase


def drug_alerts(ctx: Context, d: DrugCase) -> List[str]:
    out: List[str] = []
    info = d.info
    for med in ctx.current_meds:
        if med in info.get("interacts_with", []):
            out.append(f"⚡ تعارض: {d.name} مع {med}")
    if ctx.is_hepatic and info.get("hepatic_caution"):
        out.append(f"🏥 تحذير كبدي: {d.name} — يحتاج متابعة أو تعديل حسب الحالة.")

    if (d.name == "Fusidic acid" and info.get("no_monotherapy_systemic")
            and ctx.specimen in ("blood", "csf", "sputum", "respiratory")):
        out.append("⚠️ Fusidic acid: لا يُستخدم منفرداً في العدوى الجهازية — "
                   "combination إلزامي (+ Rifampicin أو + Vancomycin). مقاومة سريعة.")

    if d.name == "Oxacillin" and d.sir == "S" and ctx.specimen == "blood":
        out.append("ℹ️ Oxacillin=S (MSSA confirmed). Cefazolin مفضل على Oxacillin "
                   "في bacteremia (أقل interstitial nephritis). IDSA 2024.")

    if d.name in ("Ampicillin", "Amoxicillin") and ctx.organism.is_("e_faecium"):
        if d.sir == "S":
            out.append("⚠️ E. faecium + Ampicillin=S: نادر (معظم عزلات faecium مقاومة "
                       "مكتسبة للـ Ampicillin) — تأكد من صحة النتيجة قبل الاعتماد عليها.")
        elif d.sir is None:
            out.append("ℹ️ E. faecium: مقاومة الـ Ampicillin مكتسبة وشائعة جداً — لا تفترض "
                       "فعاليته دون اختبار؛ فكّر في Vancomycin/Linezolid حسب الحساسية.")
    return out
