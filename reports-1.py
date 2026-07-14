# Auto-extracted: PDF / image report rendering — Orange Lab Microbiology CDSS
import io
import logging
import json
import re
import math
import time
import hashlib
from datetime import datetime, date
from difflib import SequenceMatcher
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("orange_lab.reports")

from abx_guidelines import (
    ABX_GUIDELINES,
)
from organism_profile import (
    ORGANISM_PROFILE,
)
from clinical_data import (
    MDR_INFO,
    RENAL_BAN_REASONS,
    get_commercial_name,
)
from clinical_engines import (
    annotate_regimen_note,
    classify_mdr,
    classify_specimen,
    get_renal_severity,
    predict_esbl,
    rank_sensitive_antibiotics,
)

# Optional rendering dependencies
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = ImageDraw = ImageFont = None

try:
    import weasyprint as _wp
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    _wp = None

try:
    import arabic_reshaper as _arabic_reshaper_mod
    from bidi.algorithm import get_display as _bidi_display
    ARABIC_SUPPORT = True
except ImportError:
    ARABIC_SUPPORT = False
    _arabic_reshaper_mod = None
    _bidi_display = None

def _fmt_age(age: Any, unit: str = "yrs") -> str:
    """Human-readable age. Infants (<1yr) are shown in months so a fractional
    age like 0.5 prints as '6 months' rather than '0.5 yrs'/'0 yrs'."""
    try:
        a = float(age)
    except (TypeError, ValueError):
        return f"{age} {unit}"
    if 0 < a < 1:
        m = max(1, round(a * 12))
        return f"{m} month{'s' if m != 1 else ''}"
    return f"{int(round(a))} {unit}"


def _draw_rbox(draw: Any, box: tuple, bg: tuple, bd: tuple,
               radius: int = 14, width: int = 3) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=bg, outline=bd, width=width)

def _tw(draw: Any, text: str, font: Any) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception as _exc:
        logger.debug("suppressed exception: %s", _exc)
        return len(text) * (font.size if hasattr(font, "size") else 8)

def _fh(font: Any) -> int:
    return font.size if hasattr(font, "size") else 14

def _draw_text_wrap(draw: Any, x: float, y: float, text: str,
                    font: Any, fill: tuple, max_w: float,
                    line_gap: int = 5) -> float:
    words = text.split()
    lines: List[str] = []
    cur   = ""
    for w in words:
        trial = (cur + " " + w).strip()
        if _tw(draw, trial, font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    lh = _fh(font) + line_gap
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        y += lh
    return y

def _score_color(score: int) -> str:
    if score >= 75: return "#922b21"
    if score >= 50: return "#b7770d"
    if score >= 30: return "#e67e22"
    return "#1e8449"

def _esc(text: str) -> str:
    """HTML-escape a string."""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))

def generate_qa_report_pdf(
    organism: str,
    specimen: str,
    sir_map: Dict[str, str],
    qc_issues: List[Dict[str, Any]],
    confidence: Dict[str, Any],
    microbiologist: str = "",
    lab_id: str = "",
    patient_ref: str = "",
) -> Optional[bytes]:
    """
    تقرير AST-QA منفصل تماماً عن تقرير الطبيب — للأرشفة الداخلية ومراجعة الجودة
    من قِبل الميكروبيولوجي فقط. لا يُعرض ولا يُرسل للطبيب المعالج.
    """
    if not WEASYPRINT_AVAILABLE or _wp is None:
        return None

    _now = datetime.now().strftime("%Y-%m-%d %H:%M")
    H: List[str] = []
    H.append("""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page { size: A4; margin: 12mm 14mm; }
body { font-family: 'Segoe UI', Tahoma, Arial, sans-serif; color:#1a1a2e; font-size:10pt; }
.hdr { border-bottom:2px solid #6e2fa0; padding-bottom:3mm; margin-bottom:4mm; }
.hdr-title { font-size:16pt; font-weight:bold; color:#6e2fa0; }
.hdr-sub { font-size:9pt; color:#888; margin-top:1mm; }
.meta-grid { display:flex; justify-content:space-between; font-size:9pt; margin-bottom:4mm;
             background:#f7f5fb; padding:2.5mm 3mm; border-radius:2mm; }
.sec-ttl { font-size:11pt; font-weight:bold; color:#6e2fa0; border-bottom:1px solid #ddd;
           padding-bottom:1mm; margin:4mm 0 2mm 0; }
.conf-box { padding:3mm; border-radius:2mm; margin-bottom:4mm; }
.issue-row { padding:2mm 3mm; margin:1.5mm 0; border-radius:1.5mm; font-size:9pt; line-height:1.5; }
.issue-error { background:#fdf2f2; border-left:3px solid #922b21; }
.issue-warning { background:#fef9e7; border-left:3px solid #b7770d; }
.ast-table { width:100%; border-collapse:collapse; font-size:8.5pt; margin-top:2mm; }
.ast-table th { background:#6e2fa0; color:#fff; padding:1.5mm 2mm; text-align:left; }
.ast-table td { padding:1.2mm 2mm; border-bottom:1px solid #eee; }
.sir-S { color:#1e8449; font-weight:bold; }
.sir-I { color:#b7770d; font-weight:bold; }
.sir-R { color:#922b21; font-weight:bold; }
.footer { margin-top:6mm; padding-top:2mm; border-top:1px solid #ddd; font-size:7.5pt; color:#888; }
.confidential { background:#fdf2f2; color:#922b21; font-weight:bold; text-align:center;
                padding:1.5mm; border-radius:1.5mm; font-size:8.5pt; margin-bottom:3mm; }
</style></head><body>""")

    H.append('<div class="confidential">🔒 INTERNAL LABORATORY USE ONLY — NOT FOR PHYSICIAN OR PATIENT DISTRIBUTION</div>')
    H.append('<div class="hdr">'
             '<div class="hdr-title">🔬 AST Quality Assurance Report</div>'
             '<div class="hdr-sub">Laboratory Consistency &amp; Confidence Audit — Internal QA Archive</div>'
             '</div>')

    H.append(
        '<div class="meta-grid">'
        f'<div><b>Organism:</b> {_esc(organism or "—")}</div>'
        f'<div><b>Specimen:</b> {_esc(specimen or "—")}</div>'
        f'<div><b>Generated:</b> {_esc(_now)}</div>'
        '</div>'
    )
    H.append(
        '<div class="meta-grid">'
        f'<div><b>Microbiologist:</b> {_esc(microbiologist or "—")}</div>'
        f'<div><b>Patient Ref:</b> {_esc(patient_ref or "—")}</div>'
        f'<div><b>Lab ID:</b> {_esc(lab_id or "—")}</div>'
        '</div>'
    )

    # ── Confidence Score ──────────────────────────────────────────────
    H.append('<div class="sec-ttl">📊 Recommendation Confidence Score</div>')
    H.append(
        f'<div class="conf-box" style="background:{confidence["color"]}15;'
        f'border:1.5px solid {confidence["color"]}">'
        f'<div style="font-size:13pt;font-weight:bold;color:{confidence["color"]}">'
        f'{confidence["icon"]} {_esc(confidence["level"])} — {confidence["score"]}/100</div>'
        '<ul style="margin:2mm 0 0 4mm;padding:0;font-size:9pt">'
        + "".join(f'<li>{_esc(r)}</li>' for r in confidence["reasons"])
        + '</ul></div>'
    )
    H.append(
        '<div style="font-size:8pt;color:#888;margin-bottom:3mm">'
        f'Errors detected: {confidence["n_errors"]} &nbsp;|&nbsp; '
        f'Warnings detected: {confidence["n_warnings"]} &nbsp;|&nbsp; '
        f'Antibiotics tested: {confidence["n_tested"]}</div>'
    )

    # ── QC Issues detail ──────────────────────────────────────────────
    H.append(f'<div class="sec-ttl">🔍 AST-QA Findings ({len(qc_issues)})</div>')
    if not qc_issues:
        H.append('<div style="font-size:9.5pt;color:#1e8449">✅ All AST consistency checks passed. No issues detected.</div>')
    else:
        for issue in qc_issues:
            cls = "issue-error" if issue["severity"] == "error" else "issue-warning"
            icon = "❌" if issue["severity"] == "error" else "⚠️"
            H.append(
                f'<div class="issue-row {cls}">'
                f'<b>{icon} [{_esc(issue["id"])}] {_esc(issue["severity"].upper())}</b><br>'
                f'{_esc(issue["message"])}<br>'
                f'<span style="color:#666">✏️ {_esc(issue["fix"])}</span>'
                '</div>'
            )

    # ── Full AST panel table ──────────────────────────────────────────
    H.append('<div class="sec-ttl">🧪 Full AST Panel as Entered</div>')
    if sir_map:
        H.append('<table class="ast-table"><tr><th>Antibiotic</th><th>Result</th></tr>')
        for drug, result in sorted(sir_map.items()):
            sir_cls = f"sir-{result}" if result in ("S", "I", "R") else ""
            H.append(f'<tr><td>{_esc(drug)}</td><td class="{sir_cls}">{_esc(result)}</td></tr>')
        H.append('</table>')
    else:
        H.append('<div style="font-size:9pt;color:#888">No AST data recorded.</div>')

    H.append(
        '<div class="footer">'
        'Generated by Orange Lab AST-QA Engine | EUCAST Expert Rules v3.3 / CLSI M100 2026<br>'
        'This document is intended solely for internal laboratory quality control and audit purposes. '
        'It must not be shared with referring physicians or included in the patient-facing clinical report.'
        '</div>'
    )
    H.append('</body></html>')

    try:
        return _wp.HTML(string="".join(H)).write_pdf()
    except Exception as _exc:
        logger.debug("suppressed exception: %s", _exc)
        return None

# ══════════════════════════════════════════════════════════════════════════
# Arabic → English safety translator for the ENGLISH PDF report.
# A few engine fields exist only in Arabic (renal-dose notes, ESBL/MDR
# rationale, drug notes, interaction alerts). For lang="en" we translate them
# so the English report contains ZERO Arabic. Strategy:
#   1) longest-phrase-first replacement (accurate medical English),
#   2) word-level fallback for leftovers,
#   3) final guarantee: strip any Arabic that slipped through (logged for QA).
# Applied ONLY to clinical free-text fields — never to lab name / patient name /
# organism — so a genuinely Arabic name is preserved and never mangled. This
# code path is a no-op for the Arabic report and for already-English text.
# ══════════════════════════════════════════════════════════════════════════
_AR_RE = re.compile(r'[\u0600-\u06FF]')

_AR2EN_PHRASES_RAW = {
    # ── ESBL / carbapenemase rationale (predict_esbl) ──────────────────────
    "Ertapenem R مع Meropenem S/I — نمط مُوحٍ بـ OXA-48 (شائع في مصر/الشرق الأوسط).":
        "Ertapenem R with Meropenem S/I — pattern suggestive of OXA-48 (common in Egypt/Middle East).",
    "أجرِ DDST. قد يكون ESBL مبكر أو آلية أخرى.":
        "Perform DDST. May be an early ESBL or another mechanism.",
    "أجرِ mCIM/CarbaNP. قد يكون فقدان بورين + ESBL/AmpC وليس carbapenemase حقيقياً.":
        "Perform mCIM/CarbaNP. May be porin loss + ESBL/AmpC rather than a true carbapenemase.",
    "أرسل للمختبر المرجعي فوراً (PCR/mCIM). عزل صارم. Colistin/Ceftazidime-Avibactam.":
        "Send to the reference lab immediately (PCR/mCIM). Strict isolation. Colistin/Ceftazidime-Avibactam.",
    "أكد بـ Double-Disk Synergy Test (DDST) أو PCR. عامل كـ ESBL حتى التأكيد.":
        "Confirm with a Double-Disk Synergy Test (DDST) or PCR. Treat as ESBL until confirmed.",
    "أكد بـ mCIM / PCR (OXA-48). راقب بحذر؛ قد تكون الكاربابينيمات أقل فعالية.":
        "Confirm with mCIM / PCR (OXA-48). Monitor closely; carbapenems may be less effective.",
    "استخدم Carbapenem للعدوى الشديدة (MERINO 2018). تجنب جميع cephalosporins.":
        "Use a carbapenem for severe infection (MERINO 2018). Avoid all cephalosporins.",
    "تجنب 3rd-gen cephalosporins حتى لو S. استخدم Cefepime أو Carbapenem. لا يُكتشف بـ DDST.":
        "Avoid 3rd-gen cephalosporins even if S. Use Cefepime or a carbapenem. Not detected by DDST.",
    "مقاومة لـ 3rd-gen + Cefoxitin في كائن AmpC-prone — نمط AmpC وليس ESBL.":
        "Resistance to 3rd-gen + Cefoxitin in an AmpC-prone organism — AmpC pattern, not ESBL.",
    "مقاومة لـ ≥2 من الجيل الأقل — يستدعي تأكيد ESBL.":
        "Resistance to ≥2 lower-generation agents — warrants ESBL confirmation.",
    "مقاومة/توسط لكاربابينيم واحد — يستلزم اختبار تأكيدي.":
        "Resistance/intermediate to a single carbapenem — requires confirmatory testing.",
    "مقاومة لـ ≥2 كاربابينيم": "Resistant to ≥2 carbapenems",
    "مقاومة لـ": "Resistant to",
    # ── MDR/XDR/PDR rationale (MDR_INFO detail/action) ─────────────────────
    "تجنب الأدوية المقاومة. استشر الصيدلي السريري.":
        "Avoid resistant agents. Consult the clinical pharmacist.",
    "حالة طارئة — استشارة معدية فورية. لا خيارات قياسية.":
        "Emergency — immediate infectious-disease consult. No standard options.",
    "مقاوم لجميع الفئات الدوائية المتاحة.": "Resistant to all available drug classes.",
    "مقاوم لعامل واحد على الأقل في 3 فئات دوائية أو أكثر.":
        "Resistant to at least one agent in ≥3 drug classes.",
    "مقاوم لمعظم الفئات الدوائية — حساس لفئتين أو أقل فقط.":
        "Resistant to most drug classes — susceptible to only ≤2 classes.",
    "يستلزم استشارة متخصص. الخيارات محدودة جداً.":
        "Requires specialist consultation. Options are very limited.",
    # ── Phenotype label/detail/action (Possible MRSA) ──────────────────────
    "Possible MRSA — تأكيد مطلوب": "Possible MRSA — confirmation required",
    "أجرِ Cefoxitin disk diffusion أو PCR (mecA) للتأكيد.":
        "Perform Cefoxitin disk diffusion or PCR (mecA) to confirm.",
    "نمط مقاومة beta-lactam مع حساسية للـ Vancomycin/Linezolid يشير لـ MRSA.":
        "Beta-lactam resistance with Vancomycin/Linezolid susceptibility indicates MRSA.",
    # ── Interaction alert templates (analyze_antibiotics) ──────────────────
    "تعارض:": "Interaction:",
    "تحذير كبدي:": "Hepatic warning:",
    "يحتاج متابعة أو تعديل حسب الحالة.": "needs monitoring or dose adjustment as appropriate.",
    # ── Renal-dose note fragments (abx_guidelines renal_note/note) ─────────
    "آمن كلوياً — لا تعديل مطلوب": "Renally safe — no adjustment needed",
    "لا تعديل كلوي مطلوب — يُطرح كبدياً أساساً": "No renal adjustment needed — primarily hepatic clearance",
    "آمن كلوياً — يُطرح صفراوياً أساساً": "Renally safe — primarily biliary clearance",
    "آمن كلوياً — يُطرح عبر الصفراء بالكامل": "Renally safe — fully biliary excretion",
    "آمن كلوياً — يُطرح كبدياً أساساً": "Renally safe — primarily hepatic clearance",
    "آمن كلوياً — يُطرح كبدياً بالكامل": "Renally safe — fully hepatic clearance",
    "آمن كلوياً — يُطرح كبدياً": "Renally safe — hepatic clearance",
    "آمن كلوياً نسبياً": "Relatively renally safe",
    "آمن كلوياً": "Renally safe",
    "لا تعديل كلوي مطلوب": "No renal adjustment needed",
    "لا تعديل كلوي": "No renal adjustment",
    "لا تعديل كلوي — لكن تجنب في": "No renal adjustment — but avoid in",
    "تمديد الفترة بين الجرعات": "extend the dosing interval",
    "تمديد الفترة": "extend the interval",
    "خفض الجرعة بنسبة 50%": "reduce the dose by 50%",
    "خفض الجرعة 50% أو مضاعفة الفترة": "reduce the dose 50% or double the interval",
    "تقليل الجرعة بنسبة 50%": "reduce the dose by 50%",
    "خفض الجرعة مطلوب": "dose reduction required",
    "تعديل جرعة إلزامي": "mandatory dose adjustment",
    "تعديل الجرعة مطلوب": "dose adjustment required",
    "خفض كبير": "major reduction",
    "نصف الجرعة": "half dose",
    "مضاعفة الفترة": "double the interval",
    "تجنّب الجرعات المتكررة": "avoid repeated doses",
    "جرعة واحدة فموية": "single oral dose",
    "جرعة واحدة": "single dose",
    "جرعة بعد dialysis": "dose after dialysis",
    "دواء بعد dialysis": "dose after dialysis",
    "بعد dialysis": "after dialysis",
    "بعد Dialysis": "after dialysis",
    "ثم تعديل حسب levels": "then adjust per levels",
    "إيقاف فوري عند": "stop immediately if",
    "خطر encephalopathy": "risk of encephalopathy",
    "خطر seizures": "risk of seizures",
    "يرتفع عند": "increases at",
    "عدم كفاءة علاجية": "therapeutic inefficacy",
    "تراكم سمي": "toxic accumulation",
    "تجنب في القصور الكلوي الشديد": "avoid in severe renal impairment",
    "تجنب في": "avoid in",
    "لكن تجنب في": "but avoid in",
    "ممنوع إذا": "Contraindicated if",
    "أقل تفضيلاً من": "less preferred than",
    "مقاومة عالية": "high resistance",
    "في معظم الكائنات بدون مثبط": "in most organisms without an inhibitor",
    "يُستخدم غالباً بمثبط": "usually used with an inhibitor",
    "بدون مثبط — مقاومة عالية لكثير من الكائنات": "without inhibitor — high resistance in many organisms",
    "فعال للأذن الوسطى والمسالك": "effective for otitis media and UTI",
    "فعال لالتهابات الحلق والجلد": "effective for throat and skin infections",
    "آمن للالتهابات البسيطة والجلد": "safe for mild and skin infections",
    "خيار فموي قوي للمسالك": "strong oral option for UTI",
    "واسع المدى للجهاز التنفسي والمسالك": "broad-spectrum for respiratory and urinary tract",
    "فعال للصدر": "effective for chest infections",
    "بديل": "alternative to",
    # ── Renal-note residual gaps (fields that reach the PDF) ───────────────
    "عند تراكم الدواء — راقب الأعراض العصبية": "on drug accumulation — monitor neurological symptoms",
    "خطر encephalopathy عند تراكم الدواء": "risk of encephalopathy on drug accumulation",
    "خطر seizures يرتفع عند تراكم الدواء": "risk of seizures increases on drug accumulation",
    "عند تراكم الدواء": "on drug accumulation",
    "راقب الأعراض العصبية": "monitor neurological symptoms",
    "الأعراض العصبية": "neurological symptoms",
    "ممنوع إذا CrCl < 45 مل/د": "Contraindicated if CrCl < 45 mL/min",
    "مل/د": "mL/min",
    "جرعة واحدة فموية (3g) مقبولة حتى": "single oral dose (3g) acceptable up to",
    "مقبولة حتى": "acceptable up to",
    "مقبولة": "acceptable",
    "إذا أُعطيت الجرعة خلال 6 ساعات قبل": "if the dose was given within 6 hours before",
    "أُعطيت الجرعة خلال": "the dose was given within",
    "أُعطيت الجرعة": "the dose was given",
    "6 ساعات قبل": "6 hours before",
    "ساعات قبل": "hours before",
    "ساعات": "hours",
    "خلال": "within",
    "أُعطيت": "was given",
    "إيقاف فوري عند Cr↑ >0.5 عن baseline": "stop immediately if Cr↑ >0.5 above baseline",
    "عن baseline": "above baseline",
    "عن ": "above ",
}
_AR2EN_PHRASES = sorted(_AR2EN_PHRASES_RAW.items(), key=lambda kv: len(kv[0]), reverse=True)

_AR2EN_WORDS = {
    "مقاومة": "resistance", "مقاوم": "resistant", "الجرعة": "dose", "جرعة": "dose",
    "الجرعات": "doses", "الفترة": "interval", "تجنب": "avoid", "تجنّب": "avoid",
    "خفض": "reduce", "تمديد": "extend", "تقليل": "reduce", "مضاعفة": "double",
    "نصف": "half", "مطلوب": "required", "إلزامي": "mandatory", "بعد": "after",
    "عند": "if", "إذا": "if", "ثم": "then", "حسب": "per", "الحالة": "status",
    "خطر": "risk of", "آمن": "safe", "كلوياً": "renally", "كلوي": "renal",
    "كبدياً": "hepatically", "صفراوياً": "biliary", "الصفراء": "bile",
    "يُطرح": "cleared", "لا": "no", "مع": "with", "أو": "or", "في": "in",
    "من": "from", "مثل": "e.g.", "فقط": "only", "بدون": "without",
    "بمثبط": "with inhibitor", "مثبط": "inhibitor", "عالية": "high",
    "معظم": "most", "الكائنات": "organisms", "كائن": "organism", "فعال": "effective",
    "بديل": "alternative", "واسع": "broad", "المدى": "spectrum", "قوي": "strong",
    "المسالك": "UTI", "الصدر": "chest", "الحلق": "throat", "الجلد": "skin",
    "البسيطة": "mild", "الوسطى": "middle", "الأذن": "ear", "أقل": "less",
    "تفضيلاً": "preferred", "يُستخدم": "used", "غالباً": "commonly",
    "استشر": "consult", "الصيدلي": "pharmacist", "السريري": "clinical",
    "استشارة": "consult", "متخصص": "specialist", "فورية": "immediate",
    "فوري": "immediate", "طارئة": "emergency", "الأدوية": "agents",
    "الفئات": "classes", "الدوائية": "drug", "المتاحة": "available",
    "حساس": "susceptible", "حساسية": "susceptibility", "الخيارات": "options",
    "محدودة": "limited", "جداً": "very", "كبير": "major", "تراكم": "accumulation",
    "سمي": "toxic", "عدم": "lack of", "كفاءة": "efficacy", "علاجية": "therapeutic",
    "ممنوع": "contraindicated", "مقبول": "acceptable", "فموي": "oral",
    "فموية": "oral", "واحدة": "single", "واحد": "single", "المتكررة": "repeated",
    "إيقاف": "stop", "يرتفع": "increases", "القصور": "impairment",
    "الشديد": "severe", "الشديدة": "severe", "متابعة": "monitoring",
    "تعديل": "adjustment", "يحتاج": "needs", "شائع": "common", "مبكر": "early",
    "آلية": "mechanism", "أخرى": "other", "أجرِ": "perform", "أكد": "confirm",
    "عامل": "treat as", "حتى": "until", "التأكيد": "confirmation",
    "للتأكيد": "to confirm", "راقب": "monitor", "بحذر": "closely",
    "أرسل": "send", "المرجعي": "reference", "للمختبر": "to the lab",
    "عزل": "isolation", "صارم": "strict", "يشير": "indicates", "نمط": "pattern",
    "يستدعي": "warrants", "يستلزم": "requires", "اختبار": "test",
    "تأكيدي": "confirmatory", "توسط": "intermediate", "الجيل": "generation",
    "الأقل": "lower", "كاربابينيم": "carbapenem", "الكاربابينيمات": "carbapenems",
    "فقدان": "loss", "بورين": "porin", "حقيقياً": "true", "جميع": "all",
    "للعدوى": "for infection", "العدوى": "infection", "يُكتشف": "detected",
    "الشرق": "East", "الأوسط": "Middle", "مصر": "Egypt", "تعارض": "interaction",
    "تحذير": "warning", "كبدي": "hepatic", "لكن": "but", "لكثير": "in many",
    "نسبياً": "relatively", "لعامل": "one agent", "لفئتين": "two classes",
    "لجميع": "all", "لمعظم": "most", "الأكثر": "more", "أمانًا": "safe",
    "قياسية": "standard", "معدية": "infectious-disease",
}


def _ar2en(text, en=True):
    """Return `text` with all Arabic clinical wording rendered in English.

    No-op for the Arabic report (`en=False`) and for text that has no Arabic.
    Guarantees the result contains no Arabic characters (any leftover is
    stripped and logged), so the English PDF can never leak Arabic.
    """
    if not text or not en or not _AR_RE.search(text):
        return text
    s = text
    for ar_p, en_p in _AR2EN_PHRASES:
        if ar_p in s:
            s = s.replace(ar_p, en_p)
    if _AR_RE.search(s):
        s = re.sub(r'[\u0600-\u06FF]+',
                   lambda m: _AR2EN_WORDS.get(m.group(0), m.group(0)), s)
    resid = _AR_RE.findall(s)
    if resid:
        logger.warning("EN PDF: stripped untranslated Arabic: %s",
                       " ".join(dict.fromkeys(resid))[:150])
        s = re.sub(r'[\u0600-\u06FF]+', '', s)
    return re.sub(r'\s{2,}', ' ', s).strip(' -–—|·،,')


def generate_pdf_html_report(
    patient_name: str, age: int, sex: str, weight: float,
    cl_cr: float, is_renal: bool, is_preg: bool, is_hepatic: bool,
    allowed: List[Dict], warned: List[Dict], banned: List[Dict],
    preg_warn_items: List[Dict], organism: str, specimen: str,
    sir_map: Dict[str, str], interactions: List[str],
    mdr_result: Dict, esbl_result: Dict, phenotypes: List[Dict],
    colony_count: str = "", date_in: str = "", pus_cells: str = "",
    rbcs: str = "", lab_name: str = "Orange Lab", lab_city: str = "",
    patho_assessment: dict = None, duration_data: dict = None,
    combo_suggestions: list = None, show_commercial_names: bool = False,
    child_pugh: str = "", hepatic_recs: list = None,
    lang: str = "ar",
) -> Optional[bytes]:
    if not WEASYPRINT_AVAILABLE:
        return None

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── Language helpers ─────────────────────────────────────────────────
    _EN = lang == "en"

    # All bilingual strings used in this PDF
    _T = {
        # Section headers
        "recommended":   "Recommended Therapy — Ranked"       if _EN else "Recommended Therapy — Ranked",
        "avoid":         "Avoid / Contraindicated"            if _EN else "🚫 Avoid / Contraindicated",
        "dose_adj":      "⚠ Dose Adjustment / Use with Caution",
        "interactions":  "💊 Drug Interactions",
        "pregnancy":     "🤰 Pregnancy — Use with Caution",
        "preg_sub":      "(Physician decision required for all items below)",
        "treatment":     "Treatment Duration",
        "pathogenicity": "Pathogenicity Assessment",
        # Pregnancy inline notes
        "preg_extra":    "Additional options require caution in pregnancy — see Pregnancy section below."
                         if _EN else "🤰 خيارات إضافية بحذر في الحمل — راجع قسم Pregnancy بالأسفل.",
        "preg_only":     "All sensitive agents require caution in pregnancy — see Pregnancy — Use with Caution below."
                         if _EN else "🤰 جميع الخيارات الحساسة تتطلب حذراً في الحمل — راجع قسم Pregnancy — Use with Caution بالأسفل لاتخاذ القرار.",
        # Renal
        "renal_label":   "Patient CrCl" if _EN else "Patient CrCl",
        "renal_thresh":  "Threshold: CrCl ≤",
        "renal_adj":     "⚠ Renal dose adjustment required  |  Threshold: CrCl ≤",
        "intermediate":  "⚠ Intermediate (I) in culture result — use only if no better option",
        # Patho
        "supporting":    "Supporting:",
        "against":       "Against:",
        "recs":          "Recommendations:",
        # Duration
        "protocol":      "Protocol",
        "standard":      "Standard",
        "range":         "Range",
        "iv_po":         "IV/PO Split",
        "follow_up":     "📋 Follow-up culture recommended after treatment",
        # Footer
        "disclaimer":    "Disclaimer: Clinical decision support only. Treatment decisions are the sole responsibility of the treating physician.",
        "references":    "References",
    }

    def _xlate_preg_note(note: str) -> str:
        """Translate Arabic preg_note to English for EN mode."""
        if not _EN or not note:
            return note
        import re as _re
        _arabic_re = _re.compile(r'[؀-ۿ]+')
        if not _arabic_re.search(note):
            return note   # already English

        # Known translations map
        _AR_EN = {
            "ممنوع في الحمل":                   "Contraindicated in pregnancy",
            "تحذير حمل":                         "Pregnancy caution",
            "مقبول في الحمل":                    "Acceptable in pregnancy",
            "آمن في الـ":                        "Safe in",
            "تجنّب في الـ":                      "Avoid in",
            "تجنّب":                             "Avoid",
            "يترسّب في عظام وأسنان الجنين":      "chelates into fetal bone and teeth",
            "تصبغ دائم للأسنان":                "permanent tooth discoloration",
            "تثبيط نمو العظام":                 "inhibited bone growth",
            "محظورة في كل مراحل الحمل":          "contraindicated throughout all trimesters",
            "خاصة بعد الأسبوع":                 "especially after week",
            "البديل":                           "Alternative",
            "بيانات بشرية محدودة":              "limited human data",
            "يعبر المشيمة":                     "crosses placenta",
            "سُمية للأذن الجنينية":             "fetal ototoxicity",
            "فقدان سمع دائم":                   "permanent hearing loss",
            "مضاد حمض الفوليك":                 "folate antagonist",
            "عيوب أنبوب عصبي":                  "neural tube defects",
            "يُفضل تجنبه":                      "prefer to avoid",
            "إن وُجد بديل آمن":                 "if a safer alternative exists",
            "مقبول في كل":                      "acceptable throughout all",
            "عند الضرورة":                      "when medically necessary",
            "القرار النهائي للطبيب المعالج":     "Final decision: treating physician",
            "حصراً":                            "exclusively",
            "خطر":                              "risk of",
            "خطر hemolytic anemia في الجنين":   "risk of fetal hemolytic anemia (G6PD)",
            "نيونيتل hemolysis عند الوليد":     "neonatal hemolysis",
            "البديل في 3rd trim":               "Alternative in 3rd trim",
            "جرعة واحدة":                       "(single dose)",
            "الأدلة الحديثة":                   "Recent evidence",
            "دحضت مخاوف":                       "refuted concerns about",
            "التشوهات القديمة":                 "historical malformation risk",
            "يُفضل تجنبه في الـ 1st trimester": "prefer to avoid in 1st trimester",
            "ارتبط بتشوهات خلقية":              "associated with congenital malformations",
            "الدراسات الحيوانية والبشرية":       "in animal and human studies",
            "أثبت سُمية جنينية في الحيوانات":   "demonstrated fetal toxicity in animal studies",
            "يُستخدم فقط عند انعدام البدائل":    "use only when no alternatives available",
            "يُستخدم عند الضرورة القصوى":        "use only when critically necessary",
            "مراقبة وظائف الكلى":               "monitor renal function",
            "السمع للأم والجنين":                "and fetal/maternal hearing",
            "Category C":                        "Category C",
            "Category B":                        "Category B",
            "عند الحاجة لكاربابينيم":           "when a carbapenem is needed",
            "يُفضل Meropenem":                  "Meropenem preferred",
            "عند تعذّر Meropenem":              "if Meropenem is unavailable",
            "nephrotoxicity":                    "nephrotoxicity",
            "يُستخدم فقط لإنقاذ الحياة":        "life-saving use only",
            "في XDR gram-negatives":            "for XDR gram-negative infections",
            "غياب أي بديل":                     "when no alternative exists",
            "تجنّب ما أمكن":                    "avoid whenever possible",
            "تجنّب في الـ 3rd trimester":        "avoid in 3rd trimester",
            "≥36 أسبوع":                        "≥36 weeks gestation",
            "ممنوع في الـ 1st trimester":        "contraindicated in 1st trimester",
            "ممنوع في كل الحمل":                "contraindicated throughout pregnancy",
            "لا يُعتبر خطاً أول":               "not a first-line agent",
            "أبداً في الحمل":                    "at any point in pregnancy",
            "خطر التشوهات أقل مما كان يُعتقد":  "teratogenicity risk lower than previously thought",
            "لا يُستخدم كخط أول":               "do not use as first-line",
            "فقط عند غياب البديل الأكثر أمانًا": "only when no safer alternative exists",
            "مقبول بجرعة واحدة":                "acceptable as single dose",
            "لـ uncomplicated UTI في الحمل":    "for uncomplicated UTI in pregnancy",
            "خيار مفضل على Nitrofurantoin":     "preferred over Nitrofurantoin",
            "1st trim":                          "1st trimester",
            "2nd trim":                          "2nd trimester",
            "3rd trim":                          "3rd trimester",
            "trimester":                         "trimester",
        }

        result = note
        for ar, en in _AR_EN.items():
            result = result.replace(ar, en)
        # Safety-net: any Arabic that survived the phrase map is stripped
        # by the same guarantee used in _ar2en() — no Arabic can reach the PDF.
        return _ar2en(result, True)

    def _xlate_patho(text: str) -> str:
        """Translate Arabic pathogenicity text to English."""
        if not _EN or not text:
            return text
        import re as _re
        if not _re.compile(r'[؀-ۿ]').search(text):
            return text
        _PATHO_EN = {
            "المؤشرات تدعم بقوة وجود عدوى حقيقية. يُنصح بالعلاج الموجَّه بنتيجة الحساسية مع مراعاة السياق الكلينيكي.":
                "Strong indicators of TRUE INFECTION. Culture-directed therapy is recommended, considering the clinical context.",
            "المؤشرات تدعم بقوة وجود عدوى حقيقية":
                "Strong indicators of true infection",
            "يُنصح بالعلاج الموجَّه بنتيجة الحساسية مع مراعاة السياق الكلينيكي":
                "Culture-directed therapy recommended based on clinical context",
            "ابدأ العلاج بناءً على نتيجة الـ AST.":
                "Initiate therapy based on AST results.",
            "ابدأ العلاج بناءً على نتيجة الـ AST":
                "Initiate therapy based on AST results",
            "راعِ شدة الأعراض وعوامل الخطر.":
                "Consider symptom severity and risk factors.",
            "راعِ شدة الأعراض وعوامل الخطر":
                "Consider severity and risk factors",
            "راجع الجرعة حسب الوظيفة الكلوية.":
                "Review dosing based on renal function.",
            "راجع الجرعة حسب الوظيفة الكلوية":
                "Review dosing based on renal function",
            "De-escalate بعد 48–72 ساعة إذا تحسّن المريض.":
                "De-escalate after 48–72 hours if patient improves.",
            "النتيجة حدودية. يُنصح بالتقييم الكلينيكي الكامل قبل البدء بالعلاج.":
                "Borderline result. Full clinical assessment recommended before initiating treatment.",
            "قد تحتاج فحوصات إضافية أو إعادة المزرعة.":
                "Additional workup or repeat culture may be needed.",
            "لا يُنصح بالعلاج إلا في الحامل أو قبل تدخل جراحي بولي.":
                "Treatment not recommended unless patient is pregnant or pre-urological procedure.",
            "المؤشرات تميل نحو التلوث أو الاستعمار.":
                "Indicators suggest contamination or colonization.",
            "ABU في سياق يستوجب العلاج (حمل / تدخل جراحي بولي).":
                "Asymptomatic Bacteriuria requiring treatment (pregnancy / pre-op).",
            "اختر مضاداً حيوياً مناسباً للحمل حسب نتيجة الحساسية.":
                "Select a pregnancy-appropriate antibiotic per sensitivity results.",
            "مدة العلاج 5–7 أيام عادةً.":
                "Treatment duration typically 5–7 days.",
            "أعِد المزرعة بعد الانتهاء من الدورة للتأكد من الشفاء.":
                "Repeat culture post-treatment to confirm clearance.",
            "العينة غير مناسبة":
                "Specimen inadequate",
            "ارفض العينة وأعِد طلب البلغم بتقنية صحيحة.":
                "Reject specimen and request repeat sputum with proper technique.",
            "قيّم المريض كلينيكياً قبل إعطاء المضادات الحيوية.":
                "Assess the patient clinically before giving antibiotics.",
            "فكّر في إعادة المزرعة إذا كان الوضع غير واضح.":
                "Consider repeating the culture if the situation is unclear.",
            "راجع نتيجة الـ Urinalysis / CRP / CBC إذا لم تكن متاحة.":
                "Review Urinalysis / CRP / CBC results if not available.",
            "النتيجة حدودية. يُنصح بالتقييم الكلينيكي الكامل قبل البدء بالعلاج. قد تحتاج فحوصات إضافية أو إعادة المزرعة.":
                "Borderline result. Full clinical assessment is recommended before starting treatment. Additional tests or repeat culture may be needed.",
            "أعِد تقييم المريض إذا استمرت الأعراض أو تطورت.":
                "Re-evaluate the patient if symptoms persist or progress.",
            "ابدأ العلاج التجريبي فوراً ريثما تظهر نتيجة الحساسية.":
                "Start empiric therapy immediately pending sensitivity results.",
            "احتجز المريض ومراقبته بشكل مكثف.":
                "Admit the patient for intensive monitoring.",
            "استثناءات: حمل — قبيل جراحة بولية (Urology pre-op).":
                "Exceptions: pregnancy / pre-urological surgery.",
            "استشر طبيب الأمراض المعدية.":
                "Consult an infectious disease specialist.",
            "التزم بمبادئ Antibiotic Stewardship.":
                "Adhere to Antibiotic Stewardship principles.",
            "العينة من موقع معقم (CSF) — أي نمو يُعدّ مرضياً بغض النظر عن العوامل الأخرى.":
                "Specimen from a sterile site (CSF) — any growth is pathogenic regardless of other factors.",
            "المؤشرات تدعم التلوث أو الاستعمار بشكل كبير. العلاج غير مبرر في الغالب. تابع المريض كلينيكياً.":
                "Indicators strongly support contamination/colonization. Treatment usually unjustified. Follow up clinically.",
            "تابع المريض وأعِد التقييم إذا ظهرت أعراض.":
                "Follow up and reassess if symptoms appear.",
            "تشير المعطيات إلى Asymptomatic Bacteriuria. وفقاً لـ IDSA 2019: لا يُنصح بالعلاج إلا في الحامل أو قبل تدخل جراحي بولي.":
                "Findings indicate Asymptomatic Bacteriuria. Per IDSA 2019: treatment not recommended except in pregnancy or before a urological procedure.",
            "لا تعطِ مضادات حيوية (Antibiotic Stewardship — IDSA 2019).":
                "Do NOT give antibiotics (Antibiotic Stewardship — IDSA 2019).",
            "لا تعطِ مضادات حيوية بناءً على هذه النتيجة.":
                "Do NOT give antibiotics based on this result.",
        }
        result = text
        for ar, en in _PATHO_EN.items():
            result = result.replace(ar, en)

        # Word-level fallback for any remaining Arabic fragments
        _WORD_EN = {
            "إعطاء": "give", "قيّم": "assess", "إعادة": "repeat", "المزرعة": "culture",
            "فكّر": "consider", "الوضع": "status", "الحيوية": "", "متاحة": "available",
            "المضادات": "antibiotics", "كان": "if", "أعِد": "repeat", "تقييم": "assessment",
            "المريض": "patient", "إذا": "if", "استمرت": "persist", "الأعراض": "symptoms",
            "تطورت": "progress", "ابدأ": "start", "العلاج": "therapy", "التجريبي": "empiric",
            "فوراً": "immediately", "ريثما": "pending", "تظهر": "appears", "نتيجة": "result",
            "الحساسية": "sensitivity", "احتجز": "admit", "ومراقبته": "and monitor", "بشكل": "",
            "مكثف": "intensive", "استشر": "consult", "طبيب": "physician", "الأمراض": "disease",
            "المعدية": "infectious", "التزم": "adhere", "بمبادئ": "to principles", "تابع": "follow up",
            "وأعِد": "and repeat", "التقييم": "assessment", "ظهرت": "appear", "تشير": "indicate",
            "المعطيات": "findings", "إلى": "to", "وفقاً": "per", "لـ": "",
            "لا": "do NOT", "تعطِ": "give", "مضادات": "antibiotics", "حيوية": "",
            "بناءً": "based", "هذه": "this", "النتيجة": "result", "العينة": "specimen",
            "من": "from", "موقع": "site", "معقم": "sterile", "أي": "any",
            "نمو": "growth", "يُعدّ": "is", "مرضياً": "pathogenic", "بغض": "regardless",
            "النظر": "", "عن": "of", "العوامل": "factors", "الأخرى": "other",
            "احتجاز": "admission", "المؤشرات": "Indicators", "تدعم": "support", "بقوة": "strongly",
            "وجود": "presence of", "عدوى": "infection", "حقيقية": "true", "يُنصح": "recommended",
            "بالعلاج": "treatment", "الموجَّه": "directed", "بنتيجة": "by result", "مع": "with",
            "مراعاة": "considering", "السياق": "context", "الكلينيكي": "clinical", "على": "on",
            "الـ": "", "راجع": "review", "الجرعة": "dose", "حسب": "per",
            "الوظيفة": "function", "الكلوية": "renal", "راعِ": "consider", "شدة": "severity",
            "وعوامل": "and factors", "الخطر": "risk", "حدودية": "borderline", "كامل": "full",
            "قبل": "before", "البدء": "starting",
        }
        if re.compile(r'[؀-ۿ]').search(result):
            for ar, en in _WORD_EN.items():
                result = result.replace(ar, en)
            result = re.sub(r'\s+', ' ', result).strip()
        # Safety-net: any Arabic that survived phrase + word maps is stripped
        # by the same guarantee used in _ar2en() — no Arabic can reach the PDF.
        return _ar2en(result, True)

    # ── AWaRe helpers ────────────────────────────────────────────────────
    AWARE_CLR  = {"Access": "#1e8449", "Watch": "#b7770d", "Reserve": "#922b21"}
    AWARE_PILL = {"Access": "background:#1e8449;color:#fff",
                  "Watch":  "background:#b7770d;color:#fff",
                  "Reserve":"background:#922b21;color:#fff"}
    AWARE_CARD = {"Access": "background:#eafaf1;border:0.8pt solid #1e8449",
                  "Watch":  "background:#fef9e7;border:0.8pt solid #b7770d",
                  "Reserve":"background:#fdf2f2;border:0.8pt solid #922b21"}
    TIER_LBL   = {"Access": "First-line", "Watch": "Alternative", "Reserve": "Reserve / MDR"}

    # المصدر الموحّد للترتيب — نفس منطق الشاشة والصورة (الحساسية أولاً ثم العينة
    # ثم AWaRe ثم الطريق)، بدلاً من ترتيب AWaRe منفصل كان يعطي ترتيباً مختلفاً.
    ranked   = rank_sensitive_antibiotics(allowed, specimen, organism, sir_map, phenotypes)
    mdr_class = mdr_result.get("level","") if mdr_result else ""
    ph_labels = [p.get("phenotype","") for p in phenotypes]
    esbl_prob = esbl_result.get("probability","low")
    esbl_conf = esbl_result.get("confidence", 0) if esbl_result else 0
    # Header pills must reflect only confirmed/high-confidence findings —
    # weak/fallback inferences (e.g. "Possible MRSA" without Oxacillin/Cefoxitin
    # confirmation) stay in the body detail, not the prominent header badge.
    _WEAK_HEADER_PHENOTYPES = {"Possible MRSA"}
    _hdr_ph_labels = [p for p in ph_labels if p not in _WEAK_HEADER_PHENOTYPES]
    # Flags for Avoid-reason tagging (derived from passed-in results)
    _is_esbl_like     = esbl_prob in ("high", "ampc")
    _is_carbapenemase = esbl_prob == "carbapenemase"
    _is_mrsa          = any("MRSA" in str(p).upper() for p in ph_labels) \
                        or "mrsa" in str(organism).lower()

    def pill(txt, style):
        return f'<span style="padding:0.3mm 2.5mm;border-radius:2mm;font-size:8pt;font-weight:bold;{style}">{_esc(txt)}</span>'

    # ── Compact CSS ──────────────────────────────────────────────────────
    CSS = """
@page {
    size: A4;
    margin: 6mm 10mm 8mm 10mm;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages) " | Microbiology CDSS | " string(labname);
        font-size: 7.5pt; color: #888;
        font-family: 'DejaVu Sans', sans-serif;
    }
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Amiri','Noto Naskh Arabic','DejaVu Sans',Arial,sans-serif;
       font-size: 9pt; color: #1a1a2e; direction: ltr; background: #fff; }
.ltr { direction: ltr; unicode-bidi: embed; display: inline; }
.rtl { direction: rtl; unicode-bidi: embed; }
/* Header — compact */
.hdr { background:#0d3b66; color:#fff; padding:2mm 8mm 1.5mm; display:flex;
       justify-content:space-between; align-items:center; }
.hdr-lab  { font-size:14pt; font-weight:bold; }
.hdr-sub  { font-size:8pt; opacity:0.85; margin-top:0.3mm; }
.hdr-pills { margin-top:0.5mm; }
.hdr-right { font-size:8pt; opacity:0.9; text-align:right; direction:ltr; }
.accent   { height:1mm; background:#ff8c00; }
.content  { padding: 0.5mm 0; }
/* Micro info grid */
.info4 { display: table; width: 100%; border-collapse: collapse; font-size:8pt; margin:1mm 0; }
.info4 tr td { padding: 1mm 2.5mm; border: 0.3pt solid #d5d8dc; }
.lbl4 { background:#f4f6f8; font-weight:bold; color:#0d3b66; width:14%; }
.val4 { width:22%; }
/* Section titles — tighter */
.sec-ttl { font-size:8.5pt; font-weight:bold; color:#0d3b66; text-transform:uppercase;
            border-bottom:1pt solid #0d3b66; padding-bottom:0.2mm; margin:1.2mm 0 0.6mm;
            direction:ltr; text-align:left; }
/* AST table */
.ast { width:100%; border-collapse:collapse; font-size:8pt; direction:ltr; }
.ast th { background:#0d3b66; color:#fff; padding:1mm 2.5mm; text-align:left; font-size:8pt; }
.ast td { padding:1mm 2.5mm; border:0.3pt solid #d5d8dc; text-align:left; }
.ast tr:nth-child(even) td { background:#f8f9fa; }
.sir-s { color:#1e8449; font-weight:bold; }
.sir-i { color:#b7770d; font-weight:bold; }
.sir-r { color:#922b21; font-weight:bold; }
/* Page break */
.pb { page-break-after: always; }
/* Two-column grid */
.grid2 { display:table; width:100%; border-spacing:1mm; border-collapse:separate; direction:ltr; }
.g2l { display:table-cell; width:49%; vertical-align:top; direction:ltr; text-align:left; }
.g2r { display:table-cell; width:49%; vertical-align:top; direction:ltr; text-align:left; }
/* Ranked rows — tighter */
.ranked-row { padding:1mm 2.5mm; margin:0.4mm 0; border-radius:1.5mm; direction:ltr; text-align:left;
              display:flex; justify-content:space-between; align-items:center; page-break-inside:avoid; }
.tier-sep { font-size:7.5pt; font-weight:bold; text-transform:uppercase; letter-spacing:0.3pt;
            direction:ltr; text-align:left;
            padding:0.2mm 0; margin-top:0.8mm; border-top:0.8pt solid; }
/* Alerts — tighter */
.alert { padding:0.8mm 2.5mm; border-radius:1.5mm; margin:0.3mm 0; font-size:8.5pt; direction:ltr; text-align:left; }
.al-warn   { background:#fef9e7; border:0.4pt solid #b7770d; color:#7d6608; }
.al-danger { background:#fdedec; border:0.4pt solid #922b21; color:#78281f; }
.al-info   { background:#eaf4fb; border:0.4pt solid #2980b9; color:#1a5276; }
.score-bar { background:#e5e7eb; border-radius:1.5mm; height:3mm; width:100%; }
.score-fill{ height:3mm; border-radius:1.5mm; }
.compact-tbl { width:100%; border-collapse:collapse; font-size:8.5pt; direction:ltr; }
.compact-tbl td { padding:0.8mm 2.5mm; border:0.3pt solid #d5d8dc; text-align:left; }
.compact-tbl .lbl { background:#f4f6f8; font-weight:bold; color:#0d3b66; width:40%; }
.warn-val  { color:#b7770d; font-weight:bold; }
.danger-val{ color:#922b21; font-weight:bold; }
.no-break  { page-break-inside: avoid; }
hr.dv { border:none; border-top:0.4pt solid #d5d8dc; margin:0.6mm 0; }
/* Safety net: long, unbreakable drug names must never overflow the A4 margin */
.content, .alert, .g2l, .g2r, .ranked-row > div { overflow-wrap:anywhere; }
.ranked-row > div { min-width:0; }
"""

    # ── Specimen short label for header (lab-report convention) ───────────
    SPECIMEN_SHORT = {
        "Urine":       "Urine C/S",
        "Blood":       "Blood C/S",
        "Sputum":      "Sputum C/S",
        "Wound Swab":  "Wound C/S",
        "Pus":         "Pus C/S",
        "Stool":       "Stool C/S",
        "CSF":         "CSF C/S",
    }
    specimen_short = SPECIMEN_SHORT.get(specimen, f"{specimen} C/S" if specimen else "")

    def hdr_html(page_lbl: str) -> str:
        mdr_pills = ""
        # MDR/XDR/PDR — deterministic category count (Magiorakos 2012), always shown
        if mdr_class: mdr_pills += pill(mdr_class, "background:#922b21;color:#fff")+" "
        # Resistance phenotypes (MRSA/VRE/CRE/CRAB/CRPA) — confirmed via direct AST
        # markers, always shown. Weak/fallback inferences already excluded upstream.
        for ph in _hdr_ph_labels[:3]: mdr_pills += pill(ph, "background:#6e2fa0;color:#fff")+" "
        # ESBL/AmpC/Carbapenemase — genuinely PREDICTED mechanisms (predict_esbl()).
        # Only surface in header when confidence is high; lower-confidence calls
        # remain available in the body detail, not as a prominent badge.
        if esbl_conf >= 70:
            if esbl_prob == "carbapenemase": mdr_pills += pill("CARBAPENEMASE","background:#922b21;color:#fff")
            elif esbl_prob == "ampc":        mdr_pills += pill("AmpC","background:#b7770d;color:#fff")
            elif esbl_prob in ("high","moderate"): mdr_pills += pill("ESBL+","background:#b7770d;color:#fff")
        _pills_html = ("<div class='hdr-pills'>" + mdr_pills + "</div>") if mdr_pills else ""
        return f"""<div class="hdr">
  <div>
    <div class="hdr-lab">🔬 {_esc(lab_name)}</div>
    <div class="hdr-sub">{_esc(lab_city)} &nbsp;|&nbsp; Microbiology CDSS</div>
    {_pills_html}
  </div>
  <div class="hdr-right">
    <b style="font-size:11pt">{_esc(specimen_short)}</b><br>
    <span style="font-size:8pt;color:#666">{page_lbl}</span><br>
    {_esc(date_in or now_str[:10])}<br>

    <i>{_esc(organism)}</i> — {_esc(patient_name or "—")}
  </div>
</div><div class="accent"></div><div class="content">"""

    H = []
    H.append("<!DOCTYPE html><html lang='en' dir='ltr'><head><meta charset='UTF-8'>"
             f"<style>{CSS}</style></head><body>")

    # ════════════════════════════════════════════════════════════════
    # SINGLE PAGE: Clinical Decision Support
    # (Page 1 Patient/Culture/AST removed — CDS only)
    # ════════════════════════════════════════════════════════════════
    H.append(hdr_html("CLINICAL ADVISORY — Orange Lab"))
    H.append('<div class="content">')

    # ── RECOMMENDED THERAPY — RANKED ─────────────────────────────────────
    # PDF: only "allowed" (truly clear) drugs here. Pregnancy-caution drugs
    # are shown ONLY in the dedicated Pregnancy section below (no duplication).
    if ranked:
        H.append(f'<div class="sec-ttl">{_T["recommended"]}</div>')
        prev_tier = ""
        for i, _rd in enumerate(ranked, 1):
            _raw  = _rd.get("aware","")
            _tlbl = TIER_LBL.get(_raw, _raw)
            _clr  = AWARE_CLR.get(_raw,"#444")
            _ccss = AWARE_CARD.get(_raw,"")
            _sirv = sir_map.get(_rd.get("name",""),"S")
            _rte  = "PO" if _rd.get("high_po") else "IV/IM"
            _brnd = _esc(get_commercial_name(_rd.get("name",""))) if show_commercial_names else ""
            _rnl  = _esc(_ar2en(_rd.get("renal_note",""), _EN)) if is_renal else ""
            if _tlbl != prev_tier:
                H.append(f'<div class="tier-sep" style="color:{_clr};border-color:{_clr}">{_tlbl}</div>')
                prev_tier = _tlbl
            H.append(
                f'<div class="ranked-row" style="{_ccss};border-radius:1.5mm;padding:1mm 2.5mm;margin:0.3mm 0">'
                '<div style="flex:1;min-width:0;overflow-wrap:anywhere">'
                f'<b style="font-size:10.5pt;color:{_clr}">{i}. {_esc(_rd.get("name",""))}</b>'
                f'&ensp;<span class="ltr" style="background:#fff;border:0.4pt solid {_clr};color:{_clr};'
                f'font-size:8.5pt;padding:0.3mm 2.5mm;border-radius:1mm">{_sirv}</span>'
                f'&ensp;<span style="font-size:8.5pt;color:#555">{_rte}</span>'
                + (f'&ensp;<small style="color:#b7770d">⚠ {_rnl}</small>' if _rnl else "")
                + (f'&ensp;<small style="color:#888">Brands: {_brnd}</small>' if _brnd else "")
                + '</div>'
                f'<div>{pill(_raw, AWARE_PILL.get(_raw,""))}</div>'
                '</div>'
            )
        # Note if pregnancy-caution options exist below
        if is_preg and preg_warn_items:
            H.append('<div style="font-size:8pt;color:#6c3483;margin-top:0.5mm">'
                     f'{_T["preg_extra"]}</div>')
    else:
        H.append(f'<div class="sec-ttl">{_T["recommended"]}</div>')
        if is_preg and preg_warn_items:
            H.append('<div class="alert al-info" style="font-size:8.5pt">'
                     f'{_T["preg_only"]}</div>')
        else:
            H.append('<div class="alert al-info" style="font-size:8.5pt">'
                     'No clear first-line options — see Caution / Pregnancy sections below.</div>')

    # ── AVOID — each drug with its specific reason ────────────────────────
    if banned:
        # Map ban category → short reason tag (bilingual, color-coded)
        def _ban_reason(bd):
            cat = bd.get("category", "")
            nm  = bd.get("name", "")
            _sir = sir_map.get(nm, "")
            _info_lookup = ABX_GUIDELINES.get(nm, {})
            _cls = (_info_lookup.get("class", "") or "").lower()
            # 1. Resistant in culture (explicit R)
            if cat == "resistant" or _sir == "R":
                return ('❌ (R)', '#922b21')
            # 2. Pregnancy contraindication
            if cat == "pregnancy":
                return ('⛔ Pregnancy', '#7d3c98')
            # 3. Pediatric / child
            if cat in ("child", "pediatric"):
                return ('⛔ Pediatric', '#7d3c98')
            # 4. Renal
            if cat == "renal":
                return ('⚠ Renal', '#b7770d')
            # 5. Organism-based (MRSA / ESBL / AmpC / Carbapenemase / intrinsic)
            if cat == "organism":
                _is_betalactam = any(k in _cls for k in
                                     ("penicillin", "cephalosporin", "carbapenem"))
                # MRSA: detected + beta-lactam
                if _is_mrsa and _is_betalactam:
                    return ('⚠ MRSA — β-lactam', '#922b21')
                # Carbapenemase
                if _is_carbapenemase and _is_betalactam:
                    return ('⚠ Carbapenemase', '#922b21')
                # ESBL/AmpC suppression of penicillins+cephalosporins
                if _is_esbl_like and _is_betalactam:
                    return ('⚠ ESBL Concern', '#b7770d')
                # Otherwise intrinsic resistance
                return ('⚠ Intrinsic R', '#922b21')
            return ('❌ Avoid', '#922b21')

        H.append(
            '<div class="sec-ttl" style="margin-top:0.6mm;color:#922b21;border-bottom-color:#922b21">'
            f'{_T["avoid"]}</div>'
        )
        # Build per-drug rows with reason tag
        _avoid_rows = []
        for _bd in banned:
            _nm   = _esc(_bd.get("name",""))
            _tag, _clr = _ban_reason(_bd)
            _avoid_rows.append(
                '<span style="display:inline-block;margin:0.3mm 1mm 0.3mm 0;'
                f'padding:0.2mm 2mm;background:#fff;border:0.4pt solid {_clr};'
                'border-radius:1.5mm;font-size:8pt;max-width:90mm;overflow-wrap:anywhere;vertical-align:top">'
                f'<b style="color:#1a1a2e">{_nm}</b> '
                f'<span style="color:{_clr};font-size:7.5pt">{_tag}</span></span>'
            )
        H.append(
            '<div class="alert al-danger" style="font-size:8.5pt;line-height:1.6">'
            f'{"".join(_avoid_rows)}</div>'
        )
        # Pregnancy-banned — separate line for clarity
        _preg_banned = [_bd for _bd in banned if _bd.get("category") == "pregnancy"]
        if _preg_banned and is_preg:
            _pb_names = ", ".join(_esc(_bd["name"]) for _bd in _preg_banned)
            H.append(
                '<div class="alert al-danger" style="font-size:8.5pt;margin-top:1mm">'
                f'⛔ <b>Pregnancy Contraindicated:</b> {_pb_names}</div>'
            )

    # ── DOSE ADJUSTMENT / USE WITH CAUTION — compact chip grid ──────────
    if warned:
        H.append('<div class="sec-ttl" style="margin-top:0.6mm;color:#b7770d;border-bottom-color:#b7770d">'
                 f'{_T["dose_adj"]}</div>')
        # Shared notes (renal / intermediate) stated ONCE here instead of
        # repeating under every single drug below.
        _sub_notes = []
        if is_renal:
            _sub_notes.append(f'{_T["renal_label"]} = {cl_cr:.1f} ml/min')
        if any(_wd.get("warning_reason") == "intermediate_culture" for _wd in warned):
            _sub_notes.append('⚠ Intermediate (I) in culture — use only if no better option')
        if _sub_notes:
            H.append('<div style="font-size:7.5pt;color:#7d6608;margin-bottom:1mm">'
                     + ' &nbsp;·&nbsp; '.join(_sub_notes) + '</div>')

        H.append('<div style="display:flex;flex-wrap:wrap;gap:1mm;align-items:stretch">')
        for _wd in warned:
            _wname = _esc(_wd.get("name",""))
            _waw   = _esc(_wd.get("aware",""))
            _wreason = _wd.get("warning_reason","")
            _waw_style = {
                "Access":  "background:#1e8449;color:#fff",
                "Watch":   "background:#b7770d;color:#fff",
                "Reserve": "background:#922b21;color:#fff",
            }.get(_wd.get("aware",""), "background:#888;color:#fff")

            # Reason-specific detail — "intermediate_culture" is skipped here
            # since it's already covered once by the shared note above.
            _detail = ""
            if _wreason == "renal_adjustment":
                _rl = _wd.get("renal_limit","-")
                _rn = _esc(_ar2en(_wd.get("renal_note",""), _EN))
                _detail = f'{_T["renal_adj"]} {_rl} ml/min' + (f' — {_rn}' if _rn else '')
            elif _wreason == "esbl_bli_uti_only":
                _esbl_txt = (_wd.get("esbl_note_en") if _EN and _wd.get("esbl_note_en")
                             else _wd.get("esbl_note","ESBL organism — BLI combo for uncomplicated UTI only"))
                _detail = _esc(_ar2en(_esbl_txt, _EN))
            elif _wreason != "intermediate_culture":
                _detail = _esc(_ar2en(_wd.get("renal_note","") or _wd.get("note",""), _EN))

            H.append(
                # flex:1 1 42mm → chips grow to fill each row evenly (fixes poor
                # distribution when few drugs); min-width forces a clean wrap; max-width
                # keeps a lone chip from spanning the whole page; overflow:hidden +
                # word wrapping on the name stop long drug names spilling past the
                # right margin.
                '<div style="flex:1 1 42mm;min-width:40mm;max-width:92mm;padding:0.5mm 2mm;'
                'border-radius:1.5mm;background:#fef9e7;border:0.5pt solid #b7770d;'
                'overflow:hidden;page-break-inside:avoid">'
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:1.5mm;min-width:0">'
                f'<b style="font-size:8pt;color:#7d6608;min-width:0;overflow-wrap:anywhere;word-break:break-word">{_wname}</b>'
                '<span style="padding:0.1mm 1.5mm;border-radius:1.5mm;font-size:6pt;flex:0 0 auto;'
                f'font-weight:bold;white-space:nowrap;{_waw_style}">{_waw}</span>'
                '</div>'
                + (f'<div style="font-size:6.5pt;color:#555;margin-top:0.2mm;line-height:1.3;overflow-wrap:anywhere">{_detail[:90]}</div>'
                   if _detail else '')
                + '</div>'
            )
        H.append('</div>')

    # ── Interactions (compact) ─────────────────────────────────────────
    if interactions:
        H.append(f'<div class="sec-ttl" style="margin-top:0.6mm">{_T["interactions"]}</div>'
                 '<div class="alert al-warn">'
                 + '<br>'.join(f'<span style="font-size:9pt">{_esc(ia)}</span>'
                               for ia in (_ar2en(x, _EN) for x in interactions[:4]))
                 + '</div>')

    # 2-column equal — Treatment Duration LEFT, Pathogenicity RIGHT (mirrored layout)
    H.append('<div class="grid2" style="margin-top:0.6mm">')

    # ── Treatment Duration (now left column) ──────────────────────────────
    H.append('<div class="g2l">')
    if duration_data:
        d = duration_data
        H.append('<div class="sec-ttl">Treatment Duration</div>')
        std = d.get("standard_days", d.get("standard","?"))
        H.append('<table class="compact-tbl">'
                 f'<tr><td class="lbl">Protocol</td><td>{_esc(d.get("label",""))}</td></tr>'
                 f'<tr><td class="lbl">Standard</td><td><b style="font-size:12pt">{std} days</b></td></tr>'
                 f'<tr><td class="lbl">Range</td><td>{d.get("min_days","?")}–{d.get("max_days","?")} days</td></tr>'
                 f'<tr><td class="lbl">IV/PO Split</td><td class="ltr">IV:{d.get("iv_days",0)}d · PO:{d.get("po_days",0)}d</td></tr>'
                 '</table>')
        if d.get("notes"):
            _note = annotate_regimen_note(d["notes"], sir_map, lang=lang)
            H.append(f'<div class="alert al-info" style="font-size:8pt;margin-top:0.5mm">📋 {_esc(_note[:300])}</div>')
        if d.get("follow_up_culture"):
            H.append('<div class="alert al-warn" style="font-size:8.5pt">🔄 Follow-up culture recommended after treatment</div>')
        H.append(f'<div style="font-size:8pt;color:#888;margin-top:1mm">📚 {_esc(d.get("ref",""))}</div>')
    else:
        H.append('<div class="sec-ttl">Treatment Duration</div>')
        H.append('<div class="alert al-info" style="font-size:9pt">Select severity level to see treatment duration</div>')
    H.append('</div>')

    # ── Pathogenicity (now right column, expanded) ────────────────────────
    H.append('<div class="g2r">')
    if patho_assessment:
        sc     = patho_assessment.get("score",0)
        verd   = _esc(patho_assessment.get("verdict",""))
        interp = _esc(_xlate_patho(patho_assessment.get("interpretation","")))
        flags  = patho_assessment.get("special_flags",[])
        recs   = [_esc(_xlate_patho(r)) for r in patho_assessment.get("recommendations",[])]
        fpos   = patho_assessment.get("factors_pos",[])
        fneg   = patho_assessment.get("factors_neg",[])
        clr2   = _score_color(sc)

        H.append('<div class="sec-ttl">Pathogenicity Assessment</div>')
        # Score bar
        H.append('<div class="score-bar"><div class="score-fill" '
                 f'style="width:{sc}%;background:{clr2}"></div></div>')
        H.append(f'<div style="font-size:10pt;margin:0.5mm 0;font-weight:bold;color:{clr2}">{sc}% — {verd}</div>')
        # Interpretation
        if interp:
            H.append(f'<div style="font-size:9pt;color:#444;margin-bottom:0.5mm">{interp[:160]}</div>')
        # Flags
        flag_msgs = {
            "CSF_ALWAYS_SIGNIFICANT": ("al-danger", "CSF — Any growth significant (sterile site)"),
            "ABU_NO_TREAT":  ("al-warn",   "ABU — Do NOT Treat (IDSA 2019)"),
            "ABU_TREAT":     ("al-danger", "ABU — TREAT (High-risk)"),
            "MW_REJECT":     ("al-danger", "Specimen REJECTED — Repeat"),
            "MW_ADEQUATE":   ("al-info",   "Murray-Washington: Adequate"),
            "MW_MIXED":      ("al-warn",   "Murray-Washington: Mixed quality"),
            "SIRS_HIGH":     ("al-danger", "SIRS ≥3 — Sepsis Probable"),
            "SIRS_MET":      ("al-warn",   "SIRS 2 — Bacteremia Possible"),
            "PEDIATRIC_UTI": ("al-info",   "Pediatric threshold applied"),
        }
        for fl, (cls, msg) in flag_msgs.items():
            if fl in flags:
                H.append(f'<div class="alert {cls}" style="font-size:8.5pt;margin:0.3mm 0">{msg}</div>')
        # Supporting factors (compact)
        if fpos:
            H.append(f'<div style="font-size:8.5pt;color:#1e8449;margin-top:1mm"><b>{_T["supporting"]}</b></div>')
            for f in fpos[:3]:
                H.append(f'<div style="font-size:8.5pt;color:#1e8449">{_esc(f[:80])}</div>')
        # Against factors
        if fneg:
            H.append(f'<div style="font-size:8.5pt;color:#b7770d;margin-top:0.5mm"><b>{_T["against"]}</b></div>')
            for f in fneg[:3]:
                H.append(f'<div style="font-size:8.5pt;color:#b7770d">{_esc(f[:80])}</div>')
        # Recommendations
        if recs:
            H.append(f'<div style="font-size:8.5pt;font-weight:bold;margin-top:0.5mm">{_T["recs"]}</div>')
            for r in recs[:3]:
                H.append(f'<div style="font-size:8.5pt">• {r[:100]}</div>')
    else:
        # Non-urine: show ESBL / MDR / resistance summary instead of pathogenicity
        _is_urine_pdf = classify_specimen(specimen) == "urine"
        if _is_urine_pdf:
            H.append('<div class="sec-ttl">Pathogenicity Assessment</div>')
            H.append('<div class="alert al-info" style="font-size:9pt">Run Pathogenicity Assessment in the app to see score</div>')
        else:
            H.append('<div class="sec-ttl">Organism Resistance Profile</div>')
            # ESBL / Mechanism
            if esbl_result and esbl_result.get("probability") not in ("low", None):
                _ep3 = esbl_result.get("probability")
                _em3 = _esc(_ar2en(esbl_result.get("mechanism", ""), _EN))
                _ec3 = esbl_result.get("confidence", 0)
                _ed3 = _esc(_ar2en(esbl_result.get("detail",""), _EN))
                if _ep3 == "carbapenemase":
                    H.append(f'<div class="alert al-danger" style="font-size:8.5pt"><b>🚨 {_em3}</b> ({_ec3}%)</div>')
                    H.append(f'<div style="font-size:8pt;color:#922b21">{_ed3[:130]}</div>')
                elif _ep3 in ("high","ampc"):
                    _l3 = "AmpC β-Lactamase" if _ep3 == "ampc" else "ESBL Producer"
                    H.append(f'<div class="alert al-danger" style="font-size:8.5pt"><b>⚠️ {_l3}</b> ({_ec3}%) — {_em3}</div>')
                    H.append(f'<div style="font-size:8pt;color:#555">{_ed3[:130]}</div>')
                elif _ep3 == "moderate":
                    H.append(f'<div class="alert al-warn" style="font-size:8.5pt"><b>🔶 ESBL Suspected</b> ({_ec3}%)</div>')
                    H.append(f'<div style="font-size:8pt;color:#555">{_ed3[:130]}</div>')
            # MDR level
            if mdr_result and mdr_result.get("level"):
                _ml3  = mdr_result["level"]
                _mi3  = MDR_INFO.get(_ml3, {})
                _clr3 = "#922b21" if _ml3 in ("XDR","PDR") else "#b7770d"
                H.append(f'<div style="font-size:9pt;font-weight:bold;color:{_clr3};margin-top:1mm">'
                         f'{_mi3.get("icon","")} {_mi3.get("label","")}</div>')
                H.append(f'<div style="font-size:8pt;color:#555">'
                         f'Resistant {mdr_result["resistant_count"]}/{mdr_result["total_tested"]} categories: '
                         f'{_esc(", ".join(mdr_result.get("resistant_categories",[])[:4]))}</div>')
            # Phenotypes
            if phenotypes:
                for _ph3 in phenotypes[:3]:
                    _phn3 = _esc(_ar2en(_ph3.get("phenotype",""), _EN))
                    H.append(f'<div style="font-size:8.5pt;color:#6e2fa0;margin-top:0.5mm">🔬 {_phn3}</div>')
            # No resistance info → show full Susceptibility Summary
            if (not esbl_result or esbl_result.get("probability") in ("low", None)) \
               and not (mdr_result and mdr_result.get("level")) \
               and not phenotypes:
                H.append('<div class="sec-ttl">Susceptibility Summary</div>')
                # ── AST stats ──────────────────────────────────────────────
                _s_n = sum(1 for v in sir_map.values() if v == "S")
                _i_n = sum(1 for v in sir_map.values() if v == "I")
                _r_n = sum(1 for v in sir_map.values() if v == "R")
                _tot = len(sir_map)
                _gram_txt = ("Gram-positive organism"
                             if (mdr_result or {}).get("gram") == "positive"
                             else "Gram-negative organism"
                             if (mdr_result or {}).get("gram") == "negative"
                             else "")
                _access_n = sum(1 for d in allowed if d.get("aware") == "Access")
                _watch_n  = sum(1 for d in allowed if d.get("aware") == "Watch")
                _res_n    = sum(1 for d in allowed if d.get("aware") == "Reserve")
                _aware_str = (
                    (f"{_access_n} Access" if _access_n else "")
                    + (" · " if _access_n and (_watch_n or _res_n) else "")
                    + (f"{_watch_n} Watch" if _watch_n else "")
                    + (" · " if _watch_n and _res_n else "")
                    + (f"{_res_n} Reserve" if _res_n else "")
                )
                _pct_s = int(_s_n / _tot * 100) if _tot else 0
                _bar_clr = "#1e8449" if _pct_s >= 60 else "#b7770d" if _pct_s >= 40 else "#922b21"
                H.append(
                    f'<div class="score-bar" style="margin:1mm 0">'
                    f'<div class="score-fill" style="width:{_pct_s}%;background:{_bar_clr}"></div></div>'
                )
                H.append(
                    '<table style="width:100%;border-collapse:collapse;font-size:9pt;margin-top:0.5mm">'
                    f'<tr><td style="padding:0.5mm 1mm;color:#1e8449">✅ Sensitive</td>'
                    f'<td style="padding:0.5mm 1mm;font-weight:bold;color:#1e8449">{_s_n} agents</td>'
                    f'<td style="padding:0.5mm 1mm;font-size:8pt;color:#888">{_pct_s}%</td></tr>'
                    + (f'<tr><td style="padding:0.5mm 1mm;color:#b7770d">🟡 Intermediate</td>'
                       f'<td style="padding:0.5mm 1mm;font-weight:bold;color:#b7770d">{_i_n} agent{"s" if _i_n!=1 else ""}</td>'
                       f'<td></td></tr>' if _i_n else "")
                    + f'<tr><td style="padding:0.5mm 1mm;color:#922b21">❌ Resistant</td>'
                      f'<td style="padding:0.5mm 1mm;font-weight:bold;color:#922b21">{_r_n} agent{"s" if _r_n!=1 else ""}</td>'
                      f'<td></td></tr>'
                    '</table>'
                )
                H.append('<hr class="dv" style="margin:0.8mm 0">')
                if _gram_txt:
                    H.append(f'<div style="font-size:9pt;color:#1a1a2e;margin:0.3mm 0">'
                             f'🦠 {_gram_txt}</div>')
                H.append(f'<div style="font-size:9pt;color:#0d3b66;margin:0.3mm 0">'
                         f'Pattern: <b>Non-MDR / Susceptible</b></div>')
                if _aware_str:
                    H.append(f'<div style="font-size:9pt;color:#555;margin:0.3mm 0">'
                             f'AWaRe: {_aware_str}</div>')
                H.append('<hr class="dv" style="margin:0.8mm 0">')
                H.append(
                    '<div class="alert al-info" style="font-size:8.5pt">'
                    '📋 No ESBL / AmpC / Carbapenemase markers detected.<br>'
                    '<span style="font-size:8pt">Standard culture-directed therapy applicable. '
                    'Follow recommended regimen above.</span></div>'
                )
    H.append('</div></div>')

    # ── PREGNANCY — USE WITH CAUTION  (dedicated section) ─────────────────
    if is_preg and preg_warn_items:
        H.append('<hr class="dv">')
        H.append(
            '<div class="sec-ttl" style="color:#7d3c98;border-bottom-color:#7d3c98">'
            f'{_T["pregnancy"]} &nbsp;'
            '<span style="font-size:7pt;font-weight:normal;color:#888">'
            f'{_T["preg_sub"]}</span></div>'
        )
        for _pw in preg_warn_items:
            _pname = _esc(_pw.get("name", ""))
            _paw   = _esc(_pw.get("aware", ""))
            _pnote = (_pw.get("preg_note") or "").strip()
            H.append(
                '<div style="margin:0.3mm 0;padding:0.8mm 2.5mm;border-radius:2mm;'
                'border:1pt solid #c39bd3;background:#f5eef8;page-break-inside:avoid">'
                '<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<b style="font-size:10.5pt;color:#6c3483">{_pname}</b>'
                '<span style="padding:0.3mm 2.5mm;border-radius:2mm;font-size:8pt;'
                f'font-weight:bold;background:#7d3c98;color:#fff">{_paw}</span>'
                '</div>'
            )
            # Use English note if lang=en
            if _EN and _pw.get("preg_note_en"):
                _pnote = _pw.get("preg_note_en").strip()
            if _pnote:
                # Each line of the note on its own row
                for _line in _pnote.splitlines():
                    _line = _line.strip()
                    if not _line:
                        continue
                    # Color-code ⛔ / ✅ / ⚠️ lines
                    if _line.startswith("⛔"):
                        _lcolor = "#922b21"; _lbg = "#fdf2f2"
                    elif _line.startswith("✅"):
                        _lcolor = "#1e8449"; _lbg = "#eafaf1"
                    elif _line.startswith("⚠"):
                        _lcolor = "#b7770d"; _lbg = "#fef9e7"
                    elif _line.startswith(">>>"):
                        _lcolor = "#444";   _lbg = "#f0f0f0"
                    else:
                        _lcolor = "#444";   _lbg = "transparent"
                    H.append(
                        f'<div style="font-size:9pt;color:{_lcolor};'
                        f'background:{_lbg};padding:0.3mm 2mm;margin-top:0.5mm;'
                        f'border-radius:1mm">{_esc(_xlate_preg_note(_line))}</div>'
                    )
            H.append('</div>')

    # Combination + Hepatic (compact)
    if combo_suggestions:
        H.append('<hr class="dv" style="margin:0.5mm 0"><div class="sec-ttl">Combination Therapy — MDR</div>')
        for cs in combo_suggestions[:2]:
            data = cs["data"]
            H.append('<div class="alert al-danger" style="font-size:8.5pt">'
                     f'<b>{_esc(data["urgency"])} — {_esc(data["title"])}</b></div>')
            for opt in data["options"][:3]:
                avoid = "AVOID" in opt.get("evidence","") or "AVOID" in opt["combo"].upper()
                H.append(f'<div style="font-size:8.5pt;margin:0.3mm 0;color:{"#922b21" if avoid else "#1a1a2e"}">'
                         f'{"🚫 " if avoid else "• "}<b>{_esc(opt["combo"])}</b>'
                         f' <span style="color:#888">({_esc(opt["evidence"])})</span></div>')

    if is_hepatic and hepatic_recs:
        action_recs = [r for r in hepatic_recs if r.get("requires_action")][:3]
        if action_recs:
            H.append(f'<hr class="dv" style="margin:0.5mm 0"><div class="sec-ttl">Hepatic Dosing — CP-{_esc(child_pugh)}</div>')
            for r in action_recs:
                cls4 = "danger-val" if "Avoid" in r["level"] else "warn-val"
                H.append('<div style="font-size:9pt;margin:0.3mm 0">'
                         f'<b class="{cls4}">{_esc(r["name"])}</b>: {_esc(r["recommendation"])}</div>')

    # Footer
    H.append("""<hr class="dv" style="margin-top:1mm">
<div class="grid2">
  <div class="g2l" style="font-size:8pt;color:#666">
    <b>References:</b> CLSI 2026 | EUCAST 2026 | IDSA AMR 2025 | WHO AWaRe 2025 | Sanford 2025 | BNF 2025 | Egypt Nat. Guidelines
  </div>
  <div class="g2r" style="font-size:8pt;color:#666">
    <b>Disclaimer:</b> Clinical decision support only. Treatment decisions are the sole responsibility of the treating physician.
  </div>
</div>

</div></body></html>""")

    try:
        return _wp.HTML(string="".join(H)).write_pdf()
    except Exception as _exc:
        logger.debug("suppressed exception: %s", _exc)
        return None

def generate_decision_tree_image(
    patient_name:    str,
    age:             int,
    sex:             str,
    weight:          float,
    cl_cr:           float,
    is_renal:        bool,
    is_preg:         bool,
    organism:        str,
    specimen:        str,
    first_line:      List[str],
    preferred:       List[str],
    use_caution:     List[str],
    contraindicated: List[str],
    reserve:         List[str],
    notes:           List[str],
    colony_count:    str = "",
    date_in:         str = "",
    pus_cells:       str = "",
    rbcs:            str = "",
    lab_name:        str = "Orange Lab",
    lab_city:        str = "",
    mdr_result:          Optional[Dict] = None,
    esbl_result:         Optional[Dict] = None,
    phenotypes:          Optional[List] = None,
    referring_physician: str = "",
    culture_condition:   str = "Aerobic",
    microbiologist:      str = "",
) -> bytes:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow غير متاح — أضف Pillow لـ requirements.txt")

    # ── Scale & Canvas ────────────────────────────────────────────────────────
    # A4 landscape = 297mm × 210mm  @ 200 DPI = 2339 × 1654 px
    # نطرح 10mm من كل جهة → 277mm × 190mm = 2181 × 1496 px
    # أصغر من A4 بـ ~20mm → يُطبع بدون قص
    S  = 2                       # 2× scale → جودة طباعة جيدة
    W  = 2181                    # 277mm @ 200 DPI  (أصغر من A4 بـ 20mm)
    H  = 1496                    # 190mm @ 200 DPI  (أصغر من A4 بـ 20mm)
    P  = 14   * S                # padding
    G  = 8    * S                # gap

    # ── Color Palette (identical to reference) ────────────────────────────────
    BG         = (248, 250, 252)
    WHITE      = (255, 255, 255)
    DARK       = (28,  32,  40)
    GRAY       = (95, 100, 112)
    LIGHT_GRAY = (190, 195, 205)

    NAVY       = (4,   26,  63)
    PURPLE_BD  = (120, 75, 178);  PURPLE_BG  = (247, 243, 254)
    GREEN_BD   = (45, 138,  68);  GREEN_BG   = (236, 252, 240);  GREEN_TXT  = (20,  95,  40)
    AMBER_BD   = (195,140,  30);  AMBER_BG   = (255, 250, 228);  AMBER_TXT  = (120,  80,   0)
    RED_BD     = (183, 52,  52);  RED_BG     = (255, 237, 234);  RED_TXT    = (148,  30,  30)
    BLUE_BD    = (35,  90, 172);  BLUE_BG    = (234, 244, 255);  BLUE_TXT   = (15,   55, 145)
    ALERT_BD   = (205,115,  50);  ALERT_BG   = (255, 248, 232);  ALERT_TXT  = (130,  60,   5)
    SPEC_BD    = (35,  90, 172);  SPEC_BG    = (234, 244, 255)
    MICRO_BD   = (30, 130,  65);  MICRO_BG   = (234, 252, 238)
    FL_BD      = (190,138,  28);  FL_BG      = (255, 250, 225)
    FOOT_BD    = (185,192,200);   FOOT_BG    = (247, 249, 251)

    # ── Fonts (all scaled) ────────────────────────────────────────────────────
    def gf(size: int, bold: bool = False):
        """
        Robust font loader with comprehensive fallbacks.
        Priority: Liberation Sans → DejaVu → NotoSans → Amiri → auto-discover
        Liberation/DejaVu give the clean sans-serif look of the old images.
        NotoSans/Amiri are fallbacks for Streamlit Cloud if Liberation not found.
        """
        import os as _os
        _b = "Bold" if bold else "Regular"
        paths = [
            # ── DejaVu Sans FIRST — supports Arabic Unicode (fonts-dejavu-core) ─
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
            f"/usr/share/fonts/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
            f"/usr/share/fonts/truetype/dejavu-sans/DejaVuSans{'-Bold' if bold else ''}.ttf",
            # ── Liberation Sans (fonts-liberation in packages.txt) ──────────────
            f"/usr/share/fonts/truetype/liberation/LiberationSans-{_b}.ttf",
            f"/usr/share/fonts/truetype/liberation2/LiberationSans-{_b}.ttf",
            f"/usr/share/fonts/liberation/LiberationSans-{_b}.ttf",
            # ── Noto Sans (fonts-noto-core in packages.txt) — clean sans-serif ──
            f"/usr/share/fonts/truetype/noto/NotoSans-{_b}.ttf",
            f"/usr/share/fonts/truetype/noto/NotoSans{'Bold' if bold else 'Regular'}.ttf",
            "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
            "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            # ── Amiri (fonts-hosny-amiri in packages.txt) — Arabic+Latin ────────
            f"/usr/share/fonts/opentype/fonts-hosny-amiri/Amiri-{_b}.ttf",
            f"/usr/share/fonts/opentype/fonts-hosny-amiri/amiri-{'bold' if bold else 'regular'}.ttf",
            f"/usr/share/fonts/truetype/amiri/Amiri-{_b}.ttf",
            # ── Other common fonts ───────────────────────────────────────────────
            f"/usr/share/fonts/truetype/freefont/FreeSans{'Bold' if bold else ''}.ttf",
            f"/usr/share/fonts/truetype/ubuntu/Ubuntu-{'B' if bold else 'R'}.ttf",
        ]
        for p in paths:
            if _os.path.isfile(p):
                try:
                    return ImageFont.truetype(p, size * S)
                except Exception as _exc:
                    logger.debug("suppressed exception: %s", _exc)
                    continue
        # Auto-discover: search for ANY usable sans-serif font
        for _fdir in ["/usr/share/fonts/truetype", "/usr/share/fonts/opentype",
                      "/usr/share/fonts"]:
            if not _os.path.isdir(_fdir):
                continue
            try:
                for _root, _, _files in _os.walk(_fdir):
                    for _f in sorted(_files):   # sorted = deterministic order
                        if not _f.lower().endswith((".ttf", ".otf")):
                            continue
                        _fl = _f.lower()
                        if any(k in _fl for k in
                               ("liberation", "dejavu", "notosans", "noto-sans",
                                "ubuntu", "freesans", "amiri", "arial", "sans")):
                            try:
                                return ImageFont.truetype(
                                    _os.path.join(_root, _f), size * S)
                            except Exception as _exc:
                                logger.debug("suppressed exception: %s", _exc)
                                continue
            except Exception as _exc:
                logger.debug("suppressed exception: %s", _exc)
                continue
        return ImageFont.load_default()

    F_HEADER  = gf(20, True)
    F_TITLE   = gf(15, True)
    F_SUBTITL = gf(12, True)
    F_TEXT    = gf(12)
    F_SMALL   = gf(10)
    F_ORG     = gf(26, True)
    F_SUMNUM  = gf(20, True)
    F_BADGE   = gf(9,  True)

    def fh(f) -> int:
        return f.size if hasattr(f, "size") else 14 * S

    def tw(draw, text, font) -> float:
        try:
            return draw.textlength(text, font=font)
        except Exception as _exc:
            logger.debug("suppressed exception: %s", _exc)
            return len(text) * fh(font) * 0.6

    # ── Arabic text helper ────────────────────────────────────────────────────
    def _fix_arabic(text: str) -> str:
        """
        Reshape Arabic text for Pillow.
        reshape() connects letters correctly.
        get_display() reverses word order — NOT used here to avoid reversal.
        """
        if not text:
            return ""
        if not ARABIC_SUPPORT:
            return str(text)
        try:
            return _arabic_reshaper_mod.reshape(str(text))
        except Exception as _exc:
            logger.debug("suppressed exception: %s", _exc)
            return str(text)

    def rbox(draw, box, bg, bd, radius=14, width=3):
        draw.rounded_rectangle(
            [box[0], box[1], box[2], box[3]],
            radius=radius * S, fill=bg, outline=bd, width=width * S
        )

    def text_wrap(draw, x, y, text, font, fill, max_w, gap=4, max_y=None, min_size=7):
        """
        Word-wraps text within max_w. If max_y is given and the wrapped
        text would cross that boundary at the current font size, the font
        is progressively shrunk (down to min_size) so the text always
        stays inside its box; if it still doesn't fit at min_size, the
        last visible line is truncated with "…" instead of overflowing
        past the border.
        """
        text = _fix_arabic(text)   # reshape Arabic before wrapping

        def _wrap(f):
            words = text.split()
            lines, cur = [], ""
            for w in words:
                trial = (cur + " " + w).strip()
                if tw(draw, trial, f) <= max_w:
                    cur = trial
                else:
                    if cur: lines.append(cur)
                    cur = w
            if cur: lines.append(cur)
            return lines

        f = font
        lines = _wrap(f)
        lh = fh(f) + gap * S

        if max_y is not None and (y + lh * len(lines)) > max_y:
            nominal = max(min_size, int(fh(font) / S) - 1)
            for step in range(nominal, min_size - 1, -1):
                f2 = gf(step)
                lines2 = _wrap(f2)
                lh2 = fh(f2) + gap * S
                if (y + lh2 * len(lines2)) <= max_y:
                    f, lines, lh = f2, lines2, lh2
                    break
            else:
                f = gf(min_size)
                lines = _wrap(f)
                lh = fh(f) + gap * S
                max_lines = max(1, int((max_y - y) // lh))
                if len(lines) > max_lines:
                    lines = lines[:max_lines]
                    lines[-1] = lines[-1].rstrip() + "…"

        for line in lines:
            draw.text((x, y), line, fill=fill, font=f)
            y += lh
        return y

    # AWaRe colors — Access أخضر، Watch برتقالي
    AWARE_NAME_COLORS = {
        "[A]": (20, 138, 68),    # أخضر — Access
        "[W]": (180, 100,  0),   # برتقالي — Watch
    }

    def section_box(draw, box, title, title_color, subtitle, items, bg, bd,
                    ft, fs, fi):
        x1, y1, x2, y2 = box
        rbox(draw, box, bg, bd, radius=16, width=3)
        draw.text((x1 + 14*S, y1 + 12*S), _fix_arabic(title), fill=title_color, font=ft)
        cy = y1 + 12*S + fh(ft) + 6*S
        if subtitle:
            draw.text((x1 + 14*S, cy), _fix_arabic(subtitle), fill=(110,115,125), font=fs)
            cy += fh(fs) + 4*S
        draw.line([(x1 + 10*S, cy), (x2 - 10*S, cy)], fill=bd, width=1*S)
        cy += 8*S
        for item in items:
            if cy + fh(fi) + 7*S > y2 - 8*S:
                draw.text((x1 + 14*S, cy), "…", fill=LIGHT_GRAY, font=fi)
                break
            # استخراج badge [A] أو [W]
            badge = ""
            display_name = item
            for b in ["[A]", "[W]"]:
                if item.endswith(b):
                    badge = b
                    display_name = item[:-len(b)].rstrip()
                    break
            # لون الاسم حسب AWaRe
            name_color = AWARE_NAME_COLORS.get(badge, DARK)
            cy = text_wrap(draw, x1 + 14*S, cy, f"• {display_name}",
                           fi, name_color, x2 - x1 - 26*S, gap=5, max_y=y2-8*S)

    # ── Build Image ───────────────────────────────────────────────────────────
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # ── 1. HEADER ─────────────────────────────────────────────────────────────
    rbox(draw, (P, 6*S, W-P, 62*S), NAVY, NAVY, radius=12, width=1)
    htxt = f"🔬  {lab_name.upper()} – MICROBIOLOGY DEPARTMENT"
    hw   = tw(draw, htxt, F_HEADER)
    draw.text(((W - hw)//2, 16*S), _fix_arabic(htxt), fill=WHITE, font=F_HEADER)

    # ── 2. CULTURE BOX (center) ───────────────────────────────────────────────
    CB = (368*S, 72*S, 870*S, 198*S)
    rbox(draw, CB, WHITE, NAVY, radius=14, width=2)

    ctype = "Culture/ Growth"
    ctw_  = tw(draw, ctype, F_SUBTITL)
    draw.text(((CB[0]+CB[2]-ctw_)//2, CB[1]+12*S), _fix_arabic(ctype), fill=DARK, font=F_SUBTITL)

    ow = tw(draw, organism, F_ORG)
    draw.text(((CB[0]+CB[2]-ow)//2, CB[1]+38*S), _fix_arabic(organism), fill=NAVY, font=F_ORG)

    # Colony count under organism — Date In inline
    cc_parts = []
    if colony_count:
        cc_parts.append(f"Colony Count: {colony_count}")
    if date_in:
        cc_parts.append(f"Date In: {date_in}")
    if cc_parts:
        cc_txt = "   |   ".join(cc_parts)
        cctw   = tw(draw, cc_txt, F_TEXT)
        draw.text(((CB[0]+CB[2]-cctw)//2, CB[1]+38*S+fh(F_ORG)+6*S),
                  cc_txt, fill=(90, 90, 140), font=F_TEXT)

    # ── 3. PATIENT BOX (left) ─────────────────────────────────────────────────
    PB = (P, 72*S, 358*S, 198*S)
    rbox(draw, PB, PURPLE_BG, PURPLE_BD, radius=14, width=3)
    # No "PATIENT DETAILS" header — direct fields
    p_lines = []
    if patient_name:
        p_lines.append(f"Patient Name:  {patient_name}")
    p_lines.append(f"Sex / Age:     {'Male' if sex == 'Male' else 'Female'}, {_fmt_age(age, 'yrs')}")
    if referring_physician:
        p_lines.append(f"Referred by:   Dr/ {referring_physician}")
    if is_renal:
        p_lines.append(f"Renal:         IMPAIRED  CrCl:{cl_cr:.0f}")
    else:
        p_lines.append("Renal:         Normal")
    p_lines.append("Hepatic:       Normal")
    if sex == "Female" and 12 <= age <= 55:
        p_lines.append(f"Pregnancy:     {'Yes' if is_preg else 'No'}")

    py = 78*S
    for ln in p_lines[:7]:
        draw.text((P+14*S, py), _fix_arabic(f"• {ln}"), fill=DARK, font=F_TEXT)
        py += fh(F_TEXT) + 5*S

    # ── 4. ALERT BOX (right) — يشمل MDR/ESBL/Phenotype ──────────────────────
    AB = (885*S, 72*S, W-P, 198*S)

    # لون المربع حسب خطورة الـ phenotype
    _ph_names   = [p.get("phenotype","") for p in (phenotypes or [])]
    _has_cre    = any(p in _ph_names for p in ["CRE","CRAB","CRPA"])
    _has_mdr    = (mdr_result or {}).get("level") in ("XDR","PDR")
    _esbl_prob  = (esbl_result or {}).get("probability")
    _has_esbl   = _esbl_prob in ("high","carbapenemase","ampc")

    if _has_cre or _has_mdr:
        AB_BG = (255, 237, 234);  AB_BD = (183, 52, 52);   AB_TXT = (148, 30, 30)
    elif _has_esbl:
        AB_BG = (255, 248, 232);  AB_BD = (205,115, 50);   AB_TXT = (130, 60,  5)
    else:
        AB_BG = ALERT_BG;         AB_BD = ALERT_BD;         AB_TXT = ALERT_TXT

    rbox(draw, AB, AB_BG, AB_BD, radius=14, width=3)

    # عنوان ديناميكي
    if _has_cre:
        alert_title = "🚨 CRE / XDR ALERT"
    elif _has_mdr:
        alert_title = "🔴 MDR/XDR ALERT"
    elif _esbl_prob == "ampc":
        alert_title = "⚠  AmpC ALERT"
    elif _has_esbl:
        alert_title = "⚠  ESBL ALERT"
    else:
        alert_title = "⚠  IMPORTANT ALERT"

    draw.text((AB[0]+12*S, 72*S+12*S), _fix_arabic(alert_title), fill=AB_TXT, font=F_SUBTITL)
    alerts: List[str] = []

    # ── MDR/XDR/PDR ──────────────────────────────────────────────────────────
    mdr_lvl = (mdr_result or {}).get("level")
    if mdr_lvl:
        mdr_cats = (mdr_result or {}).get("resistant_categories", [])
        rc = (mdr_result or {}).get("resistant_count", 0)
        rt = (mdr_result or {}).get("total_tested", 0)
        alerts.append(f"{mdr_lvl}: Resistant {rc}/{rt} categories")
        if mdr_cats:
            alerts.append(f"R-cats: {', '.join(mdr_cats[:3])}")

    # ── ESBL / AmpC / Carbapenemase ────────────────────────────────────────────
    _esbl_mech = (esbl_result or {}).get("mechanism", "")
    if _esbl_prob == "carbapenemase":
        if "OXA-48" in _esbl_mech:
            alerts.append("Possible OXA-48 carbapenemase")
        else:
            alerts.append("Carbapenemase (KPC/MBL/OXA) possible!")
        alerts.append("Send to reference lab immediately.")
    elif _esbl_prob == "ampc":
        alerts.append("Possible AmpC β-lactamase")
        alerts.append("Avoid 3rd-gen cephalosporins; use Cefepime/Carbapenem")
    elif _esbl_prob == "high":
        alerts.append("High probability ESBL Producer")
        alerts.append("Use Carbapenems for severe cases")
    elif _esbl_prob == "moderate":
        alerts.append("ESBL confirmation recommended")
        alerts.append("Double Disk Synergy Test")

    # ── Phenotypes ────────────────────────────────────────────────────────────
    for ph in (phenotypes or [])[:2]:
        ph_name = ph.get("phenotype","")
        if ph_name not in ("Possible MRSA",):
            alerts.append(f"Phenotype: {ph_name}")

    # ── Organism-specific baseline alerts ────────────────────────────────────
    org_l = organism.lower()
    if not alerts:  # فقط لو مفيش MDR/ESBL
        if "klebsiella" in org_l:
            alerts += ["Consider ESBL screening",
                       "Natural resistance: Ampicillin"]
        elif "e. coli" in org_l or "coli" in org_l:
            alerts += ["Most common UTI pathogen",
                       "Verify with culture sensitivity"]
        elif "pseudomonas" in org_l:
            alerts += ["High intrinsic resistance",
                       "Anti-pseudomonal agent required"]
        elif "mrsa" in org_l or "staphylococcus" in org_l:
            alerts += ["Check MRSA status",
                       "Vancomycin/Linezolid if MRSA"]
        elif "acinetobacter" in org_l:
            alerts += ["MDR risk — check Carbapenem S/I/R"]
        else:
            alerts = ["Verify sensitivity results."]

    if is_renal:
        alerts.append(f"Renal adj. (CrCl {cl_cr:.0f} ml/min)")
    if is_preg:
        # Pregnancy can be flagged from menarche onward — if it's set, always warn.
        alerts.append("Pregnancy: verify fetal safety")

    ay = 72*S + 12*S + fh(F_SUBTITL) + 8*S
    alert_max_w = AB[2] - AB[0] - 22*S
    for al in alerts[:6]:
        if ay + fh(F_SMALL) + 4*S > AB[3] - 6*S:
            break
        ay = text_wrap(draw, AB[0]+12*S, ay, f"• {al}",
                       F_SMALL, AB_TXT, alert_max_w, gap=4, max_y=AB[3]-6*S)
        ay += 2*S

    # ── 5. ROW 2: Specimen | Microscopic Exam | Clinical Strategy ─────────────
    R2_Y1 = 210*S
    R2_Y2 = 310*S
    r2w   = (W - 2*P - 2*G) // 3

    # Specimen box — no title, direct fields
    # Specimen label — add collection method for Urine
    _img_cat = classify_specimen(specimen)
    _spec_label = specimen
    if _img_cat == "urine":
        _spec_label = f"{specimen} / Mid-Stream"
    spec_items = [
        f"Specimen:      {_spec_label}",
        "Method:        Culture & Sensitivity",
        f"Condition:     {culture_condition}",
    ]
    if microbiologist:
        spec_items.append(f"Microbiologist: Dr/ {microbiologist}")
    # Pus/RBC microscopy is a urine/wound bench finding — never imply it was
    # performed for blood/CSF/sputum/stool specimens.
    if _img_cat in ("urine", "wound"):
        micro_items = [
            f"Pus Cells: {pus_cells if pus_cells else chr(8212)} /HPF",
            f"RBCs:      {rbcs if rbcs else chr(8212)} /HPF",
        ]
    else:
        micro_items = [
            "Pus/RBCs:  N/A for this specimen",
            f"Condition: {culture_condition}",
        ]
    fl_items = first_line[:4] or ["—"]

    r2_data = [
        ("",                   spec_items,  SPEC_BD,  SPEC_BG,  ""),
        ("MICROSCOPIC EXAM",   micro_items, MICRO_BD, MICRO_BG, "🔬"),
        ("CLINICAL STRATEGY", fl_items,    FL_BD,    FL_BG,    "📋"),
    ]
    for i, (title, items, bd, bg, icon) in enumerate(r2_data):
        bx1 = P + i*(r2w+G)
        bx2 = bx1 + r2w
        rbox(draw, (bx1, R2_Y1, bx2, R2_Y2), bg, bd, radius=12, width=2)
        if title:
            draw.text((bx1+12*S, R2_Y1+9*S), _fix_arabic(f"{icon} {title}"), fill=bd, font=F_SUBTITL)
            iy = R2_Y1 + 32*S
        else:
            iy = R2_Y1 + 11*S  # start higher when no title
        for it in items[:5]:
            iy = text_wrap(draw, bx1+14*S, iy, f"• {it}",
                           F_SMALL, DARK, bx2-bx1-24*S, gap=4, max_y=R2_Y2-6*S)

    # ── 6. FOUR MAIN COLUMNS ──────────────────────────────────────────────────
    COL_Y1 = 323*S
    COL_Y2 = H - 115*S
    cw     = (W - 2*P - 3*G) // 4

    # Dynamic column titles based on pregnancy
    avoid_title    = "🚫 AVOID IN PREGNANCY" if is_preg else "🚫 AVOID / CONTRAINDICT."
    avoid_subtitle = "Contraindicated / Not recommended" if is_preg else "Due to other factors"

    columns = [
        ("✅ PREFERRED (SAFE)",  "Preferred oral options",  preferred,       GREEN_BD, GREEN_BG, GREEN_TXT),
        ("⚠️  USE WITH CAUTION", "Use with caution",         use_caution,     AMBER_BD, AMBER_BG, AMBER_TXT),
        (avoid_title,            avoid_subtitle,             contraindicated,  RED_BD,   RED_BG,   RED_TXT),
        ("🛡️  RESERVE (WHO)",     "Last-resort agents (MDR/XDR)", reserve,      BLUE_BD,  BLUE_BG,  BLUE_TXT),
    ]
    for i, (title, subtitle, items, bd, bg, tc) in enumerate(columns):
        bx1 = P + i*(cw+G)
        bx2 = bx1 + cw
        section_box(draw, (bx1, COL_Y1, bx2, COL_Y2),
                    title, tc, subtitle, items or ["—"],
                    bg, bd, F_TITLE, F_SMALL, F_TEXT)

    # ── 7. FOOTER — 4 مربعات متساوية ─────────────────────────────────────────
    FY1 = H - 116*S
    FY2 = H - 8*S
    fw4 = (W - 2*P - 3*G) // 4

    # ① WHO AWaRe
    fx1 = P;  fx2 = fx1 + fw4
    rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1+10*S, FY1+10*S), "WHO AWaRe", fill=DARK, font=F_SUBTITL)
    bx = fx1 + 10*S
    by = FY1 + 30*S
    for label, color in [("ACCESS", GREEN_TXT), ("WATCH", AMBER_TXT), ("RESERVE", RED_TXT)]:
        lw      = tw(draw, label, F_BADGE)
        badge_w = int(lw) + 10*S
        rbox(draw, (bx-2*S, by-2*S, bx+badge_w, by+fh(F_BADGE)+4*S),
             color, color, radius=5, width=1)
        draw.text((bx+3*S, by), label, fill=WHITE, font=F_BADGE)
        bx += badge_w + 5*S
    draw.text((fx1+10*S, by+fh(F_BADGE)+7*S),
              "1st/2nd | Caution | Last resort", fill=GRAY, font=F_SMALL)

    # ② SUMMARY
    fx1 = P + fw4 + G;  fx2 = fx1 + fw4
    rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1+10*S, FY1+10*S), "SUMMARY", fill=DARK, font=F_SUBTITL)
    sum_items = [
        (f"~{len(preferred)}",       "Recommended", GREEN_TXT),
        (f"~{len(use_caution)}",     "Caution",     AMBER_TXT),
        (f"~{len(contraindicated)}", "Avoided",     RED_TXT),
        (f"~{len(reserve)}",         "Reserve",     BLUE_TXT),
    ]
    sw = (fx2 - fx1 - 16*S) // 4
    for j, (num, lbl, clr) in enumerate(sum_items):
        sx = fx1 + 10*S + j * sw
        draw.text((sx, FY1+28*S), num, fill=clr,  font=F_SUMNUM)
        draw.text((sx, FY1+62*S), lbl, fill=GRAY, font=F_SMALL)

    # ③ NOTES
    fx1 = P + 2*(fw4+G);  fx2 = fx1 + fw4
    rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1+10*S, FY1+10*S), "NOTES", fill=DARK, font=F_SUBTITL)
    ny = FY1 + 30*S
    for note in (notes or [])[:5]:
        if ny + fh(F_SMALL) + 3*S > FY2 - 6*S:
            break
        ny = text_wrap(draw, fx1+10*S, ny, f"• {note}",
                       F_SMALL, DARK, fx2-fx1-18*S, gap=3, max_y=FY2-6*S)

    # ④ REFERENCES
    fx1 = P + 3*(fw4+G);  fx2 = W - P
    rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1+10*S, FY1+10*S), "REFERENCES", fill=DARK, font=F_SUBTITL)
    refs = ["EUCAST 2026", "CLSI M100 2026", "IDSA AMR 2025",
            "WHO AWaRe 2025", "Egypt Nat. Guidelines", "BNF 2025 | FDA Labels"]
    ry = FY1 + 30*S
    for ref in refs:
        if ry + fh(F_SMALL) + 3*S > FY2 - 6*S:
            break
        ry = text_wrap(draw, fx1+10*S, ry, f"• {ref}",
                       F_SMALL, DARK, fx2-fx1-18*S, gap=3, max_y=FY2-6*S)
    # ── Export Ultra HD ───────────────────────────────────────────────────────
    buf = io.BytesIO()
    img.save(buf, "PNG", dpi=(200, 200), optimize=False)
    return buf.getvalue()

def generate_report(
    patient_name:    str,
    age:             int,
    sex:             str,
    weight:          float,
    cl_cr:           float,
    is_renal:        bool,
    is_preg:         bool,
    is_hepatic:      bool,
    allowed:         List[Dict],
    warned:          List[Dict],
    banned:          List[Dict],
    preg_warn_items: List[Dict],
    organism:        str,
    specimen:        str,
    interactions:    List[str],
    sir_map:         Dict[str, str],
    colony_count:    str = "",
    date_in:         str = "",
    pus_cells:       str = "",
    rbcs:            str = "",
    lab_name:              str = "Orange Lab",
    lab_city:              str = "",
    patho_assessment:      dict = None,
    show_commercial_names: bool = False,
) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep  = "=" * 60
    sep2 = "-" * 60
    L:   List[str] = []

    lab_hdr = lab_name.upper() if lab_name else "ORANGE LAB"
    L += [sep, f"{lab_hdr} — CLINICAL DECISION REPORT", sep, f"Date     : {now}"]
    if patient_name:
        L.append(f"Patient  : {patient_name}")
    L.append(sep)

    L += ["\nPATIENT DETAILS", sep2,
          f"Age      : {_fmt_age(age, 'years')}",
          f"Gender   : {sex}",
          f"Weight   : {weight} kg",
          f"Renal    : {'IMPAIRED' if is_renal else 'Normal'}"]
    if is_renal:
        if age < 18:
            L.append(f"eGFR     : {cl_cr:.1f} mL/min/1.73m² (Schwartz, {get_renal_severity(cl_cr)})")
        else:
            L.append(f"CrCl     : {cl_cr:.1f} ml/min ({get_renal_severity(cl_cr)})")
    L.append(f"Hepatic  : {'IMPAIRED' if is_hepatic else 'Normal'}")
    if sex == "Female" and (11 <= age <= 55 or is_preg):
        L.append(f"Pregnant : {'Yes' if is_preg else 'No'}")

    L += ["\nCULTURE & MICROSCOPY", sep2,
          f"Specimen : {specimen}"]
    if date_in:
        L.append(f"Date In  : {date_in}")
    L.append(f"Organism : {organism}")
    if colony_count:
        L.append(f"Colony   : {colony_count}")
    if pus_cells:
        L.append(f"Pus Cells: {pus_cells} /HPF")
    if rbcs:
        L.append(f"RBCs     : {rbcs} /HPF")

    if organism in ORGANISM_PROFILE:
        op = ORGANISM_PROFILE[organism]
        if op.get("note"):
            L.append(f"Note       : {op['note']}")
        spec_ctx = (op.get("specimen_context") or {}).get(specimen, "")
        if spec_ctx:
            L.append(f"Context    : {spec_ctx}")
        if op.get("first_line"):
            L.append(f"First-line : {', '.join(op['first_line'])}")
        if op.get("avoid"):
            L.append(f"Avoid      : {', '.join(op['avoid'])}")

    if sir_map:
        L += ["\nSENSITIVITY RESULTS", sep2]
        for drug, result in sorted(sir_map.items()):
            label = {"S": "Sensitive", "R": "Resistant", "I": "Intermediate"}.get(result, result)
            L.append(f"{drug:<40} {label}")

    if interactions:
        L += ["\nINTERACTIONS / WARNINGS", sep2]
        for item in sorted(set(interactions)):
            L.append(f"- {item}")

    # MDR/XDR/PDR + ESBL في التقرير
    if sir_map:
        mdr_r = classify_mdr(organism, sir_map)
        if mdr_r["level"]:
            info = MDR_INFO[mdr_r["level"]]
            L += [f"\n{info['icon']} RESISTANCE CLASSIFICATION: {info['label']}", sep2,
                  info["detail"],
                  f"Resistant ({mdr_r['resistant_count']}/{mdr_r['total_tested']}): "
                  + ", ".join(mdr_r['resistant_categories']),
                  f"Action: {info['action']}", ""]
        esbl_r = predict_esbl(organism, sir_map)
        prob   = esbl_r.get("probability")
        if prob == "carbapenemase":
            L += [f"\n🚨 {esbl_r.get('mechanism','POSSIBLE CARBAPENEMASE PRODUCER').upper()}", sep2,
                  esbl_r["detail"], f"Action: {esbl_r['action']}", ""]
        elif prob == "ampc":
            L += ["\n⚠️  POSSIBLE AmpC β-LACTAMASE PRODUCER", sep2,
                  esbl_r["detail"], f"Action: {esbl_r['action']}", ""]
        elif prob == "high":
            L += ["\n⚠️  HIGH PROBABILITY ESBL PRODUCER", sep2,
                  esbl_r["detail"], f"Action: {esbl_r['action']}", ""]
        elif prob == "moderate":
            L += ["\n🔶 ESBL CONFIRMATION RECOMMENDED", sep2,
                  esbl_r["detail"], f"Action: {esbl_r['action']}", ""]

    L += ["\nRECOMMENDED ANTIBIOTICS", sep]
    if allowed:
        for item in allowed:
            sir_tag  = f" [Culture: {sir_map[item['name']]}]" if sir_map and item['name'] in sir_map else ""
            preg_tag = " [Pregnancy: caution]" if (is_preg and item.get("preg_status") == "Warn") else ""
            L += [f"\n{item['name']}{sir_tag}{preg_tag}", sep2,
                  f"WHO AWaRe : {item.get('aware','-')}",
                  f"Class     : {item.get('class','-')}",
                  f"Route     : {'Oral/PO-friendly' if item.get('high_po') else 'IV/IM only'}"]
            spec_note = (item.get("specimen_notes") or {}).get(specimen, "")
            if spec_note:
                L += [f"Note      : {item.get('note','')}", f"{specimen}   : {spec_note}"]
            else:
                L.append(f"Note      : {item.get('note','')}")
            if is_renal:
                L.append(f"Renal     : {item.get('renal_note','-')}")
            if is_preg and item.get("preg_status") == "Warn":
                pn = (item.get("preg_note") or "").splitlines()
                if pn:
                    L.append(f"Pregnancy : {pn[0]}")
            if show_commercial_names:
                _brands = get_commercial_name(item["name"])
                if _brands:
                    L.append(f"Brands    : {_brands}")
    else:
        L.append("No recommended options after applying all restrictions.")

    if warned:
        L += ["\nDOSE ADJUSTMENT / USE WITH CAUTION", sep]
        if is_renal:
            L.append(f"Patient CrCl = {cl_cr:.1f} ml/min\n")
        for item in warned:
            sir_tag = f" [Culture: {sir_map[item['name']]}]" if sir_map and item['name'] in sir_map else ""
            L += [f"{item['name']}{sir_tag}", sep2, f"WHO AWaRe : {item.get('aware','-')}"]
            if item.get("warning_reason") == "intermediate_culture":
                L.append("Reason    : Intermediate (I) on culture result")
            else:
                L += [f"Renal note: {item.get('renal_note','-')}",
                      f"Limit CrCl: <= {item.get('renal_limit','-')} ml/min"]
            if show_commercial_names:
                _brands = get_commercial_name(item["name"])
                if _brands:
                    L.append(f"Brands    : {_brands}")
            L.append("")

    if is_preg and preg_warn_items:
        L += ["\nPREGNANCY — USE WITH CAUTION", sep]
        for item in preg_warn_items:
            L += [item['name'], sep2]
            L.extend((item.get("preg_note") or "").splitlines())
            L.append("")

    if banned:
        L += ["\nCONTRAINDICATED / INEFFECTIVE", sep]
        grouped: Dict[str, list] = {
            "resistant": [], "renal": [], "pregnancy": [],
            "child": [], "organism": [], "specimen": [], "other": [],
        }
        for item in banned:
            grouped.setdefault(item["category"], []).append(item)
        labels = [
            ("resistant", "[A] RESISTANT IN CULTURE"),
            ("renal",     "[B] CONTRAINDICATED — RENAL IMPAIRMENT"),
            ("pregnancy", "[C] CONTRAINDICATED — PREGNANCY"),
            ("child",     "[D] NOT SUITABLE FOR AGE"),
            ("organism",  f"[E] INEFFECTIVE FOR {organism}"),
            ("specimen",  f"[F] INAPPROPRIATE FOR {specimen.upper()} SPECIMEN"),
            ("other",     "[G] OTHER CONTRAINDICATIONS"),
        ]
        _rendered_cats = set()
        for cat, heading in labels:
            if grouped.get(cat):
                _rendered_cats.add(cat)
                L += [f"\n{heading}", sep2]
                for b in grouped[cat]:
                    L.append(f"- {b['name']} — {b.get('reason_short', '')}")
                    if cat == "renal":
                        dk       = b["name"].lower().replace(" ", "")
                        rendered = False
                        for k, v in RENAL_BAN_REASONS.items():
                            if k in dk:
                                L.extend([f"  {ln}" for ln in v.splitlines()])
                                rendered = True
                                break
                        if not rendered:
                            L.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                    else:
                        L.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                    L.append("")
        # Safety net — never silently drop a banned drug whose category is not
        # in the list above (e.g. a future/unknown category). Every banned item
        # must appear with its reason in the txt report.
        for cat, items in grouped.items():
            if cat in _rendered_cats or not items:
                continue
            L += [f"\n[+] OTHER — {cat.upper()}", sep2]
            for b in items:
                L.append(f"- {b['name']} — {b.get('reason_short', '')}")
                L.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                L.append("")

    # ── Pathogenicity Assessment ──────────────────────────────────────
    if patho_assessment:
        sc    = patho_assessment.get("score", 0)
        verd  = patho_assessment.get("verdict", "")
        interp = patho_assessment.get("interpretation", "")
        recs  = patho_assessment.get("recommendations", [])
        flags = patho_assessment.get("special_flags", [])
        L += ["", "PATHOGENICITY ASSESSMENT", sep2,
              f"Score    : {sc}% — {verd}"]
        if "ABU_DETECTED" in flags:
            L.append("FLAG     : Asymptomatic Bacteriuria (ABU) Detected")
        if "MW_REJECT" in flags:
            L.append("FLAG     : Murray-Washington — Specimen REJECTED")
        elif "MW_ADEQUATE" in flags:
            L.append("FLAG     : Murray-Washington — Adequate Sputum Quality")
        if "SIRS_HIGH" in flags:
            L.append("FLAG     : SIRS >=3 criteria — Sepsis Probable")
        if interp:
            L.append(f"Interp   : {interp}")
        if recs:
            L.append("Recs     :")
            for r in recs:
                L.append(f"  • {r}")

    L += ["\nDISCLAIMER", sep,
          "هذا التقرير أداة مساعدة للقرار الطبي وليس بديلاً عن التقييم السريري.",
          "القرار النهائي للوصف العلاجي يعود للطبيب المعالج.", sep,
          "Guidelines: EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | Egypt National",
          "Route info: BNF 2025 | FDA Labels | WHO AWaRe 2025",
          "WHO AWaRe : Access | Watch | Reserve", sep,
          f"Developed by Dr / Hussein Ali | {lab_name}{(' | ' + lab_city) if lab_city else ''}", sep]
    return "\n".join(L)
