"""Rules about what this organism does to this drug, whatever the disc says."""
from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Optional

from organism_profile import ORGANISM_PROFILE

from .. import drugs as D
from ..organisms import is_intrinsic
from .context import Context, DrugCase
from .findings import Finding, ban, warn

# Class-level words used in ORGANISM_PROFILE[...]["avoid"] -> drug families.
_AVOID_CLASS_FAMILIES: Dict[str, FrozenSet[str]] = {
    "cephalosporins": frozenset({D.CEPHALOSPORIN, D.CEPHALOSPORIN_BLI, D.CEPHAMYCIN}),
    "tetracyclines": frozenset({D.TETRACYCLINE}),
    "aminoglycosides": frozenset({D.AMINOGLYCOSIDE}),
    "carbapenems": frozenset({D.CARBAPENEM}),
    "beta-lactams": D.BETA_LACTAM_FAMILIES,
}


def _avoid_term(text: str) -> str:
    """'Cephalosporins (كل الجيل)' -> 'cephalosporins'; 'Ampicillin (alone)' -> 'ampicillin'."""
    return re.sub(r"\(.*?\)", "", text or "").strip().lower()


def is_intrinsically_avoided(organism_type: str, drug_name: str,
                             drug_info: Optional[Dict[str, Any]] = None) -> bool:
    """True when the organism is intrinsically resistant to the drug (canonical
    EUCAST table) or the organism profile lists the drug - or its whole class -
    under "avoid".

    Profile entries are matched by EXACT drug name or by class word. They used
    to be matched by substring, so "Ampicillin" on the H. influenzae avoid list
    also banned Ampicillin/Sulbactam, and "Amoxicillin" on the Moraxella list
    banned Amoxicillin + Clavulanic acid - the inhibitor combinations that
    exist precisely to treat those beta-lactamase producers.
    """
    if is_intrinsic(organism_type, drug_name):
        return True
    avoid = (ORGANISM_PROFILE.get(organism_type) or {}).get("avoid", [])
    d_low = drug_name.strip().lower()
    fam = D.family(drug_name)
    for entry in avoid:
        term = _avoid_term(entry)
        if not term:
            continue
        if term == d_low:
            return True
        families = _AVOID_CLASS_FAMILIES.get(term)
        if families and fam in families:
            return True
    return False


def rule_intrinsic_avoided(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """Expected-resistant drug reported S or I. The QC layer (ast_reportability)
    flags such a result as an error; the engine must agree with it and must not
    list the drug as an option while the QC panel says the result is impossible.
    (It used to: "Vancomycin S" on E. coli raised a QC error AND appeared under
    recommended options.)"""
    if not (d.name in ctx.reportability_intrinsic
            or is_intrinsically_avoided(ctx.organism_name, d.name, d.info)):
        return None
    org = ctx.organism_name
    return ban(
        "organism_inactive", "organism",
        f"غير فعال لـ {org} طبيعياً.",
        f"{d.name} لديه مقاومة طبيعية أو عدم فعالية ضد {org}.",
        f"Not active against {org} (intrinsic).",
        f"{d.name} has natural resistance or no useful activity against {org}.",
        terminal=True,
    )


def rule_mrsa_beta_lactam(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """MRSA (mecA / PBP2a): every beta-lactam in this formulary fails, whatever
    the disc reads - including the inhibitor combinations."""
    if not (ctx.is_mrsa and d.family in D.BETA_LACTAM_FAMILIES):
        return None
    return ban(
        "mrsa_beta_lactam", "organism", "بيتا-لاكتام — لا يعمل على MRSA.",
        "MRSA يحمل جين mecA (PBP2a) → مقاوم لكل البيتا-لاكتام (البنسلينات، "
        "السيفالوسبورينات التقليدية، والكاربابينيمات) حتى لو أظهرت المزرعة حساسية. "
        "العلاج: Vancomycin / Linezolid / Daptomycin (حسب الموقع والحساسية).",
        "Beta-lactam — does not work against MRSA.",
        "MRSA carries mecA (PBP2a) and is therefore resistant to ALL "
        "beta-lactams (penicillins, conventional cephalosporins and "
        "carbapenems) EVEN IF the culture reports susceptible. Treat with "
        "Vancomycin / Linezolid / Daptomycin per site and susceptibility.",
    )


def rule_d_test(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """Erythromycin R + Clindamycin S -> inducible MLSB until a negative D-test."""
    if not (d.name == "Clindamycin" and d.sir == "S"
            and ctx.sir.get("Erythromycin") == "R"):
        return None
    d_test = str(ctx.sir.get("D-test") or ctx.sir.get("D test") or "").strip().upper()
    if d_test in ("NEGATIVE", "NEG", "-"):
        return None
    label = ("D-test Positive" if d_test in ("POSITIVE", "POS", "+")
             else "D-test Not Confirmed")
    return ban(
        "d_test_inducible", "d_test_inducible",
        f"مقاومة Clindamycin المستحثة — {label}",
        "Erythromycin=R + Clindamycin=S → MLSB inducible resistance محتملة. "
        "لا تُستخدم Clindamycin إلا بعد تأكيد D-test سالب. CLSI M100 / EUCAST.",
        f"Inducible clindamycin resistance - {label}",
        "Erythromycin=R + Clindamycin=S -> possible inducible MLSB "
        "resistance. Do not use Clindamycin unless a negative D-test "
        "confirms it. CLSI M100 / EUCAST.",
    )


def rule_staph_penicillinase(ctx: Context, d: DrugCase) -> Optional[Finding]:
    if not (d.name == "Penicillin" and d.info.get("penicillinase_sensitive")
            and ctx.organism.is_("staphylococcus") and d.sir != "S"):
        return None
    return ban(
        "penicillinase_producer", "penicillinase_producer",
        "إنتاج Beta-lactamase (Penicillinase)",
        "90%+ من S. aureus تنتج Penicillinase → Penicillin غير فعال. "
        "استخدم Cefazolin أو Oxacillin (MSSA) أو Vancomycin (MRSA).",
        "Beta-lactamase (penicillinase) producer",
        "Over 90% of S. aureus produce penicillinase, so Penicillin is not "
        "effective. Use Cefazolin or Oxacillin (MSSA), or Vancomycin (MRSA).",
    )


def rule_enterococcus_folate(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """Enterococci use exogenous folate in vivo: TMP-SMX can test S and fail."""
    if not (d.family == D.FOLATE and ctx.organism.is_("enterococcus")):
        return None
    return ban(
        "enterococcus_tmpsmx", "organism",
        "غير موثوق سريرياً ضد Enterococcus (رغم حساسية المختبر).",
        "المكورات المعوية تستخدم الفولات/الثيميدين الخارجي داخل الجسم فتتجاوز "
        "تثبيط الفولات؛ لذلك قد يظهر TMP-SMX حساساً في المختبر لكنه يفشل سريرياً. "
        "لا يُعتمد عليه لعلاج عدوى Enterococcus (CLSI/EUCAST). استخدم "
        "Ampicillin/Amoxicillin (أو Vancomycin/Linezolid حسب الحساسية).",
        "Clinically unreliable against Enterococcus (despite in-vitro susceptibility).",
        "Enterococci take up exogenous folate/thymidine in vivo and bypass "
        "folate inhibition, so TMP-SMX can test susceptible in the laboratory "
        "yet fail clinically. It is not relied upon for enterococcal infection "
        "(CLSI/EUCAST). Use Ampicillin/Amoxicillin, or Vancomycin/Linezolid "
        "according to susceptibility.",
    )


def rule_klebsiella_fosa(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """K. pneumoniae carries chromosomal fosA: fosfomycin can read S and fail."""
    if not (d.name == "Fosfomycin" and ctx.organism.is_("klebsiella")):
        return None
    ar = ("Klebsiella تحمل جين fosA كروموسومياً — قد تفشل "
          "الاستجابة رغم حساسية المزرعة. لا تعتمد عليه "
          "كعلاج وحيد؛ فضّل بديلاً مؤكداً.")
    en = ("Klebsiella carries chromosomal fosA — therapy may "
          "fail despite an S result in vitro. Do not rely on "
          "fosfomycin monotherapy; prefer a confirmed alternative.")
    return warn("intrinsic_fosa", ar, en,
                "Klebsiella + fosA: قد يفشل رغم الحساسية — لا يُعتمد عليه منفرداً.",
                "Klebsiella fosA: may fail despite S — do not rely on it alone.",
                sir_note="fosa_klebsiella",
                sir_note_ar=ar, sir_note_en=en)
