"""Beta-lactam resistance mechanism inference (ESBL / AmpC / carbapenemase).

Returns the same dict shape the UI and the reports already consume
(`probability`, `confidence`, `mechanism`, `markers_R`, `detail`, `action`),
plus one new field the drug-disposition rules key on:

    betalactam_policy
        None            no mechanism-driven restriction
        "esbl"          ESBL phenotype
        "ampc"          derepressed AmpC phenotype
        "cre"           meropenem and/or imipenem resistant Enterobacterales
        "cre_possible"  ertapenem-only resistance, or a carbapenem "I":
                        carbapenem activity is in doubt but NOT disproven

WHY "cre" AND "cre_possible" ARE SEPARATE. Both used to be reported as
probability == "carbapenemase", and that single flag made the disposition
engine remove EVERY beta-lactam, including carbapenems that tested
susceptible. Two real patterns were handled wrongly as a result:

  * Proteus / Morganella / Providencia with imipenem R (or I) only. These
    genera have intrinsically reduced imipenem susceptibility; it says nothing
    about carbapenemase. Meropenem-S and ceftriaxone-S were both taken away.
  * Ertapenem R with meropenem S. Most often ESBL/AmpC plus porin loss. IDSA
    AMR guidance: when no carbapenemase gene has been identified, an isolate
    that is not susceptible to ertapenem but susceptible to meropenem can be
    treated with extended-infusion meropenem. The engine instead removed
    meropenem and left the prescriber with colistin.

So only "cre" suppresses carbapenems that test susceptible; "cre_possible"
keeps them, with a mandatory confirm-first warning.
"""
from __future__ import annotations

from typing import Any, Dict, List

from clinical_data import CARBAPENEMS, ESBL_MARKERS

from .organisms import identify, strip_intrinsic
from .sir import normalize_sir_map

_NONE = {"probability": None, "confidence": 0, "mechanism": "",
         "markers_R": [], "detail": "", "action": "", "betalactam_policy": None}
_LOW = {"probability": "low", "confidence": 10, "mechanism": "",
        "markers_R": [], "detail": "", "action": "", "betalactam_policy": None}

_PSEUDOMONAS_BETALACTAMS = (
    "Ceftazidime", "Cefepime", "Piperacillin + Tazobactam",
    "Piperacillin/Tazobactam", "Ceftolozane + Tazobactam",
    "Ceftazidime + Avibactam", "Aztreonam",
)


def _cr_pseudomonas(sir: Dict[str, str], carb_R: List[str]) -> Dict[str, Any]:
    """Carbapenem-resistant P. aeruginosa: NOT a carbapenemase call.

    In P. aeruginosa carbapenem resistance is predominantly chromosomal (OprD
    porin loss, efflux, derepressed AmpC) and EUCAST publishes no phenotypic
    rule that separates it from carbapenemase production. Other beta-lactams
    that test susceptible are reported as tested and stay usable.
    """
    still_s = [d for d in _PSEUDOMONAS_BETALACTAMS if sir.get(d) == "S"]
    sug = (f" الأدوية التالية لسه S في نفس اللوحة: {', '.join(still_s)} — "
           "ده يرجّح آلية غير إنزيمية (فقد بورين/مضخة طرد) ويقلّل احتمال "
           "الكاربابينيميز." if still_s else
           " مفيش بيتا-لاكتام S في اللوحة — احتمال الكاربابينيميز أعلى هنا.")
    return {
        "probability": "cr_pseudomonas",
        "confidence": 60,
        "mechanism": "Carbapenem-resistant P. aeruginosa — mechanism not determined",
        "markers_R": carb_R,
        "carbapenem_resistant": True,
        "still_susceptible_betalactams": still_s,
        "betalactam_policy": None,
        "detail": ("مقاومة كاربابينيم في P. aeruginosa — الأشيع فقد بورين OprD "
                   "± مضخة طرد ± AmpC مُحدَث، مش إنزيم كاربابينيميز. "
                   "الكاربابينيميز أقلية في السودوموناس ولا يوجد نمط قرصي "
                   "معتمد من EUCAST يفرّق بينهم." + sug),
        "action": ("راجع Ceftazidime / Cefepime / Piperacillin-Tazobactam في نفس "
                   "اللوحة قبل النزول على Colistin — لو فيهم S بلّغهم كما هم "
                   "واستخدمهم. أكّد بـ mCIM / PCR فقط لو التصنيف هيغيّر العلاج "
                   "أو لأغراض مكافحة العدوى."),
    }


def predict_esbl(organism: str, sir_map: Dict[str, str]) -> Dict[str, Any]:
    """Predict ESBL / AmpC / carbapenem-resistance mechanism from the phenotype."""
    sir = normalize_sir_map(sir_map)
    if not sir:
        return dict(_NONE)

    org = identify(organism)
    is_producer = org.is_("esbl_capable")
    is_ampc_prone = org.is_("ampc_inducible")
    if not is_producer and not is_ampc_prone:
        return dict(_NONE)

    # Intrinsic-R results carry no information about acquired mechanisms.
    sir = strip_intrinsic(organism, sir)

    def r(drug: str) -> bool:
        return sir.get(drug) == "R"

    primary_R = [d for d in ESBL_MARKERS["primary"] if r(d)]
    second_R = [d for d in ESBL_MARKERS["secondary"] if r(d)]
    med_R = [d for d in ESBL_MARKERS["medium"] if r(d)]
    primary_tested = [d for d in ESBL_MARKERS["primary"] if d in sir]
    thin_panel = len(primary_tested) < 2

    carb_R = [d for d in CARBAPENEMS if r(d)]

    # ── P. aeruginosa ────────────────────────────────────────────────────
    if org.is_("pseudomonas"):
        if carb_R:
            return _cr_pseudomonas(sir, carb_R)
        return dict(_LOW)          # ESBL/AmpC labels are Enterobacterales-only

    # ── Carbapenem signals (Enterobacterales) ────────────────────────────
    # Morganellaceae: imipenem non-susceptibility is expected, not a signal.
    imipenem_counts = not org.is_("morganellaceae")
    strong_R = [d for d in ("Imipenem/Cilastatin", "Meropenem")
                if r(d) and (d != "Imipenem/Cilastatin" or imipenem_counts)]
    strong_I = [d for d in ("Imipenem/Cilastatin", "Meropenem")
                if sir.get(d) == "I" and (d != "Imipenem/Cilastatin" or imipenem_counts)]
    erta_R = r("Ertapenem")
    signal_R = strong_R + (["Ertapenem"] if erta_R else [])

    if strong_R:
        if len(signal_R) >= 2:
            return {
                "probability": "carbapenemase", "confidence": 92,
                "betalactam_policy": "cre",
                "mechanism": "Carbapenemase (KPC / MBL / OXA-48-like) — Predicted",
                "markers_R": signal_R + primary_R,
                "detail": f"مقاومة لـ ≥2 كاربابينيم ({', '.join(signal_R)}) — نمط Carbapenemase صريح.",
                "action": "أرسل للمختبر المرجعي فوراً (PCR/mCIM). عزل صارم. Colistin/Ceftazidime-Avibactam.",
            }
        return {
            "probability": "carbapenemase", "confidence": 55,
            "betalactam_policy": "cre",
            "mechanism": "Possible carbapenemase (low-level) — Predicted",
            "markers_R": signal_R,
            "detail": "مقاومة لكاربابينيم واحد — يستلزم اختبار تأكيدي.",
            "action": "أجرِ mCIM/CarbaNP. قد يكون فقدان بورين + ESBL/AmpC وليس carbapenemase حقيقياً.",
        }
    if erta_R:
        mero_tested = sir.get("Meropenem") in ("S", "I")
        return {
            "probability": "carbapenemase", "confidence": 62 if mero_tested else 55,
            "betalactam_policy": "cre_possible",
            "mechanism": "Possible OXA-48-like carbapenemase OR porin loss + ESBL/AmpC — Predicted",
            "markers_R": ["Ertapenem"] + primary_R,
            "detail": ("Ertapenem R مع Meropenem S/I — نمط قد يوحي بـ OXA-48 (شائع في "
                       "مصر/الشرق الأوسط) أو بفقدان بورين + ESBL/AmpC بدون إنزيم "
                       "كاربابينيميز حقيقي."),
            "action": "أكد بـ mCIM / PCR (OXA-48) قبل اعتماد التشخيص. راقب بحذر؛ قد تكون الكاربابينيمات أقل فعالية.",
        }
    if strong_I:
        return {
            "probability": "carbapenemase", "confidence": 55,
            "betalactam_policy": "cre_possible",
            "mechanism": "Possible carbapenemase (low-level) — Predicted",
            "markers_R": [f"{d} (I)" for d in strong_I],
            "detail": "توسط (I) لكاربابينيم — يستلزم اختبار تأكيدي.",
            "action": "أجرِ mCIM/CarbaNP. قد يكون فقدان بورين + ESBL/AmpC وليس carbapenemase حقيقياً.",
        }

    # ── AmpC (Enterobacterales with chromosomal inducible AmpC) ──────────
    if is_ampc_prone and is_producer and primary_R:
        return {
            "probability": "ampc", "confidence": 75, "betalactam_policy": "ampc",
            "mechanism": "Possible AmpC β-lactamase (Predicted)",
            "markers_R": primary_R,
            "detail": "مقاومة لـ 3rd-gen cephalosporin في كائن Enterobacterale منتج لـ AmpC مزمن — نمط AmpC وليس ESBL.",
            "action": "تجنب 3rd-gen cephalosporins حتى لو S. استخدم Cefepime أو Carbapenem. لا يُكتشف بـ DDST.",
        }

    # ── ESBL (Enterobacterales only) ─────────────────────────────────────
    if not is_producer:
        return dict(_LOW)

    if len(primary_R) >= 2:
        return {
            "probability": "high", "confidence": 88, "betalactam_policy": "esbl",
            "mechanism": "ESBL (Extended-Spectrum β-Lactamase) — Predicted",
            "markers_R": primary_R + second_R,
            "detail": f"مقاومة لـ {', '.join(primary_R)} — احتمال ESBL مرتفع.",
            "action": "استخدم Carbapenem للعدوى الشديدة (MERINO 2018). تجنب جميع cephalosporins.",
        }
    if len(primary_R) == 1:
        carb_s = any(sir.get(d) == "S" for d in CARBAPENEMS)
        conf = 72 if carb_s else 60
        if thin_panel:
            conf = min(conf, 45)
        detail = f"مقاومة لـ {primary_R[0]}" + (
            " مع كاربابينيم حساس — نمط ESBL كلاسيكي." if carb_s else ".")
        if thin_panel:
            detail += (" ⚠️ لوحة محدودة: تم اختبار سيفالوسبورين أساسي واحد فقط "
                       "— التفسير أقل موثوقية؛ وسّع اللوحة (Ceftazidime/Cefotaxime).")
        prob = "high" if (carb_s and not thin_panel) else "moderate"
        return {
            "probability": prob, "confidence": conf,
            "betalactam_policy": "esbl" if prob == "high" else None,
            "mechanism": "Probable ESBL — Predicted",
            "markers_R": primary_R + med_R,
            "detail": detail,
            "action": "أكد بـ Double-Disk Synergy Test (DDST) أو PCR. عامل كـ ESBL حتى التأكيد.",
        }
    if len(med_R) >= 2:
        return {
            "probability": "moderate", "confidence": 50, "betalactam_policy": None,
            "mechanism": "Possible ESBL (lower-gen cephalosporin resistance) — Predicted",
            "markers_R": med_R,
            "detail": "مقاومة لـ ≥2 من الجيل الأقل — يستدعي تأكيد ESBL.",
            "action": "أجرِ DDST. قد يكون ESBL مبكر أو آلية أخرى.",
        }
    return dict(_LOW)
