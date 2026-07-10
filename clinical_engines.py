# Auto-extracted: pure clinical decision logic — Orange Lab Microbiology CDSS
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

logger = logging.getLogger("orange_lab.engines")

from abx_guidelines import (
    ABX_GUIDELINES,
)
from organism_profile import (
    ORGANISM_PROFILE,
)
from clinical_data import (
    ALWAYS_IV_SYNDROMES,
    AMPC_PRODUCERS,
    AST_QC_RULES,
    CARBAPENEMS,
    CHILD_BAN_REASONS,
    COMBINATION_THERAPY,
    ESBL_MARKERS,
    ESBL_PRODUCERS,
    GRAM_POSITIVE_ORGANISMS,
    HEPATIC_DOSING,
    HIGH_BIOAVAILABILITY,
    INFECTION_SYNDROMES,
    INTRINSIC_RESISTANCE,
    MDR_CATEGORIES,
    MDR_CATEGORIES_GRAM_NEG,
    MDR_CATEGORIES_GRAM_POS,
    ORGANISM_AVOID_CLASS_MAP,
    PHENOTYPE_RULES,
    RANKING_WEIGHTS,
    TREATMENT_DURATION_DB,
    get_mdr_panel,
)

def fuzzy_match(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 100.0
    return SequenceMatcher(None, a, b).ratio() * 100

def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception as _exc:
        logger.debug("suppressed exception: %s", _exc)
        return default

def calc_creatinine_clearance(age: int, weight: float, scr: float, sex: str,
                              height_cm: Optional[float] = None) -> float:
    """Estimate renal function.

    • Adults (≥18y): Cockcroft-Gault (CrCl, mL/min).
    • Children (<18y): Bedside Schwartz eGFR (mL/min/1.73m²) — the validated
      pediatric equation. Cockcroft-Gault is NOT validated in children and must
      not be used for them. Schwartz needs HEIGHT; if height_cm isn't supplied
      it's estimated from age (rougher — pass a real height whenever possible).
    """
    if scr <= 0:
        return 0.0
    if age < 18:
        # Bedside Schwartz (2009, IDMS-traceable): eGFR = 0.413 × height(cm) / SCr
        h = height_cm if (height_cm and height_cm > 0) else None
        if h is None:
            # Fallback height estimate from age when none is provided.
            h = (50 + age * 25) if age < 1 else (6 * age + 77)
        return (0.413 * float(h)) / scr
    # Adult Cockcroft-Gault
    crcl = ((140 - age) * weight) / (72 * scr)
    if sex == "Female":
        crcl *= 0.85
    return crcl

def get_renal_severity(crcl: float) -> str:
    if crcl >= 60:
        return "Mild"
    if crcl >= 30:
        return "Moderate"
    return "Severe"

def get_route_label(item: Dict[str, Any]) -> str:
    return "🟢 Oral preferred / PO-friendly" if item.get("high_po") else "💉 IV/IM only"

def uniq_keep_order(items: List[str]) -> List[str]:
    seen:   set       = set()
    result: List[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            result.append(x)
    return result


# ─────────────────────────────────────────────────────────────────────────
# Specimen classification — the SINGLE source of truth for specimen routing
# across the whole app (UI field visibility, pathogenicity branches, and the
# pathogenicity scoring engine). One classifier prevents the UI and the engine
# from drifting apart — the exact drift that made a bare "swab" keyword get
# checked before "rectal"/"throat"/"vaginal", so a rectal/throat/vaginal swab
# was mis-scored as a wound.
#
# Category split worth noting:
#   • "sputum"      → expectorated sputum → Murray-Washington screening applies.
#   • "respiratory" → BAL / bronchial washing / (endo)tracheal aspirate →
#                     lower-respiratory, but Murray-Washington does NOT apply.
#   • "genital"/"throat" → own buckets so a swab from these sites is never a
#                     "wound".
# ─────────────────────────────────────────────────────────────────────────
SPECIMEN_CATEGORIES = (
    "urine", "blood", "sputum", "respiratory", "stool",
    "csf", "genital", "throat", "wound", "other",
)


def classify_specimen(name: str) -> str:
    """Map any specimen label to a canonical category (see SPECIMEN_CATEGORIES).

    Order matters: the most specific site keywords are checked BEFORE the
    generic wound/swab keywords, so 'rectal swab' → stool, 'throat swab' →
    throat, 'high vaginal swab' → genital, and only a bare/other swab falls
    through to 'wound'.
    """
    s = (name or "").lower()
    stripped = s.strip()
    if not stripped:
        return "other"

    # 1) CSF / sterile CNS fluid
    if any(k in s for k in ("csf", "cerebro", "spinal fluid", "lumbar",
                            "ventricular fluid")):
        return "csf"
    # 2) Blood
    if any(k in s for k in ("blood", "haemocult", "hemocult", "bacterem",
                            "septicaem", "septicem")):
        return "blood"
    # 3) Urine
    if any(k in s for k in ("urine", "urinary", "midstream", "msu", "csu")):
        return "urine"
    # 4) Genital (before wound → a genital swab is never a "wound")
    if any(k in s for k in ("vagin", "cervi", "endocerv", "urethr", "genital",
                            "hvs", "semen", "seminal", "prostat", "penile",
                            "vulv")):
        return "genital"
    # 5) Stool / GI (before wound → 'rectal swab' is stool, not wound).
    #    Use spaced/exact ' gi ' so it never matches 'surgical'.
    if (any(k in s for k in ("stool", "fecal", "faecal", "rectal", "gastro",
                             "colon", " gi "))
            or stripped in ("gi", "git")):
        return "stool"
    # 6) Throat / upper-respiratory-tract & ENT (before wound; no M-W here).
    #    'ear swab'/'otic'/'aural' (not bare 'ear') so it never matches 'smear'.
    if (any(k in s for k in ("throat", "pharyng", "tonsil", "nasal", "nasoph",
                             "nostril", "aural", "otic", "auricular",
                             "buccal", "ear swab"))
            or stripped in ("ear", "oral")):
        return "throat"
    # 7) Expectorated sputum → Murray-Washington applies
    if any(k in s for k in ("sputum", "expectorat")):
        return "sputum"
    # 8) Lower-respiratory aspirates → respiratory scoring, NO Murray-Washington
    if any(k in s for k in ("bal", "broncho", "bronch", "tracheal", "endotrach",
                            "et aspirate", "lavage", "respir")):
        return "respiratory"
    # 9) Wound / pus / abscess / tissue (a bare 'swab' lands here as last resort)
    if any(k in s for k in ("wound", "pus", "abscess", "tissue", "ulcer",
                            "drain", "cellulit", "sinus tract", "swab")):
        return "wound"
    return "other"


def is_intrinsically_avoided(organism_type: str, drug_name: str, drug_info: Dict[str, Any]) -> bool:
    organism_avoid = (ORGANISM_PROFILE.get(organism_type) or {}).get("avoid", [])
    d_low   = drug_name.lower()
    d_class = drug_info.get("class", "").lower()
    for avoid_item in organism_avoid:
        av_low = avoid_item.lower().strip()
        if av_low in d_low or d_low in av_low:
            return True
        mapped = ORGANISM_AVOID_CLASS_MAP.get(av_low)
        if mapped and any(cls in d_class for cls in mapped):
            return True
    return False

def build_banned_item(name: str, category: str, reason_short: str, reason_detail: str) -> Dict[str, str]:
    return {"name": name, "category": category,
            "reason_short": reason_short, "reason_detail": reason_detail}

# ── Organism-name canonicalization ─────────────────────────────────────────
# The app/profile use short names ("E. coli", "Klebsiella spp.", "MRSA"), while
# some data/tests use full binomials ("Escherichia coli", "Klebsiella pneumoniae").
# assess_pathogenicity used to compare with `organism in <list>`, which SILENTLY
# failed whenever the two spellings differed (e.g. "E. coli" not matching
# "Escherichia coli"), mis-scoring most non-urine organisms. Canonicalize BOTH
# sides so membership tests are spelling-independent.
_ORG_CANON_MAP = {
    "e. coli": "escherichia coli", "e.coli": "escherichia coli",
    "escherichia coli": "escherichia coli",
    "enterohemorrhagic e. coli": "escherichia coli o157",
    "escherichia coli o157:h7": "escherichia coli o157",
    "klebsiella spp.": "klebsiella", "klebsiella pneumoniae": "klebsiella",
    "klebsiella oxytoca": "klebsiella", "klebsiella": "klebsiella",
    "proteus mirabilis": "proteus", "proteus spp.": "proteus", "proteus": "proteus",
    "enterococcus faecalis": "enterococcus", "enterococcus spp.": "enterococcus",
    "enterococcus faecium": "enterococcus", "enterococcus": "enterococcus",
    "vre": "vre",
    "h. influenzae": "haemophilus influenzae",
    "haemophilus influenzae": "haemophilus influenzae",
    "staphylococcus aureus": "staphylococcus aureus", "mssa": "staphylococcus aureus",
    "mrsa": "mrsa",
    "staphylococcus epidermidis": "cons",
    "staphylococcus saprophyticus": "staphylococcus saprophyticus",
    "coagulase negative staphylococcus": "cons",
    "coagulase-negative staphylococci": "cons", "cons": "cons",
    "streptococcus viridans": "viridans streptococci",
    "viridans streptococci": "viridans streptococci",
    "corynebacterium spp.": "corynebacterium", "corynebacterium": "corynebacterium",
    "campylobacter jejuni": "campylobacter", "campylobacter spp.": "campylobacter",
    "campylobacter": "campylobacter",
    "salmonella spp.": "salmonella", "salmonella": "salmonella",
    "shigella spp.": "shigella", "shigella": "shigella",
    "streptococcus pneumoniae": "streptococcus pneumoniae",
    "s. pneumoniae": "streptococcus pneumoniae",
    "pseudomonas aeruginosa": "pseudomonas aeruginosa",
    "acinetobacter baumannii": "acinetobacter baumannii",
    "stenotrophomonas maltophilia": "stenotrophomonas maltophilia",
    "legionella pneumophila": "legionella", "legionella": "legionella",
    "mycoplasma spp.": "mycoplasma", "mycoplasma pneumoniae": "mycoplasma",
    "moraxella catarrhalis": "moraxella catarrhalis",
    "neisseria meningitidis": "neisseria meningitidis",
    "neisseria spp.": "neisseria",
    "listeria monocytogenes": "listeria monocytogenes",
    "streptococcus agalactiae": "streptococcus agalactiae",
    "gbs": "streptococcus agalactiae",
    "anaerobes (لاهوائيات)": "anaerobes", "anaerobes": "anaerobes",
    "clostridioides difficile": "c. difficile", "clostridium difficile": "c. difficile",
    "candida albicans": "candida", "candida spp.": "candida", "candida": "candida",
}


def _canon_org(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip().lower())
    return _ORG_CANON_MAP.get(n, n)


def _org_in(name: str, group) -> bool:
    """Spelling-independent membership test for organism names."""
    target = _canon_org(name)
    return any(_canon_org(g) == target for g in group)

def analyze_antibiotics(
    final_drugs: List[str],
    organism_type: str,
    culture_type: str,
    age: int,
    sex: str,
    is_renal: bool,
    cl_cr: float,
    is_preg: bool,
    is_hepatic: bool,
    current_meds: List[str],
    sir_map: Dict[str, str],
) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict], List[str]]:
    allowed:            List[Dict] = []
    warned:             List[Dict] = []
    banned:             List[Dict] = []
    preg_warn_items:    List[Dict] = []
    interactions_alerts: List[str] = []

    # ── Detect resistance mechanism ONCE (drives beta-lactam suppression) ──────
    # ESBL → resistant to ALL penicillins + cephalosporins (+ aztreonam),
    #        even if AST reports S (inoculum effect; EUCAST/CLSI report-as-tested
    #        but clinically carbapenem is required for serious infection).
    # Carbapenemase → also resistant to carbapenems.
    _mech = predict_esbl(organism_type, sir_map) if sir_map else {}
    _mech = _mech or {}
    _mech_prob = _mech.get("probability")
    _is_esbl_like   = _mech_prob in ("high", "ampc")
    _is_carbapenemase = _mech_prob == "carbapenemase"

    # ── Detect MRSA from AST markers (Oxacillin/Cefoxitin R), not just name ────
    # A S. aureus with Oxacillin-R or Cefoxitin-R IS MRSA → ALL beta-lactams fail
    # (except anti-MRSA cephalosporins like Ceftaroline, not in this formulary).
    _org_l_aa = (organism_type or "").lower()
    _is_staph = ("staphylococcus" in _org_l_aa or "staph" in _org_l_aa
                 or _org_l_aa == "mrsa" or _org_l_aa == "mssa")
    # MRSA detection: AST markers + organism name + free-text report markers
    _mrsa_text_markers = (
        "mrsa screen positive" in _org_l_aa
        or "pbp2a positive" in _org_l_aa
        or "pbp2a" in _org_l_aa
        or "methicillin resistant" in _org_l_aa
        or "methicillin-resistant" in _org_l_aa
    )
    _mrsa_marker_R = (sir_map.get("Oxacillin") == "R"
                      or sir_map.get("Cefoxitin") == "R"
                      or _org_l_aa == "mrsa"
                      or _mrsa_text_markers)
    _is_mrsa = _is_staph and _mrsa_marker_R

    def _is_penicillin_or_ceph(info_dict: Dict) -> bool:
        c = info_dict.get("class", "").lower()
        # Penicillins & cephalosporins, but NOT BLI combos vs Carbapenems
        if "carbapenem" in c:
            return False
        if "bli" in c or "tazobactam" in c or "sulbactam" in c or "clavulan" in c:
            return False   # BLI combos handled separately (UTI-only caution)
        return any(k in c for k in ("penicillin", "cephalosporin", "cephalosporins"))

    def _is_bli_combo(info_dict: Dict) -> bool:
        c = info_dict.get("class", "").lower()
        n = info_dict.get("name", "").lower() if isinstance(info_dict.get("name"), str) else ""
        return ("bli" in c or "tazobactam" in c or "sulbactam" in c
                or "clavulan" in c or "clavulanic" in n or "tazobactam" in n)

    def _is_carbapenem(info_dict: Dict) -> bool:
        return "carbapenem" in info_dict.get("class", "").lower()

    for drug in final_drugs:
        if drug not in ABX_GUIDELINES:
            continue
        info           = ABX_GUIDELINES[drug]
        d_low          = drug.lower()
        cls            = info.get("class", "").lower()
        culture_result = sir_map.get(drug)

        if culture_result == "R":
            banned.append(build_banned_item(
                drug, "resistant", "مقاوم (R) في نتيجة المزرعة.",
                f"المزرعة أثبتت أن {drug} لا يثبط نمو الجرثومة. MIC أعلى من الحد العلاجي → خطر فشل علاجي.",
            ))
            continue

        for med in current_meds:
            if med in info.get("interacts_with", []):
                interactions_alerts.append(f"⚡ تعارض: {drug} مع {med}")
        if is_hepatic and info.get("hepatic_caution"):
            interactions_alerts.append(f"🏥 تحذير كبدي: {drug} — يحتاج متابعة أو تعديل حسب الحالة.")

        if is_intrinsically_avoided(organism_type, drug, info):
            banned.append(build_banned_item(
                drug, "organism",
                f"غير فعال لـ {organism_type} طبيعياً.",
                f"{drug} لديه مقاومة طبيعية أو عدم فعالية ضد {organism_type}.",
            ))
            continue

        # ── MRSA: ALL beta-lactams (penicillins + cephalosporins) fail ────────
        # Detected from AST (Oxacillin/Cefoxitin R) OR organism name = MRSA.
        # Exception: carbapenems also fail for MRSA but are caught here too.
        if _is_mrsa and any(k in info.get("class", "").lower()
                            for k in ("penicillin", "cephalosporin", "carbapenem")):
            banned.append(build_banned_item(
                drug, "organism", "بيتا-لاكتام — لا يعمل على MRSA.",
                "MRSA يحمل جين mecA (PBP2a) → مقاوم لكل البيتا-لاكتام (البنسلينات، "
                "السيفالوسبورينات التقليدية، والكاربابينيمات) حتى لو أظهرت المزرعة حساسية. "
                "العلاج: Vancomycin / Linezolid / Daptomycin (حسب الموقع والحساسية).",
            ))
            continue

        # ── Cefepime (4th-gen) + ESBL: special handling (NOT a hard ban) ──────
        # EUCAST 2026 reports as-tested; IDSA AMR 2025: Cefepime-S acceptable
        # ONLY for uncomplicated lower UTI, AVOID in bacteremia/serious infection.
        # Mirrors BLI-combo handling — warn, don't ban, don't free-allow.
        if (_is_esbl_like and not _is_carbapenemase
                and drug == "Cefepime"
                and sir_map.get("Cefepime") == "S"):
            _wc = dict(info)
            _wc["warning_reason"] = "esbl_bli_uti_only"
            _wc["esbl_note"] = (
                "كائن ESBL: Cefepime (4th-gen) قد يبقى حساسًا، لكنه فعّال فقط "
                "لعدوى المسالك البولية البسيطة عند ثبوت الحساسية. تجنّبه في تجرثم "
                "الدم أو التهاب الكلية الصاعد (IDSA AMR 2025 — ارتفاع الوفيات) — "
                "Carbapenem هو الخيار الأول للعدوى الشديدة."
            )
            _wc["esbl_note_en"] = (
                "ESBL organism: Cefepime (4th-gen) may remain susceptible but is "
                "effective ONLY for uncomplicated lower UTI when proven S. Avoid in "
                "bacteremia or pyelonephritis (IDSA AMR 2025 — higher mortality) — "
                "Carbapenem is first-line for serious infection."
            )
            warned.append({"name": drug, **_wc})
            continue

        # ── ESBL / AmpC: suppress ALL penicillins & cephalosporins ────────────
        # (even if AST = S — clinically unreliable for serious infection)
        # Note: Cefepime-S handled separately above (UTI-only caution).
        if (_is_esbl_like or _is_carbapenemase) and _is_penicillin_or_ceph(info):
            _mech_name = ("Carbapenemase" if _is_carbapenemase
                          else "AmpC" if _mech_prob == "ampc" else "ESBL")
            banned.append(build_banned_item(
                drug, "organism",
                f"غير فعّال — كائن منتج لـ {_mech_name}.",
                f"الكائن منتج لـ {_mech_name}: مقاوم لجميع البنسلينات والسيفالوسبورينات "
                "(بما فيها Ampicillin/Amoxicillin والأجيال 1–4) حتى لو أظهرت المزرعة "
                "حساسية (تأثير اللقاح / inoculum effect). الخيار العلاجي = "
                f"{'Colistin / Ceftazidime-Avibactam' if _is_carbapenemase else 'Carbapenem (Meropenem/Ertapenem)'}.",
            ))
            continue

        # ── Carbapenemase: also suppress carbapenems ──────────────────────────
        if _is_carbapenemase and _is_carbapenem(info):
            banned.append(build_banned_item(
                drug, "organism",
                "غير فعّال — كائن منتج لـ Carbapenemase.",
                "الكائن منتج لإنزيم Carbapenemase (KPC/MBL/OXA): مقاوم للكاربابينيمات. "
                "استخدم Colistin أو Ceftazidime-Avibactam (± Aztreonam لـ MBL) حسب الحساسية.",
            ))
            continue

        # ── ESBL + BLI combos (Amox-Clav, Pip-Tazo): UTI-only caution ─────────
        # Not banned outright (effective for uncomplicated ESBL UTI if S),
        # but NOT for bacteremia/serious infection (MERINO 2018).
        if (_is_esbl_like or _is_carbapenemase) and _is_bli_combo(info):
            _w = dict(info)
            _w["warning_reason"] = "esbl_bli_uti_only"
            _w["esbl_note"] = ("كائن ESBL: هذا المثبط (BLI) فعّال فقط لعدوى المسالك "
                               "البولية البسيطة عند ثبوت الحساسية. لا يُستخدم في تجرثم الدم "
                               "أو العدوى الشديدة (دراسة MERINO 2018) — استخدم Carbapenem.")
            _w["esbl_note_en"] = ("ESBL organism: this BLI combination is effective ONLY for "
                                  "uncomplicated lower UTI when proven susceptible. Do NOT use "
                                  "in bacteremia or serious infection (MERINO 2018) — use Carbapenem.")
            warned.append({"name": drug, **_w})
            continue

        # ══════════════════════════════════════════════════════════════════
        # ABSOLUTE CONTRAINDICATIONS — checked BEFORE pregnancy caution
        # (child age + renal threshold are hard bans; pregnancy is discretionary)
        # ══════════════════════════════════════════════════════════════════
        if age < 18 and not info.get("child_safe", True):
            if "fluoroquinolone" in cls:
                banned.append(build_banned_item(
                    drug, "child", "غير مناسب < 18 سنة.", CHILD_BAN_REASONS["fluoroquinolone"]
                ))
                continue
            if "tetracycline" in cls and age < 8:
                banned.append(build_banned_item(
                    drug, "child", "غير مناسب < 8 سنوات.", CHILD_BAN_REASONS["tetracycline"]
                ))
                continue
            banned.append(build_banned_item(
                drug, "child", "غير مفضل للأطفال.",
                "يحتاج تقييم متخصص أو لا يُنصح به روتينياً لهذه الفئة العمرية.",
            ))
            continue

        # Nitrofurantoin: contraindicated below its renal threshold (EMA/BNF 2025 = 45)
        # ── D-test: Inducible Clindamycin Resistance (CLSI M100 2026) ──────────
        if "clindamycin" in d_low and culture_result == "S":
            erythro_r = sir_map.get("Erythromycin") == "R"
            if erythro_r:
                d_test_val = (sir_map.get("D-test") or
                              sir_map.get("D test") or "").strip().upper()
                if d_test_val == "NEGATIVE":
                    pass  # Confirmed D-test negative → safe to use
                else:
                    label = "D-test Positive" if d_test_val == "POSITIVE" else "D-test Not Confirmed"
                    banned.append(build_banned_item(
                        drug, "d_test_inducible",
                        f"مقاومة Clindamycin المستحثة — {label}",
                        f"Erythromycin=R + Clindamycin=S → MLSB inducible resistance محتملة. "
                        f"لا تُستخدم Clindamycin إلا بعد تأكيد D-test سالب. CLSI M100 2026 / EUCAST 2026.",
                    ))
                    continue

        # ── Fusidic acid: لا monotherapy في العدوى الجهازية ─────────────────────
        if "fusidic" in d_low and info.get("no_monotherapy_systemic"):
            if any(_s in culture_type.lower() for _s in ("blood", "csf", "sputum")):
                interactions_alerts.append(
                    "⚠️ Fusidic acid: لا يُستخدم منفرداً في العدوى الجهازية — "
                    "combination إلزامي (+ Rifampicin أو + Vancomycin). مقاومة سريعة."
                )

        # ── Penicillin: Penicillinase في المكورات العنقودية ─────────────────────
        if ("penicillin" in d_low and "oxacillin" not in d_low
                and info.get("penicillinase_sensitive")):
            org_l = (organism_type or "").lower()
            is_staph = ("staphylococcus aureus" in org_l or "mrsa" in org_l
                        or "mssa" in org_l or "staph" in org_l)
            if is_staph and culture_result != "S":
                banned.append(build_banned_item(
                    drug, "penicillinase_producer",
                    "إنتاج Beta-lactamase (Penicillinase)",
                    "90%+ من S. aureus تنتج Penicillinase → Penicillin غير فعال. "
                    "استخدم Cefazolin أو Oxacillin (MSSA) أو Vancomycin (MRSA).",
                ))
                continue

        # ── Oxacillin: MSSA alert للـ bacteremia ─────────────────────────────────
        if "oxacillin" in d_low and culture_result == "S" and "blood" in culture_type.lower():
            interactions_alerts.append(
                "ℹ️ Oxacillin=S (MSSA confirmed). Cefazolin مفضل على Oxacillin "
                "في bacteremia (أقل interstitial nephritis). IDSA 2024."
            )

        # ── Enterococcus + TMP-SMX: in-vitro S but clinically unreliable ─────────
        # Enterococci use exogenous folate/thymidine in vivo, bypassing folate
        # inhibition, so TMP-SMX may test S yet fail clinically (CLSI/EUCAST).
        if (("trimethoprim" in d_low or "sulfamethoxazole" in d_low or "smx" in d_low)
                and "enterococc" in (organism_type or "").lower()):
            banned.append(build_banned_item(
                drug, "organism",
                "غير موثوق سريرياً ضد Enterococcus (رغم حساسية المختبر).",
                "المكورات المعوية تستخدم الفولات/الثيميدين الخارجي داخل الجسم فتتجاوز "
                "تثبيط الفولات؛ لذلك قد يظهر TMP-SMX حساساً في المختبر لكنه يفشل سريرياً. "
                "لا يُعتمد عليه لعلاج عدوى Enterococcus (CLSI/EUCAST). استخدم "
                "Ampicillin/Amoxicillin (أو Vancomycin/Linezolid حسب الحساسية).",
            ))
            continue

        # ── E. faecium + Ampicillin/Amox: acquired resistance is very common ─────
        # Unlike E. faecalis (usually ampicillin-S), E. faecium is ampicillin-R in
        # the great majority of isolates (acquired, not intrinsic — so we honour a
        # genuine S result but warn). If not tested, do not assume it is usable.
        if (("ampicillin" in d_low or "amoxicillin" in d_low)
                and "faecium" in (organism_type or "").lower()):
            _amp_sir = culture_result
            if _amp_sir == "S":
                interactions_alerts.append(
                    "⚠️ E. faecium + Ampicillin=S: نادر (معظم عزلات faecium مقاومة "
                    "مكتسبة للـ Ampicillin) — تأكد من صحة النتيجة قبل الاعتماد عليها."
                )
            elif _amp_sir not in ("S", "I", "R"):
                interactions_alerts.append(
                    "ℹ️ E. faecium: مقاومة الـ Ampicillin مكتسبة وشائعة جداً — لا تفترض "
                    "فعاليته دون اختبار؛ فكّر في Vancomycin/Linezolid حسب الحساسية."
                )

        _nf_limit = info.get("renal_limit", 45)
        if is_renal and "nitrofurantoin" in d_low and cl_cr < _nf_limit:
            banned.append(build_banned_item(
                drug, "renal",
                f"ممنوع — CrCl {cl_cr:.1f} < {_nf_limit} ml/min",
                f"CrCl = {cl_cr:.1f} مل/د — أقل من الحد المطلوب ({_nf_limit} مل/د). "
                "خطر عدم كفاءة علاجية + تراكم سمي (EMA/BNF 2025).",
            ))
            continue

        renal_limit = info.get("renal_limit", 0)
        if is_renal and renal_limit > 0 and cl_cr <= renal_limit:
            warned.append({"name": drug, **info, "warning_reason": "renal_adjustment"})
            continue

        # ══════════════════════════════════════════════════════════════════
        # PREGNANCY SAFETY BLOCK
        # Updated per: ACOG 2023, BNF 2025, EMA 2025, ENTIS 2024,
        #              IDSA AMR 2025, WHO AWaRe 2023, BMJ Teratology 2023
        # ══════════════════════════════════════════════════════════════════
        if is_preg:

            # ── 1. Tetracyclines: ALWAYS BANNED (class-based override) ────────
            # Bypasses preg_status value — even if "Safe" by mistake in data.
            # Mechanism: chelation into fetal bone/cartilage → permanent
            # teeth staining + inhibited bone growth (esp. after week 15).
            # ACOG 2023 / BNF 2025 / CLSI: absolute contraindication.
            if "tetracycline" in cls:
                banned.append(build_banned_item(
                    drug, "pregnancy",
                    "⛔ ممنوع في الحمل — Tetracyclines.",
                    "Tetracyclines (Doxycycline / Tetracycline / Minocycline / Tigecycline):\n"
                    "تترسّب في عظام وأسنان الجنين → تصبغ دائم للأسنان وتثبيط نمو العظام.\n"
                    "محظورة في كل مراحل الحمل (خاصة بعد الأسبوع 15).\n"
                    "ACOG 2023 / BNF 2025: contraindication مطلقة.\n"
                    "البديل: Azithromycin (atypicals) | Amoxicillin-Clavulanate | Cephalosporin.",
                ))
                continue

            # ── 2. Aminoglycosides: ALWAYS BANNED ────────────────────────────
            # preg_status = "Banned" in data — but add class-level safety net.
            # Cross placenta → cochlear hair cell damage → permanent hearing loss.
            if "aminoglycoside" in cls:
                preg_note = info.get("preg_note") or (
                    "⛔ ممنوع في الحمل — Aminoglycosides.\n"
                    "يعبر المشيمة → سُمية للأذن الجنينية (ototoxicity) → فقدان سمع دائم.\n"
                    "FDA Category D / ACOG: contraindication."
                )
                banned.append(build_banned_item(
                    drug, "pregnancy",
                    preg_note.splitlines()[0],
                    preg_note,
                ))
                continue

            # ── 3. TMP-SMX & Sulfonamides: BANNED ────────────────────────────
            # 1st trim: Trimethoprim = folate antagonist → neural tube defects.
            # 3rd trim: Sulfonamides displace bilirubin → neonatal kernicterus.
            # No safe trimester window → ban throughout.
            # preg_status = "Banned" in data, but add name/class-based safety net.
            if (info.get("preg_status") == "Banned"
                    and ("sulfonamide" in cls or "trimethoprim" in d_low
                         or "sulfamethox" in d_low)):
                preg_note = info.get("preg_note") or (
                    "⛔ ممنوع في الحمل — TMP/SMX.\n"
                    "Trimethoprim: مضاد حمض الفوليك → neural tube defects (1st trim).\n"
                    "Sulfonamides: تنافس bilirubin → kernicterus نووي (3rd trim).\n"
                    "البديل: Nitrofurantoin (1st/2nd trim) | Fosfomycin | Cephalexin."
                )
                banned.append(build_banned_item(
                    drug, "pregnancy",
                    preg_note.splitlines()[0],
                    preg_note,
                ))
                continue

            # ── 4. Clarithromycin: BANNED ─────────────────────────────────────
            # Linked to cardiovascular malformations in cohort studies (JAMA 2019).
            # BNF 2025: avoid in pregnancy. Azithromycin is the safe macrolide.
            if "clarithromycin" in d_low:
                preg_note = info.get("preg_note") or (
                    "⛔ ممنوع في الحمل — Clarithromycin.\n"
                    "ارتبط بتشوهات قلبية خلقية (JAMA 2019 cohort study).\n"
                    "BNF 2025: تجنّب في الحمل.\n"
                    "البديل الآمن: Azithromycin."
                )
                banned.append(build_banned_item(
                    drug, "pregnancy",
                    preg_note.splitlines()[0],
                    preg_note,
                ))
                continue

            # ── 5. Linezolid: BANNED ──────────────────────────────────────────
            # preg_status = "Banned" in data. Animal teratogenicity data.
            # No human safety data → reserve for life-threatening situations only.
            if "linezolid" in d_low or info.get("preg_status") == "Banned":
                preg_note = info.get("preg_note") or "⛔ ممنوع في الحمل."
                banned.append(build_banned_item(
                    drug, "pregnancy",
                    preg_note.splitlines()[0],
                    preg_note,
                ))
                continue

            # ── 6. Fluoroquinolones: USE WITH CAUTION ────────────────────────
            # Risk of arthropathy (cartilage) historically overstated.
            # ENTIS 2024 / BMJ 2023: no significant teratogenicity signal.
            # Still NOT first-line in pregnancy — use only when no safer alternative.
            # Decision stays with treating physician.
            if "fluoroquinolone" in cls:
                preg_warn_items.append({
                    "name": drug, **info,
                    "preg_note": info.get("preg_note") or (
                        "⚠️ Use with Caution — Fluoroquinolone في الحمل:\n"
                        "الأدلة الحديثة (ENTIS 2024): خطر التشوهات أقل مما كان يُعتقد.\n"
                        "لا يُستخدم كخط أول — فقط عند غياب البديل الأكثر أمانًا.\n"
                        ">>> القرار النهائي للطبيب المعالج حصراً. <<<"
                    ),
                })
                continue

            # ── 7. Nitrofurantoin: CAUTION (trimester-dependent) ─────────────
            # Safe in 1st and 2nd trimester for UTI.
            # AVOID at term (≥36 weeks) / 3rd trimester:
            # risk of hemolytic anemia (G6PD) and neonatal hemolysis.
            # Alternative in 3rd trim: Fosfomycin (single dose) or Cephalexin.
            if "nitrofurantoin" in d_low:
                preg_warn_items.append({
                    "name": drug, **info,
                    "preg_note": info.get("preg_note") or (
                        "⚠️ Nitrofurantoin — Use with Caution في الحمل:\n"
                        "✅ مسموح في الـ 1st و 2nd trimester (ACOG 2023).\n"
                        "⛔ تجنّب في الـ 3rd trimester وعند الـ term (≥36 أسبوع):\n"
                        "   خطر hemolytic anemia جنينية (G6PD) ونيونيتل hemolysis.\n"
                        "البديل في 3rd trim: Fosfomycin جرعة واحدة أو Cephalexin.\n"
                        ">>> القرار النهائي للطبيب المعالج حسب الـ trimester. <<<"
                    ),
                })
                continue

            # ── 8. Metronidazole: CAUTION (1st trim preference) ──────────────
            # ACOG 2021: historical carcinogenicity concern is NOT supported
            # by human evidence. Acceptable in all trimesters when medically needed.
            # Still preferred to avoid in 1st trim if alternative exists.
            if "nitroimidazole" in cls or "metronidazole" in d_low:
                preg_warn_items.append({
                    "name": drug, **info,
                    "preg_note": info.get("preg_note") or (
                        "⚠️ Metronidazole — Use with Caution:\n"
                        "ACOG 2021: مقبول في كل trimesters عند الضرورة.\n"
                        "يُفضل تجنبه في الـ 1st trimester إن وُجد بديل آمن.\n"
                        ">>> القرار النهائي للطبيب المعالج حصراً. <<<"
                    ),
                })
                continue

            # ── 9. Carbapenems (Warn): acceptable in severe infection ─────────
            # Meropenem: relatively more data, preferred over Imipenem.
            # Imipenem: limited human data — use Meropenem if possible.
            if "carbapenem" in cls and info.get("preg_status") == "Warn":
                preg_warn_items.append({"name": drug, **info})
                continue

            # ── 10. Vancomycin / Colistin: Warn → physician decides ───────────
            # Life-threatening infections → benefit outweighs risk.
            # Vancomycin: monitor renal function + fetal hearing.
            # Colistin: last resort XDR — no alternative.
            if info.get("preg_status") == "Warn":
                preg_warn_items.append({"name": drug, **info})
                continue

        if culture_result == "I":
            warned.append({"name": drug, **info, "warning_reason": "intermediate_culture"})
            continue

        allowed.append({"name": drug, **info})

    allowed         = sorted(allowed,         key=lambda x: x.get("priority", 999))
    warned          = sorted(warned,          key=lambda x: x.get("priority", 999))
    preg_warn_items = sorted(preg_warn_items, key=lambda x: x.get("priority", 999))

    # ── Specimen-appropriateness filter ───────────────────────────────────────
    # Urine-only agents achieve therapeutic concentrations ONLY in urine:
    #   • Nitrofurantoin / Fosfomycin (oral): negligible serum & tissue levels
    #     → useless for bacteremia, pneumonia, wound, meningitis.
    #   • Norfloxacin: poor serum levels → urinary (and some GI) use only.
    # Previously these were only removed for stool; for blood/sputum/wound/CSF
    # they leaked into the "allowed" list. Now they are BANNED (with a reason)
    # for every non-urine systemic specimen so the clinician sees why.
    _spec_l     = culture_type.lower()
    is_urine    = "urine" in _spec_l
    is_stool_gi = any(k in _spec_l for k in ["stool", "fecal", "rectal"])

    if not is_urine:
        if is_stool_gi:
            _urine_only = {"Nitrofurantoin", "Fosfomycin"}   # Norfloxacin has GI use
            _reason = ("عامل بولي فقط — لا يصل لتركيز علاجي داخل الأمعاء؛ "
                       "غير مناسب لعدوى الجهاز الهضمي.")
        else:
            _urine_only = {"Nitrofurantoin", "Fosfomycin", "Norfloxacin"}
            _reason = ("عامل بولي فقط — لا يحقق تركيزاً علاجياً في الدم أو الأنسجة؛ "
                       "غير مناسب للعدوى الجهازية (دم / رئة / جرح / سائل نخاعي). "
                       "(ملاحظة: Fosfomycin الوريدي استثناء غير متوفر في هذه القائمة.)")
        _moved = ({d["name"] for d in allowed if d.get("name") in _urine_only} |
                  {d["name"] for d in warned  if d.get("name") in _urine_only})
        allowed = [d for d in allowed if d.get("name") not in _urine_only]
        warned  = [d for d in warned  if d.get("name") not in _urine_only]
        for _nm in sorted(_moved):
            banned.append(build_banned_item(
                _nm, "specimen",
                "عامل بولي فقط — غير مناسب لهذه العينة.", _reason,
            ))

    return allowed, warned, banned, preg_warn_items, sorted(set(interactions_alerts))

def _remove_intrinsic_resistance(organism: str, sir_map: Dict[str, str]) -> Dict[str, str]:
    """Drop drugs the organism is intrinsically resistant to (not acquired)."""
    org_l = organism.lower().strip()
    drugs_to_drop = set()
    for org_key, drug_list in INTRINSIC_RESISTANCE.items():
        if org_key in org_l or org_l in org_key:
            drugs_to_drop.update(drug_list)
    if not drugs_to_drop:
        return dict(sir_map)
    return {d: v for d, v in sir_map.items() if d not in drugs_to_drop}

def classify_mdr(organism: str, sir_map: Dict[str, str]) -> Dict[str, Any]:
    """
    MDR/XDR/PDR classification — Magiorakos et al. 2012 (ECDC/CDC).
    Key principles implemented:
    • Non-susceptible = R + I (not R alone)
    • Intrinsic resistance excluded before counting
    • Gram-pos / Gram-neg category sets applied per organism
    • A category counts as SUSCEPTIBLE if the isolate is susceptible to ≥1
      tested agent representing it (a usable option exists in that class —
      e.g. Cefoperazone R + Cefoperazone/Sulbactam S ⇒ that cephalosporin
      category is still an option, NOT counted toward MDR/XDR).
      It only counts as non-susceptible when EVERY tested agent in the
      category is R or I (no active option left in that class).
    • Reliability warning when too few categories testable
    """
    if not sir_map:
        return {
            "level": None, "resistant_categories": [], "susceptible_categories": [],
            "total_tested": 0, "total_categories_evaluable": 0, "resistant_count": 0,
            "single_drug_categories": [], "reliable": False, "warnings": [], "gram": "",
        }

    # 1. Strip intrinsic resistance
    clean_map = _remove_intrinsic_resistance(organism, sir_map)

    # 2. Choose category set — Magiorakos defines SEPARATE panels for
    #    Enterobacterales / Pseudomonas / Acinetobacter (and gram-positives),
    #    so pick the organism-specific panel rather than one shared GN table.
    org_l = organism.lower().strip()
    is_gram_pos = any(g in org_l for g in GRAM_POSITIVE_ORGANISMS)
    applicable = get_mdr_panel(organism, is_gram_pos)

    resistant_cats     = []
    susceptible_cats   = []
    single_drug_cats   = []   # categories judged on only 1 tested agent

    for cat, drugs in MDR_CATEGORIES.items():
        if cat not in applicable:
            continue
        tested = [d for d in drugs if d in clean_map]
        if not tested:
            continue
        if len(tested) == 1:
            single_drug_cats.append(cat)
        # Susceptible to >=1 tested agent in the category => category is a
        # usable option, not counted as non-susceptible — even if another
        # agent in the same category is R/I. Only when NO tested agent is S
        # (i.e. non-susceptible to all of them) does the category count.
        if any(clean_map.get(d) == "S" for d in tested):
            susceptible_cats.append(cat)
        else:
            resistant_cats.append(cat)

    total_cats = len(resistant_cats) + len(susceptible_cats)
    r_count    = len(resistant_cats)

    if total_cats == 0:
        return {
            "level": None, "resistant_categories": [], "susceptible_categories": susceptible_cats,
            "total_tested": 0, "total_categories_evaluable": 0, "resistant_count": 0,
            "single_drug_categories": single_drug_cats, "reliable": False, "warnings": [],
            "gram": "positive" if is_gram_pos else "negative",
        }

    # XDR/PDR require enough categories tested to be meaningful (Magiorakos:
    # XDR = susceptible to ≤2 categories out of the full applicable panel).
    # Without a broad panel we cannot reliably call XDR/PDR → cap at MDR.
    _enough_for_xdr = total_cats >= 6

    # A category judged on a SINGLE tested agent is weak evidence (one disc can
    # be an error). XDR/PDR is a severe call and must rest on categories
    # confirmed by ≥2 agents; require ≥3 multi-agent resistant categories.
    _single = set(single_drug_cats)
    _multidrug_resistant = [c for c in resistant_cats if c not in _single]
    _enough_multidrug = len(_multidrug_resistant) >= 3

    if r_count >= total_cats and _enough_for_xdr and _enough_multidrug:
        level = "PDR"
    elif (total_cats - r_count) <= 2 and r_count >= 3 and _enough_for_xdr and _enough_multidrug:
        level = "XDR"
    elif r_count >= 3:
        level = "MDR"
    else:
        level = None

    # If pattern looks like XDR/PDR but evidence is too thin (few categories, or
    # resistant categories rest mostly on single agents), flag but hold at MDR.
    _capped = False
    if r_count >= 3 and (total_cats - r_count) <= 2 and not (_enough_for_xdr and _enough_multidrug):
        _capped = True

    # Reliability flag
    reliable = total_cats >= 4
    warnings = []
    if not reliable:
        warnings.append(f"⚠️ Only {total_cats} categories testable — MDR classification may be unreliable.")
    if single_drug_cats:
        warnings.append(f"⚠️ Categories judged on a single agent: {', '.join(single_drug_cats)}")
    if _capped:
        warnings.append("⚠️ Resistance pattern suggests XDR/PDR, but the evidence is too thin "
                        "(few categories, or resistant categories rest on a single agent each) — "
                        "reported as MDR. Expand the panel with ≥2 agents per category to confirm.")

    return {
        "level":                  level,
        "resistant_categories":   resistant_cats,
        "susceptible_categories": susceptible_cats,
        "total_tested":           total_cats,
        "total_categories_evaluable": total_cats,
        "resistant_count":        r_count,
        "single_drug_categories": single_drug_cats,
        "reliable":               reliable,
        "warnings":               warnings,
        "gram":                   "positive" if is_gram_pos else "negative",
    }

def predict_esbl(organism: str, sir_map: Dict[str, str]) -> Dict[str, Any]:
    """
    Predict ESBL / AmpC / Carbapenemase from the resistance phenotype.
    Returns probability + confidence (0-100) + mechanism + markers.

    Logic (EUCAST/CLSI):
    • ESBL  : R to ≥1 primary 3rd-gen cephalosporin (Ceftriaxone/Cefotaxime/Ceftazidime)
    • AmpC  : 3rd-gen R + Cefoxitin R (in AmpC-prone organism)
    • Carbapenemase tiers:
        - OXA-48 suspicion : Ertapenem R, Meropenem S/I
        - high             : ≥2 carbapenems R
        - moderate         : 1 carbapenem R (or Meropenem I)
    """
    if not sir_map:
        return {"probability": None, "confidence": 0, "mechanism": "",
                "markers_R": [], "detail": "", "action": ""}

    org_l = organism.lower().strip()
    is_producer = any(p in org_l or org_l in p for p in ESBL_PRODUCERS)
    is_ampc_prone = any(p in org_l or org_l in p for p in AMPC_PRODUCERS)
    if not is_producer and not is_ampc_prone:
        return {"probability": None, "confidence": 0, "mechanism": "",
                "markers_R": [], "detail": "", "action": ""}

    def _ns(drug):  # non-susceptible = R or I
        return sir_map.get(drug) in ("R", "I")
    def _r(drug):
        return sir_map.get(drug) == "R"

    primary_R = [d for d in ESBL_MARKERS["primary"] if _r(d)]
    second_R  = [d for d in ESBL_MARKERS["secondary"] if _r(d)]
    med_R     = [d for d in ESBL_MARKERS["medium"] if _r(d)]
    cefoxitin_R = _r("Cefoxitin")
    # كم marker أساسي (3rd-gen cephalosporin) تم اختباره فعلاً؟ الثقة في تفسير
    # ESBL تعتمد على اتساع اللوحة: R لدواء واحد بينما البقية غير مُختبَرة أضعف.
    primary_tested = [d for d in ESBL_MARKERS["primary"] if d in sir_map]
    _thin_panel = len(primary_tested) < 2

    carb_R_list = [d for d in CARBAPENEMS if _r(d)]
    erta_R   = _r("Ertapenem")
    mero_R   = _r("Meropenem")
    mero_I   = sir_map.get("Meropenem") == "I"
    
    # ── 1. Carbapenemase tiers (highest priority) ─────────────────────────
    if len(carb_R_list) >= 2:
        return {
            "probability": "carbapenemase",
            "confidence": 92,
            "mechanism": "Carbapenemase (KPC / MBL / OXA-48-like) — Predicted",
            "markers_R": carb_R_list + primary_R,
            "detail": f"مقاومة لـ ≥2 كاربابينيم ({', '.join(carb_R_list)}) — نمط Carbapenemase صريح.",
            "action": "أرسل للمختبر المرجعي فوراً (PCR/mCIM). عزل صارم. Colistin/Ceftazidime-Avibactam.",
        }
    if erta_R and (sir_map.get("Meropenem") in ("S", "I")) and not mero_R:
        # Classic OXA-48 fingerprint — common in Egypt / Middle East
        return {
            "probability": "carbapenemase",
            "confidence": 70,
            "mechanism": "Possible OXA-48-like carbapenemase — Predicted",
            "markers_R": ["Ertapenem"] + primary_R,
            "detail": "Ertapenem R مع Meropenem S/I — نمط مُوحٍ بـ OXA-48 (شائع في مصر/الشرق الأوسط).",
            "action": "أكد بـ mCIM / PCR (OXA-48). راقب بحذر؛ قد تكون الكاربابينيمات أقل فعالية.",
        }
    if len(carb_R_list) == 1 or mero_I:
        return {
            "probability": "carbapenemase",
            "confidence": 55,
            "mechanism": "Possible carbapenemase (low-level) — Predicted",
            "markers_R": carb_R_list or ["Meropenem (I)"],
            "detail": "مقاومة/توسط لكاربابينيم واحد — يستلزم اختبار تأكيدي.",
            "action": "أجرِ mCIM/CarbaNP. قد يكون فقدان بورين + ESBL/AmpC وليس carbapenemase حقيقياً.",
        }

    # ── 2. AmpC (3rd-gen R + Cefoxitin R in AmpC-prone) ───────────────────
    if is_ampc_prone and primary_R and cefoxitin_R:
        return {
            "probability": "ampc",
            "confidence": 75,
            "mechanism": "Possible AmpC β-lactamase (Predicted)",
            "markers_R": primary_R + ["Cefoxitin"],
            "detail": "مقاومة لـ 3rd-gen + Cefoxitin في كائن AmpC-prone — نمط AmpC وليس ESBL.",
            "action": "تجنب 3rd-gen cephalosporins حتى لو S. استخدم Cefepime أو Carbapenem. لا يُكتشف بـ DDST.",
        }

    # ── 3. ESBL ───────────────────────────────────────────────────────────
    if len(primary_R) >= 2:
        return {
            "probability": "high",
            "confidence": 88,
            "mechanism": "ESBL (Extended-Spectrum β-Lactamase) — Predicted",
            "markers_R": primary_R + second_R,
            "detail": f"مقاومة لـ {', '.join(primary_R)} — احتمال ESBL مرتفع.",
            "action": "استخدم Carbapenem للعدوى الشديدة (MERINO 2018). تجنب جميع cephalosporins.",
        }
    if len(primary_R) == 1:
        # Classic single-marker ESBL pattern (e.g., Ceftriaxone R, Meropenem S)
        carbS = any(sir_map.get(d) == "S" for d in CARBAPENEMS)
        _base_conf = 72 if carbS else 60
        # لوحة رفيعة (marker أساسي واحد مُختبَر فقط) → خفّض الثقة.
        if _thin_panel:
            _base_conf = min(_base_conf, 45)
        _detail = f"مقاومة لـ {primary_R[0]}" + (
            " مع كاربابينيم حساس — نمط ESBL كلاسيكي." if carbS else ".")
        if _thin_panel:
            _detail += (" ⚠️ لوحة محدودة: تم اختبار سيفالوسبورين أساسي واحد فقط "
                        "— التفسير أقل موثوقية؛ وسّع اللوحة (Ceftazidime/Cefotaxime).")
        return {
            "probability": ("high" if carbS else "moderate") if not _thin_panel else "moderate",
            "confidence": _base_conf,
            "mechanism": "Probable ESBL — Predicted",
            "markers_R": primary_R + med_R,
            "detail": _detail,
            "action": "أكد بـ Double-Disk Synergy Test (DDST) أو PCR. عامل كـ ESBL حتى التأكيد.",
        }
    if len(med_R) >= 2:
        return {
            "probability": "moderate",
            "confidence": 50,
            "mechanism": "Possible ESBL (lower-gen cephalosporin resistance) — Predicted",
            "markers_R": med_R,
            "detail": "مقاومة لـ ≥2 من الجيل الأقل — يستدعي تأكيد ESBL.",
            "action": "أجرِ DDST. قد يكون ESBL مبكر أو آلية أخرى.",
        }

    return {"probability": "low", "confidence": 10, "mechanism": "",
            "markers_R": [], "detail": "", "action": ""}

def assess_pathogenicity(
    specimen: str,
    organism: str,
    colony_count_text: str,
    culture_purity: str,
    symptoms: list,
    pus_cells_text: str,
    urinalysis_result: str,
    gram_stain: str,
    age: int,
    sex: str,
    host_factors: list,
    # Sputum-specific
    sputum_pus_cells: str = "",
    sputum_epithelial: str = "",
    # Blood-specific (SIRS)
    sirs_criteria: list = None,
    blood_source: str = "",
    # Wound-specific
    wound_type: str = "",
) -> dict:
    """
    Pathogenicity Score Engine v2
    Returns: {score, verdict, color, interpretation, recommendations,
              factors_pos, factors_neg, abu_detected, special_flags}
    """
    if sirs_criteria is None:
        sirs_criteria = []

    score        = 0
    factors_pos  = []
    factors_neg  = []
    special_flags = []
    abu_detected  = False

    # ── Organism Lists ────────────────────────────────────────────────
    TYPICAL_UROPATHOGENS = [
        "Escherichia coli", "Klebsiella pneumoniae", "Klebsiella spp.",
        "Proteus mirabilis", "Proteus spp.", "Enterococcus faecalis",
        "Enterococcus spp.", "Staphylococcus saprophyticus",
        "Pseudomonas aeruginosa", "Enterobacter spp.", "Enterobacter cloacae",
        "Citrobacter spp.", "Morganella morganii", "Serratia marcescens",
    ]
    ATYPICAL_UROPATHOGENS = [
        "Staphylococcus aureus", "MRSA", "Staphylococcus epidermidis",
        "Streptococcus viridans", "Corynebacterium spp.",
        "Candida albicans", "Candida spp.",
    ]
    NORMAL_SKIN_FLORA = [
        "Staphylococcus epidermidis", "Corynebacterium spp.",
        "Streptococcus viridans",
    ]
    RESPIRATORY_PATHOGENS = [
        "Streptococcus pneumoniae", "Haemophilus influenzae",
        "Klebsiella pneumoniae", "Pseudomonas aeruginosa",
        "Staphylococcus aureus", "MRSA", "Moraxella catarrhalis",
        "Acinetobacter baumannii", "Enterobacter spp.",
        "Escherichia coli", "Serratia marcescens",
        "Stenotrophomonas maltophilia", "Legionella pneumophila",
        "Mycoplasma spp.",
    ]
    URT_CONTAMINANTS_SPUTUM = [
        "Streptococcus viridans", "Neisseria spp.", "Candida spp.",
        "Candida albicans", "Staphylococcus epidermidis",
        "Corynebacterium spp.",
    ]
    TRUE_BLOOD_PATHOGENS = [
        "Staphylococcus aureus", "MRSA", "Streptococcus pneumoniae",
        "Escherichia coli", "Klebsiella pneumoniae", "Pseudomonas aeruginosa",
        "Acinetobacter baumannii", "Enterococcus faecalis", "Enterococcus spp.",
        "VRE", "Proteus mirabilis", "Salmonella spp.", "H. influenzae",
        "Anaerobes (لاهوائيات)", "Stenotrophomonas maltophilia",
        "Candida albicans", "Candida spp.",
        "Neisseria meningitidis", "Listeria monocytogenes",
    ]
    BLOOD_CONTAMINANTS = [
        "Staphylococcus epidermidis", "Corynebacterium spp.",
        "Bacillus spp.", "Propionibacterium spp.", "Micrococcus spp.",
    ]

    # Route on the single canonical classifier so the engine and the UI can
    # never disagree about what a specimen is (see classify_specimen).
    cat = classify_specimen(specimen)

    # ══════════════════════════════════════════════════════════════════
    # URINE
    # ══════════════════════════════════════════════════════════════════
    if cat == "urine":

        # Pediatric threshold: < 2 years → any growth significant
        if age < 2:
            score += 20
            factors_pos.append("✅ Infant < 2 yrs — any colony count clinically significant")
            special_flags.append("PEDIATRIC_UTI")

        # Organism context
        if _org_in(organism, TYPICAL_UROPATHOGENS):
            score += 20
            factors_pos.append(f"✅ {organism} — typical uropathogen")
        elif _org_in(organism, ATYPICAL_UROPATHOGENS):
            score -= 20
            factors_neg.append(f"⚠️ {organism} — atypical uropathogen; consider contamination or hematogenous seeding")
        else:
            score += 5
            factors_pos.append(f"➕ {organism} — occasional uropathogen")

        # Colony count
        cfu_val = _parse_cfu(colony_count_text)
        if age < 2:
            # Pediatric: ≥ 10⁴ = significant
            if cfu_val >= 10000:
                score += 20
                factors_pos.append("✅ Colony count ≥ 10⁴ CFU/mL (significant for age < 2)")
            elif cfu_val > 0:
                score += 5
                factors_pos.append(f"➕ Colony count {cfu_val:,} — borderline (pediatric)")
        elif sex == "Female" and age >= 12:
            # IDSA: ≥ 10³ symptomatic, ≥ 10⁵ asymptomatic
            if cfu_val >= 100000:
                score += 25
                factors_pos.append("✅ Colony count ≥ 10⁵ CFU/mL — significant bacteriuria")
            elif cfu_val >= 1000:
                score += 12
                factors_pos.append("➕ Colony count 10³–10⁵ — significant if symptomatic (female)")
            elif cfu_val > 0:
                score -= 10
                factors_neg.append(f"⚠️ Colony count {cfu_val:,} < 10³ — likely insignificant")
        else:
            # Male / general
            if cfu_val >= 100000:
                score += 25
                factors_pos.append("✅ Colony count ≥ 10⁵ CFU/mL — significant bacteriuria")
            elif cfu_val >= 10000:
                score += 10
                factors_pos.append("➕ Colony count 10⁴–10⁵ CFU/mL — borderline")
            elif cfu_val > 0:
                score -= 15
                factors_neg.append(f"⚠️ Colony count {cfu_val:,} < 10⁴ — likely insignificant")

        # Pyuria / Urinalysis
        pus_val = _parse_pus(pus_cells_text)
        if pus_val is not None:
            if pus_val > 10:
                score += 20
                factors_pos.append(f"✅ Significant pyuria ({pus_val} WBC/HPF)")
            elif pus_val >= 5:
                score += 10
                factors_pos.append(f"➕ Mild pyuria ({pus_val} WBC/HPF)")
            else:
                score -= 15
                factors_neg.append(f"⚠️ No/minimal pyuria ({pus_val} WBC/HPF) — argues against UTI")
        elif "طبيعي" in urinalysis_result or "normal" in urinalysis_result.lower():
            score -= 25
            factors_neg.append("❌ Normal urinalysis — strongly suggests contamination")
        elif "pyuria" in urinalysis_result.lower() or "wbc" in urinalysis_result.lower():
            score += 15
            factors_pos.append("✅ Pyuria noted on urinalysis")
        elif "nitrit" in urinalysis_result.lower():
            score += 10
            factors_pos.append("➕ Nitrites positive — bacterial activity")

        # ABU Detection
        classic_symp = [s for s in symptoms if s in [
            "Dysuria / Frequency / Urgency", "Fever (> 38°C)", "Flank pain / Loin pain"
        ]]
        if not classic_symp and cfu_val >= 100000 and pus_val is not None and pus_val >= 5:
            abu_detected = True
            special_flags.append("ABU_DETECTED")
            # ABU: treat only if pregnant or pre-surgery
            if "Pregnant" in host_factors or "Pre-surgical" in host_factors:
                score += 20
                factors_pos.append("✅ ABU in high-risk context (pregnancy/pre-op) — TREAT")
                special_flags.append("ABU_TREAT")
            else:
                score -= 20
                factors_neg.append("⚠️ Asymptomatic Bacteriuria (ABU) — Do NOT treat (IDSA 2019)")
                special_flags.append("ABU_NO_TREAT")

        # Sex & Age context
        if sex == "Female":
            score += 10
            factors_pos.append("➕ Female — higher UTI prevalence")
        if sex == "Male" and 15 <= age <= 50:
            score -= 5
            factors_neg.append("⚠️ Male (non-pediatric/non-elderly) — UTI uncommon")
        if sex == "Male" and age > 50:
            score += 10
            factors_pos.append("➕ Male > 50 — prostatic age, any UTI is significant")
        if age < 1:
            score += 15
            factors_pos.append("✅ Infant < 1 yr — all UTIs require treatment")

    # ══════════════════════════════════════════════════════════════════
    # SPUTUM — Murray-Washington criteria
    # ══════════════════════════════════════════════════════════════════
    elif cat in ("sputum", "respiratory"):
        # Expectorated sputum ('sputum') AND lower-respiratory aspirates
        # ('respiratory': BAL / bronchial / tracheal) share pathogen + symptom
        # scoring. Murray-Washington below only fires when WBC/epithelial counts
        # are supplied — the UI supplies them for expectorated sputum only, so
        # BAL is correctly scored WITHOUT Murray-Washington.

        # Murray-Washington score from WBCs & epithelial cells
        mw_pus   = _parse_pus(sputum_pus_cells)   # WBC/LPF
        mw_epith = _parse_pus(sputum_epithelial)   # Epithelial cells/LPF

        if mw_pus is not None and mw_epith is not None:
            if mw_pus >= 25 and mw_epith < 10:
                score += 30
                factors_pos.append("✅ Murray-Washington Grade ≥4: WBC≥25, Epi<10/LPF — Adequate sputum")
                special_flags.append("MW_ADEQUATE")
            elif mw_pus >= 25 and mw_epith >= 10:
                score += 10
                factors_pos.append("➕ Murray-Washington: WBC≥25 but Epi≥10 — mixed quality")
                special_flags.append("MW_MIXED")
            elif mw_epith >= 25:
                score -= 20
                factors_neg.append("❌ Murray-Washington: Epi≥25/LPF — heavily contaminated, reject specimen")
                special_flags.append("MW_REJECT")
            else:
                score += 5
        elif mw_epith is not None and mw_epith >= 25:
            score -= 20
            factors_neg.append("❌ Epithelial cells ≥25/LPF — specimen inadequate (saliva)")
            special_flags.append("MW_REJECT")

        # Organism context
        if _org_in(organism, RESPIRATORY_PATHOGENS):
            score += 20
            factors_pos.append(f"✅ {organism} — recognized respiratory pathogen")
        elif _org_in(organism, URT_CONTAMINANTS_SPUTUM):
            score -= 20
            factors_neg.append(f"⚠️ {organism} — likely URT/oropharyngeal contaminant")
        else:
            score += 5

        # Symptoms
        resp_symp = [s for s in symptoms if s in [
            "Productive cough / Purulent sputum",
            "Fever (> 38°C)", "Dyspnea", "Pleuritic chest pain"
        ]]
        if len(resp_symp) >= 2:
            score += 20
            factors_pos.append(f"✅ {len(resp_symp)} respiratory symptoms present")
        elif len(resp_symp) == 1:
            score += 10
            factors_pos.append("➕ 1 respiratory symptom present")

    # ══════════════════════════════════════════════════════════════════
    # BLOOD CULTURE — SIRS criteria
    # ══════════════════════════════════════════════════════════════════
    elif cat == "blood":

        # SIRS criteria (≥2 = SIRS, ≥3 = high probability sepsis)
        sirs_count = len(sirs_criteria)
        if sirs_count >= 3:
            score += 35
            factors_pos.append(f"✅ {sirs_count}/4 SIRS criteria met — high sepsis probability")
            special_flags.append("SIRS_HIGH")
        elif sirs_count == 2:
            score += 20
            factors_pos.append("➕ 2/4 SIRS criteria met — bacteremia possible")
            special_flags.append("SIRS_MET")
        elif sirs_count == 1:
            score += 10
            factors_pos.append("➕ 1 SIRS criterion — low probability bacteremia")
        else:
            score += 5
            factors_neg.append("⚠️ No SIRS criteria — consider contaminant especially for CoNS")

        # Organism type
        if _org_in(organism, TRUE_BLOOD_PATHOGENS):
            score += 25
            factors_pos.append(f"✅ {organism} — true bloodstream pathogen; single positive = significant")
        elif _org_in(organism, BLOOD_CONTAMINANTS):
            score -= 20
            factors_neg.append(f"⚠️ {organism} — common blood culture contaminant (CoNS/Coryne); requires ≥2 bottles")
            special_flags.append("BLOOD_CONTAMINANT_RISK")
        else:
            score += 15
            factors_pos.append(f"➕ {organism} — possible bloodstream pathogen")

        # Number of positive bottles
        if "Multiple bottles positive" in blood_source:
            score += 15
            factors_pos.append("✅ Multiple blood culture bottles positive — true bacteremia")
        elif "Single bottle" in blood_source and _org_in(organism, BLOOD_CONTAMINANTS):
            score -= 15
            factors_neg.append("⚠️ Single bottle + contaminant organism — likely contamination")

        # Source identified
        if blood_source and "source" in blood_source.lower():
            score += 10
            factors_pos.append(f"➕ Source identified: {blood_source}")

    # ══════════════════════════════════════════════════════════════════
    # CSF
    # ══════════════════════════════════════════════════════════════════
    elif cat == "csf":
        score += 40
        factors_pos.append("✅ CSF — any growth is always clinically significant (sterile site)")
        special_flags.append("CSF_ALWAYS_SIGNIFICANT")
        # Skin flora (CoNS/Coryne/Propioni/Bacillus) can contaminate LP samples.
        if _org_in(organism, BLOOD_CONTAMINANTS):
            factors_neg.append(
                f"⚠️ {organism} is common skin flora — without a CNS device "
                "(VP shunt / EVD) or ≥2 concordant cultures, consider LP "
                "contamination. Treat empirically until excluded."
            )

    # ══════════════════════════════════════════════════════════════════
    # STOOL / GI
    # ══════════════════════════════════════════════════════════════════
    elif cat == "stool":

        # GI-specific pathogens always significant
        GI_TRUE_PATHOGENS = [
            "Salmonella spp.", "Shigella spp.", "Campylobacter spp.",
            "Clostridioides difficile", "Clostridium difficile",
            "Yersinia enterocolitica", "Vibrio cholerae", "Listeria monocytogenes",
            "Enterohemorrhagic E. coli", "Escherichia coli O157:H7",
            "Entamoeba histolytica",
        ]
        GI_NORMAL_FLORA = [
            "Escherichia coli", "Klebsiella spp.", "Klebsiella pneumoniae",
            "Enterococcus faecalis", "Enterococcus spp.",
            "Proteus mirabilis", "Proteus spp.",
        ]

        if _org_in(organism, GI_TRUE_PATHOGENS):
            score += 40
            factors_pos.append(f"✅ {organism} — obligate GI pathogen; always clinically significant")
            special_flags.append("GI_TRUE_PATHOGEN")
        elif _org_in(organism, GI_NORMAL_FLORA):
            score -= 10
            factors_neg.append(f"⚠️ {organism} — normal GI flora; significance depends on clinical context")
        else:
            score += 15
            factors_pos.append(f"➕ {organism} — potential GI pathogen; correlate clinically")

        # GI Symptoms
        gi_symp = [s for s in symptoms if s in [
            "Fever (> 38°C)", "Bloody diarrhea", "Watery diarrhea",
            "Vomiting", "Abdominal cramps",
        ]]
        if len(gi_symp) >= 2:
            score += 25
            factors_pos.append(f"✅ {len(gi_symp)} GI symptoms — supports true infection")
        elif len(gi_symp) == 1:
            score += 10
        else:
            score -= 10
            factors_neg.append("⚠️ No GI symptoms — most stool cultures positive without symptoms = colonization")

        # Most GI infections: antibiotics often NOT indicated
        factors_neg.append("⚠️ Most GI infections: supportive care preferred; antibiotics only for severe/immunocompromised")

    # ══════════════════════════════════════════════════════════════════
    # WOUND / PUS
    # ══════════════════════════════════════════════════════════════════
    elif cat == "wound":
        # Only true wound/pus/abscess/tissue specimens reach here. Genital,
        # throat and other swabs are NOT wounds — they fall through to the
        # shared factors below (generic scoring), which is clinically correct.
        wound_lower = wound_type.lower() if wound_type else ""

        if _org_in(organism, NORMAL_SKIN_FLORA) and not wound_lower:
            score += 10
            factors_pos.append(f"➕ {organism} — possible wound pathogen, assess clinical context")
        else:
            score += 25
            factors_pos.append(f"✅ {organism} — likely wound pathogen")

        # Wound type context
        if "surgical" in wound_lower or "post-op" in wound_lower:
            score += 15
            factors_pos.append("✅ Post-surgical wound — any growth is significant")
        elif "chronic" in wound_lower or "diabetic" in wound_lower:
            score += 10
            factors_pos.append("➕ Chronic/diabetic wound — higher clinical significance")
        elif "superficial" in wound_lower:
            score -= 5
            factors_neg.append("⚠️ Superficial wound — assess depth and clinical signs")

        # Symptoms
        wound_symp = [s for s in symptoms if s in [
            "Erythema / Warmth / Swelling",
            "Purulent discharge",
            "Fever (> 38°C)",
            "Pain / Tenderness",
        ]]
        if len(wound_symp) >= 2:
            score += 20
            factors_pos.append(f"✅ {len(wound_symp)} local infection signs present")
        elif len(wound_symp) == 1:
            score += 10

    # ══════════════════════════════════════════════════════════════════
    # Shared factors (all specimens)
    # ══════════════════════════════════════════════════════════════════

    # Culture purity
    if culture_purity == "Pure growth":
        score += 15
        factors_pos.append("✅ Pure culture — supports true infection")
    elif culture_purity == "Mixed growth":
        score -= 15
        factors_neg.append("⚠️ Mixed growth — suggests contamination")

    # Gram stain
    if "WBCs + Gram" in gram_stain:
        score += 15
        factors_pos.append("✅ Gram stain: organisms + WBCs — supports infection")
    elif "Organisms" in gram_stain and "بدون" not in gram_stain and "without" not in gram_stain.lower():
        score += 5
        factors_pos.append("➕ Organisms seen on Gram stain")
    elif "طبيعية" in gram_stain or "No organisms" in gram_stain:
        score -= 10
        factors_neg.append("⚠️ Normal Gram stain — no organisms seen")

    # Host factors
    if "Immunosuppressants / Steroids" in host_factors:
        score += 10
        factors_pos.append("➕ Immunocompromised — lower threshold for clinical significance")
    if "Diabetes" in host_factors:
        score += 5
        factors_pos.append("➕ Diabetes — increased infection susceptibility")
    if "تاريخ UTIs متكررة" in host_factors or "Recurrent infections" in host_factors:
        score += 5
        factors_pos.append("➕ Recurrent infection history")
    if "Urinary catheter" in host_factors or "Central line / PICC" in host_factors or "Catheter" in host_factors:
        score += 10
        factors_pos.append("➕ Indwelling device — lower threshold for significance")
    if "Renal abnormality / Vesicoureteral reflux" in host_factors:
        score += 10
        factors_pos.append("➕ Structural abnormality — increased susceptibility")
    if "Pregnant" in host_factors:
        score += 10
        factors_pos.append(
            "✅ Pregnancy — any significant bacteriuria requires treatment"
            if cat == "urine"
            else "✅ Pregnancy — lower threshold for treating significant infection"
        )
    if not host_factors:
        score -= 5
        factors_neg.append("ℹ️ No host risk factors identified")

    # Pediatric global flag
    if age < 3 and "PEDIATRIC_UTI" not in special_flags and cat != "csf":
        score += 5
        factors_pos.append("➕ Young child — higher clinical vigilance warranted")

    # ── Clamp ────────────────────────────────────────────────────────
    score = max(0, min(100, score))

    # ── Verdict ──────────────────────────────────────────────────────
    if "CSF_ALWAYS_SIGNIFICANT" in special_flags:
        verdict = "🔴 ALWAYS SIGNIFICANT — Treat Immediately"
        color   = "error"
        interpretation = "العينة من موقع معقم (CSF) — أي نمو يُعدّ مرضياً بغض النظر عن العوامل الأخرى."
        recommendations = [
            "ابدأ العلاج التجريبي فوراً ريثما تظهر نتيجة الحساسية.",
            "استشر طبيب الأمراض المعدية.",
            "احتجز المريض ومراقبته بشكل مكثف.",
        ]
    elif "MW_REJECT" in special_flags:
        verdict = "🟠 SPECIMEN INADEQUATE — Reject & Repeat"
        color   = "warning"
        interpretation = "العينة غير مناسبة (خلايا طلائية ≥25/LPF). النتيجة تعكس تلوثاً من تجويف الفم لا عدوى حقيقية."
        recommendations = [
            "ارفض العينة وأعِد طلب البلغم بتقنية صحيحة.",
            "يُفضَّل التجميع الصباحي الباكر (Early morning sputum).",
            "فكّر في BAL إذا تعذّر الحصول على عينة مناسبة.",
        ]
    elif "ABU_NO_TREAT" in special_flags:
        verdict = "🟡 ASYMPTOMATIC BACTERIURIA (ABU) — Do NOT Treat"
        color   = "warning"
        interpretation = (
            "تشير المعطيات إلى Asymptomatic Bacteriuria. وفقاً لـ IDSA 2019: "
            "لا يُنصح بالعلاج إلا في الحامل أو قبل تدخل جراحي بولي."
        )
        recommendations = [
            "لا تعطِ مضادات حيوية (Antibiotic Stewardship — IDSA 2019).",
            "تابع المريض وأعِد التقييم إذا ظهرت أعراض.",
            "استثناءات: حمل — قبيل جراحة بولية (Urology pre-op).",
        ]
    elif "ABU_TREAT" in special_flags:
        verdict = "🔴 ABU IN HIGH-RISK CONTEXT — Treat"
        color   = "error"
        interpretation = "ABU في سياق يستوجب العلاج (حمل / تدخل جراحي بولي)."
        recommendations = [
            "اختر مضاداً حيوياً مناسباً للحمل حسب نتيجة الحساسية.",
            "مدة العلاج 5–7 أيام عادةً.",
            "أعِد المزرعة بعد الانتهاء من الدورة للتأكد من الشفاء.",
        ]
    elif score >= 75:
        verdict = "🔴 Likely TRUE INFECTION — Treat"
        color   = "error"
        interpretation = (
            "المؤشرات تدعم بقوة وجود عدوى حقيقية. يُنصح بالعلاج "
            "الموجَّه بنتيجة الحساسية مع مراعاة السياق الكلينيكي."
        )
        recommendations = [
            "ابدأ العلاج بناءً على نتيجة الـ AST.",
            "راعِ شدة الأعراض وعوامل الخطر.",
            "راجع الجرعة حسب الوظيفة الكلوية.",
            "De-escalate بعد 48–72 ساعة إذا تحسّن المريض.",
        ]
    elif score >= 50:
        verdict = "🟡 POSSIBLE INFECTION — Clinical Correlation Required"
        color   = "warning"
        interpretation = (
            "النتيجة حدودية. يُنصح بالتقييم الكلينيكي الكامل قبل البدء بالعلاج. "
            "قد تحتاج فحوصات إضافية أو إعادة المزرعة."
        )
        recommendations = [
            "قيّم المريض كلينيكياً قبل إعطاء المضادات الحيوية.",
            "فكّر في إعادة المزرعة إذا كان الوضع غير واضح.",
            "راجع نتيجة الـ Urinalysis / CRP / CBC إذا لم تكن متاحة.",
        ]
    elif score >= 30:
        verdict = "🟠 LIKELY CONTAMINANT — Repeat Recommended"
        color   = "warning"
        interpretation = (
            "المؤشرات تميل نحو التلوث أو الاستعمار. "
            "يُنصح بإعادة أخذ العينة بتقنية صحيحة قبل البدء بالعلاج."
        )
        recommendations = [
            "أعِد أخذ العينة مع تحسين التقنية.",
            "لا تبدأ العلاج بناءً على هذه النتيجة وحدها.",
            "إذا تكرر العزل، فكّر في مصدر بديل (Hematogenous / Device).",
        ]
    else:
        verdict = "🟢 LIKELY CONTAMINANT / COLONIZER — Do Not Treat"
        color   = "success"
        interpretation = (
            "المؤشرات تدعم التلوث أو الاستعمار بشكل كبير. "
            "العلاج غير مبرر في الغالب. تابع المريض كلينيكياً."
        )
        recommendations = [
            "لا تعطِ مضادات حيوية بناءً على هذه النتيجة.",
            "أعِد تقييم المريض إذا استمرت الأعراض أو تطورت.",
            "التزم بمبادئ Antibiotic Stewardship.",
        ]

    return {
        "score":           score,
        "verdict":         verdict,
        "color":           color,
        "interpretation":  interpretation,
        "recommendations": recommendations,
        "factors_pos":     factors_pos,
        "factors_neg":     factors_neg,
        "abu_detected":    abu_detected,
        "special_flags":   special_flags,
    }

def _parse_cfu(text: str) -> int:
    """استخرج قيمة CFU رقمية من النص"""
    if not text:
        return 0
    # FIXED: clean spaces before checking
    t_clean = text.lower().replace(" ", "").replace("\u2009", "").strip()
    if any(x in t_clean for x in ["≥", ">=", ">10^5", ">100000", "10^5", "≥10", ">=10"]):
        if "10^5" in t_clean or "100000" in t_clean:
            return 100000
        if "10^4" in t_clean or "10000" in t_clean:
            return 10000
    nums = re.findall(r'[\d]+', text.replace(",", ""))
    if not nums:
        return 0
    val = int(nums[-1])
    # إذا كان الرقم صغير جداً (مثل "10" تعني 10^5 أحياناً)
    if val <= 9 and "^" in text:
        exp_match = re.findall(r'\^(\d+)', text)
        if exp_match:
            val = 10 ** int(exp_match[0])
    return val

def _parse_pus(text: str):
    """استخرج أقصى قيمة WBC/HPF من النص، أو None إذا لم يوجد"""
    if not text:
        return None
    nums = re.findall(r'[\d]+', text)
    if not nums:
        return None
    return max(int(n) for n in nums)

def suggest_severity(
    specimen: str, age: int, sex: str,
    is_preg: bool, is_renal: bool, cl_cr: float,
    host_factors: Optional[List] = None,
    symptoms: Optional[List] = None,
) -> Dict[str, Any]:
    """
    Auto-suggest infection severity based on patient risk factors.
    Clinical basis: IDSA UTI 2022 | IDSA CAP 2019 | Sanford 2025 |
                    AHA Infective Endocarditis 2015 | SCCM Sepsis-3 2016.

    Returns:
        suggested: "mild" | "moderate" | "severe"
        reasons:   list of clinical reasons
        override:  True (user can still change it)
    """
    spec_l = specimen.lower()
    hf     = [h.lower() for h in (host_factors or [])]
    syms   = [s.lower() for s in (symptoms or [])]

    reasons_severe   = []
    reasons_moderate = []
    reasons_mild     = []

    # ── Universal red flags → SEVERE ─────────────────────────────────────
    if any(k in " ".join(syms) for k in
           ["septic shock", "hypotension", "icu", "bacteremia",
            "altered consciousness", "confusion", "rigors"]):
        reasons_severe.append("Systemic sepsis signs / shock")

    if "central line" in " ".join(hf) or "immunocompromised" in " ".join(hf):
        reasons_severe.append("Immunocompromised / central line")

    # ── Specimen-specific logic ────────────────────────────────────────────
    if "urine" in spec_l or "uti" in spec_l:
        # IDSA: complicated UTI = male, pregnant, elderly, renal, catheter
        if sex == "Male":
            reasons_moderate.append("Male UTI → always complicated (IDSA 2022)")
        if is_preg:
            reasons_moderate.append("Pregnancy → complicated UTI")
        if age >= 65:
            reasons_moderate.append("Age ≥ 65 → complicated UTI")
        if is_renal and cl_cr < 60:
            reasons_moderate.append(f"Renal impairment (CrCl {cl_cr:.0f}) → complicated")
        if any(k in " ".join(hf) for k in ["catheter", "urologic", "diabetes"]):
            reasons_moderate.append("Host risk factor (DM / catheter / urologic anomaly)")
        if any(k in " ".join(syms) for k in ["fever", "flank pain", "costovertebral"]):
            reasons_moderate.append("Upper UTI symptoms → pyelonephritis")
        if not reasons_moderate and not reasons_severe:
            if sex == "Female" and age < 65 and not is_preg and not is_renal:
                reasons_mild.append("Young healthy female → uncomplicated cystitis (IDSA 2022)")

    elif "sputum" in spec_l or "respiratory" in spec_l or "bal" in spec_l:
        # CURB-65 proxy: Age ≥65, renal, altered mentation
        curb = 0
        if age >= 65:         curb += 1; reasons_moderate.append("Age ≥ 65 (CURB-65)")
        if is_renal:          curb += 1; reasons_moderate.append("Renal impairment (CURB-65)")
        if any(k in " ".join(syms) for k in ["confusion", "altered"]):
            curb += 1; reasons_severe.append("Altered mentation (CURB-65 ≥3)")
        if curb == 0:
            reasons_mild.append("No CURB-65 risk factors → mild CAP")

    elif "blood" in spec_l:
        # Bacteremia is always at least moderate
        reasons_moderate.append("Bloodstream infection → minimum moderate")
        if age >= 65 or is_renal:
            reasons_severe.append("Bacteremia + age ≥65 / renal impairment → severe")

    elif "csf" in spec_l or "meningitis" in spec_l:
        # CNS = always severe
        reasons_severe.append("CNS infection → always severe")

    elif "wound" in spec_l or "pus" in spec_l or "abscess" in spec_l:
        if any(k in " ".join(hf) for k in ["diabetes", "immunocompromised"]):
            reasons_moderate.append("Wound infection + DM/immunocompromised")
        elif not reasons_moderate and not reasons_severe:
            reasons_mild.append("Simple SSTI without systemic features")

    elif "stool" in spec_l or "gi" in spec_l:
        if age >= 65 or is_renal or is_preg:
            reasons_moderate.append("GI infection + high-risk host")
        if any(k in " ".join(syms) for k in ["bloody", "fever", "dehydration"]):
            reasons_moderate.append("Febrile / bloody diarrhea → moderate+")
        else:
            reasons_mild.append("GI infection without systemic features → supportive")

    # ── Final decision ────────────────────────────────────────────────────
    if reasons_severe:
        return {"suggested": "severe",   "reasons": reasons_severe,   "override": True}
    elif reasons_moderate:
        return {"suggested": "moderate", "reasons": reasons_moderate, "override": True}
    else:
        return {"suggested": "mild",     "reasons": reasons_mild or ["No risk factors identified"],
                "override": True}

# ── Empiric-regimen note annotation ─────────────────────────────────────────
# The TREATMENT_DURATION_DB "notes" field may quote guideline first-line agents
# (e.g. "3d TMP-SMX | 5d Nitrofurantoin | 3-7d FQ"). On a culture report those
# drug names MUST be reconciled with the patient's own AST — otherwise a drug
# that is Resistant, or was never tested, appears as if it were recommended.
# This annotator flags each quoted agent with its real susceptibility status.
_REGIMEN_TOKENS = [
    # (token as written in notes, [AST drug name(s) to check])
    ("TMP-SMX",        ["Trimethoprim/Sulfamethoxazole"]),
    ("Nitrofurantoin", ["Nitrofurantoin"]),
    ("Fosfomycin",     ["Fosfomycin"]),
    ("FQ",             ["Ciprofloxacin", "Ofloxacin", "Norfloxacin",
                        "Levofloxacin", "Gatifloxacin", "Moxifloxacin"]),
]


def _sir_lookup(drug: str, sir_map: Dict[str, str]) -> Optional[str]:
    """Return S/I/R for `drug` from sir_map, matching keys tolerantly."""
    if not sir_map:
        return None
    try:
        from abx_guidelines import normalize_abx_key
        target = normalize_abx_key(drug)
        for k, v in sir_map.items():
            if normalize_abx_key(k) == target:
                return ((v or "").strip().upper()[:1]) or None
    except Exception:
        low = {k.lower(): v for k, v in sir_map.items()}
        val = low.get(drug.lower())
        return ((val or "").strip().upper()[:1]) or None
    return None


def _regimen_token_status(drug_names, sir_map) -> str:
    """Aggregate AST status for one token. For a class, S wins, then I, then R,
    else 'NT' (not tested / not on the panel)."""
    seen = [s for s in (_sir_lookup(d, sir_map) for d in drug_names) if s]
    if not seen:
        return "NT"
    if "S" in seen:
        return "S"
    if "I" in seen:
        return "I"
    return "R"


def annotate_regimen_note(note: str, sir_map: Dict[str, str], lang: str = "ar") -> str:
    """Insert an AST-status flag after each guideline agent quoted in `note`.
    Sensitive agents are left unflagged; Resistant / Intermediate / not-tested
    agents are marked so the note can never contradict the antibiogram."""
    if not note or not sir_map:
        return note
    flags = {
        "R":  " ⚠️[R — مقاوم في هذه المزرعة]" if lang == "ar" else " ⚠️[R — resistant here]",
        "I":  " [I]",
        "NT": " [غير مُختبر]" if lang == "ar" else " [not tested]",
        # "S" is intentionally left unflagged.
    }
    out = note
    for token, drugs in _REGIMEN_TOKENS:
        if token not in out:
            continue
        flag = flags.get(_regimen_token_status(drugs, sir_map), "")
        if not flag:
            continue
        out = re.sub(r"(?<![\w-])" + re.escape(token) + r"(?![\w-])",
                     lambda m: m.group(0) + flag, out, count=1)
    return out


def get_treatment_duration(
    specimen: str, organism: str, syndrome: str,
    age: int, sex: str, is_renal: bool,
    phenotypes: List[Dict], severity: str = "moderate",
) -> Dict[str, Any]:
    """Treatment Duration Engine — IDSA AMR 2025 | Sanford Guide 2025"""
    spec = specimen.lower()
    org  = organism.lower()
    synd = (syndrome or "").lower()
    ph   = [p.get("phenotype", "") for p in phenotypes]
    has_mrsa = "MRSA" in ph
    has_mdr  = any(x in ph for x in ["MDR", "XDR", "PDR", "CRE", "CRPA", "CRAB"])

    key = None
    if "urine" in spec:
        if any(k in synd for k in ["pyelonephritis", "upper", "kidney", "pyelo"]):
            # Syndrome explicitly says pyelonephritis
            key = "Pyelonephritis_inpatient" if severity == "severe" else "Pyelonephritis_outpatient"
        elif severity == "severe":
            # Severe UTI without explicit syndrome → treat as pyelonephritis/inpatient
            key = "Pyelonephritis_inpatient"
        elif severity == "moderate" or sex == "Male" or age >= 65 or is_renal or has_mdr:
            # Complicated: male, elderly, renal impaired, MDR, or moderate severity
            key = "UTI_complicated"
        else:
            # Mild + female + young + no complicating factors → uncomplicated
            key = "UTI_uncomplicated_female"
    elif any(s in spec for s in ["sputum", "respiratory", "bal", "tracheal", "bronch"]):
        if any(k in synd for k in ["hap", "vap", "hospital", "ventil"]):
            key = "HAP_VAP"
        elif severity == "mild":   key = "CAP_mild"
        elif severity == "severe": key = "CAP_severe"
        else:                      key = "CAP_moderate"
    elif "blood" in spec:
        if has_mrsa or "mrsa" in org:           key = "Bacteremia_MRSA"
        elif "staphylococcus aureus" in org:     key = "Bacteremia_MSSA"
        else:                                    key = "Bacteremia_GNB"
    elif "csf" in spec:
        # NB: bare "pneumoniae" also matches *Klebsiella* pneumoniae — match the
        # pneumococcus explicitly so GNB meningitis isn't treated as pneumococcal.
        _is_pneumococcus = ("streptococcus pneumoniae" in org
                            or "s. pneumoniae" in org or "pneumococc" in org)
        key = "Meningitis_pneumococcal" if _is_pneumococcus else "Meningitis_GNB"
    elif any(w in spec for w in ["wound", "pus", "swab", "tissue", "abscess"]):
        if any(k in synd for k in ["necrotiz", "fasciitis", "gangrene"]): key = "SSTI_severe"
        elif "osteomyelitis" in synd or "bone" in synd:                    key = "Osteomyelitis"
        elif severity == "mild":   key = "SSTI_mild"
        elif severity == "severe": key = "SSTI_severe"
        else:                      key = "SSTI_moderate"
    elif "stool" in spec or "fecal" in spec or "rectal" in spec:
        # GI infections: most need NO antibiotic; treat only severe/immunocompromised
        key = "GI_severe" if severity == "severe" else "GI_mild"
    elif any(w in spec for w in ["abdomen", "periton"]):
        key = "Intraabdominal_severe" if severity == "severe" else "Intraabdominal_mild"

    if not key:
        return {"label": "Not matched", "min_days": 7, "max_days": 14, "standard_days": 10,
                "iv_days": 3, "po_days": 7, "notes": "Individualize based on clinical response.",
                "follow_up_culture": True, "ref": "Clinical judgment"}

    _d_raw = TREATMENT_DURATION_DB.get(key)
    if not _d_raw:
        # Key not present in the duration DB → fall back safely instead of KeyError.
        return {"label": "Not matched", "min_days": 7, "max_days": 14, "standard_days": 10,
                "iv_days": 3, "po_days": 7, "notes": "Individualize based on clinical response.",
                "follow_up_culture": True, "ref": "Clinical judgment"}
    d = _d_raw.copy()
    mn, mx = d["days"]
    notes_extra = []
    if has_mdr:
        mx = max(mx, 14)
        notes_extra.append("MDR organism: extended duration may be required.")
    if is_renal: notes_extra.append("Renal impairment: monitor drug levels closely.")
    if age > 65:  notes_extra.append("Elderly: monitor for toxicity; shorter courses if responding.")
    if notes_extra:
        _base = d.get("notes") or ""
        d["notes"] = (_base + " | " if _base else "") + " | ".join(notes_extra)
    d.update({"min_days": mn, "max_days": mx, "standard_days": d["standard"]})
    return d

def evaluate_iv_po_switch(
    drug_name: str, syndrome: str,
    clinical_improving: bool, tolerating_oral: bool,
    bacteremia_resolved: bool, days_on_iv: int,
) -> Dict[str, Any]:
    """OPAT IV→PO Evaluation — IDSA 2019 | BNF 2025"""
    bioavail, matched = 0, ""
    for k, v in HIGH_BIOAVAILABILITY.items():
        if k.lower() == drug_name.lower() or drug_name.lower() in k.lower():
            bioavail, matched = v, k
            break

    blockers, supporters = [], []
    if not clinical_improving: blockers.append("No clinical improvement in 48-72h")
    else:                      supporters.append("Clinical improvement documented")
    if not tolerating_oral:    blockers.append("Not tolerating oral intake")
    else:                      supporters.append("Tolerating oral medications")
    if not bacteremia_resolved: blockers.append("Active bacteremia / endovascular infection")
    else:                       supporters.append("No active bloodstream infection")

    if bioavail >= 80:     supporters.append(f"{matched}: Oral bioavailability {bioavail}% — excellent for switch")
    elif bioavail >= 50:   blockers.append(f"{matched}: Moderate bioavailability ({bioavail}%) — consider IV continuation")
    elif bioavail > 0:     blockers.append(f"{matched}: Low bioavailability ({bioavail}%) — IV preferred")
    else:                  blockers.append(f"{drug_name}: No established oral equivalent")

    synd_lower = (syndrome or "").lower()
    if any(s in synd_lower for s in ALWAYS_IV_SYNDROMES):
        blockers.append(f"{syndrome} — requires prolonged IV therapy")
    if days_on_iv < 2:    blockers.append(f"Less than 48h on IV ({days_on_iv}d) — complete initial IV course")
    else:                  supporters.append(f"{days_on_iv} days on IV — appropriate reassessment window")

    can_switch = len(blockers) == 0
    return {
        "can_switch": can_switch, "bioavail": bioavail, "matched_drug": matched,
        "blockers": blockers, "supporters": supporters,
        "verdict": (f"Switch acceptable. Oral bioavailability: {bioavail}%." if can_switch
                    else "IV→PO switch NOT recommended at this time."),
        "ref": "IDSA OPAT 2019 | BNF 2025 | BSAC 2023",
    }

def get_hepatic_recommendations(allowed_drugs: List[Dict], child_pugh: str) -> List[Dict[str, str]]:
    """Hepatic dosing recommendations — BNF 2025 | Lexicomp 2025"""
    results = []
    for drug in allowed_drugs:
        name = drug.get("name", "")
        if name in HEPATIC_DOSING:
            level, rec = HEPATIC_DOSING[name].get(child_pugh, ("Normal", "No adjustment"))
            note = HEPATIC_DOSING[name].get("note", "")
            results.append({
                "name": name, "level": level,
                "recommendation": rec, "note": note,
                "requires_action": level not in ("Normal", "Renal-based", "AUC/MIC monitoring"),
            })
    results.sort(key=lambda x: (0 if x["requires_action"] else 1, x["name"]))
    return results

def get_combination_therapy(phenotypes: List[Dict]) -> List[Dict]:
    """Combination therapy suggestions based on detected phenotypes — IDSA AMR 2025"""
    results  = []
    ph_names = [p.get("phenotype", "") for p in phenotypes]
    for ph in ["CRAB", "CRPA", "CRE", "MRSA", "VRE", "ESBL", "MDR"]:
        if ph in ph_names and ph in COMBINATION_THERAPY:
            results.append({"phenotype": ph, "data": COMBINATION_THERAPY[ph]})
    return results

def evaluate_deescalation(
    allowed: List[Dict], phenotypes: List[Dict],
    hours_on_treatment: int, clinical_improving: bool,
) -> Dict[str, Any]:
    """De-escalation advisor — WHO AWaRe 2025 | IDSA Stewardship 2025"""
    ph_names    = [p.get("phenotype", "") for p in phenotypes]
    is_reserve  = any(p in ph_names for p in ["MDR", "XDR", "PDR", "CRE", "CRPA", "CRAB"])
    access_drugs = [d for d in allowed if d.get("aware") == "Access"]
    watch_drugs  = [d for d in allowed if d.get("aware") == "Watch"]
    recs, can_de = [], False

    if hours_on_treatment < 48:
        recs.append(f"INFO: Still in early treatment phase ({hours_on_treatment}h). Complete 48-72h before reassessment.")
    elif not clinical_improving:
        recs.extend(["WARNING: No clinical improvement at 48-72h:",
                     "  - Repeat culture to confirm sensitivity",
                     "  - Assess source control (drainage, catheter removal)",
                     "  - Consider TDM (vancomycin AUC, aminoglycosides)",
                     "  - Consult Infectious Disease"])
    else:
        can_de = True
        recs.append("RECOMMENDED: Clinical improvement documented — consider spectrum narrowing:")
        if access_drugs:
            names = [d["name"] for d in access_drugs[:4]]
            recs.append(f"  Access-group options: {' | '.join(names)}")
        elif watch_drugs:
            names = [d["name"] for d in watch_drugs[:3]]
            recs.append(f"  Watch-group options: {' | '.join(names)}")
        if is_reserve:
            recs.append("  CAUTION: MDR/XDR organism — ID consult before de-escalating Reserve agents")
            can_de = False

    recs.append("PRINCIPLE: Narrowest effective spectrum + shortest safe duration (WHO AWaRe 2025)")
    return {
        "can_deescalate": can_de,
        "access_options": [d["name"] for d in access_drugs],
        "watch_options":  [d["name"] for d in watch_drugs],
        "recommendations": recs,
        "is_reserve_organism": is_reserve,
        "ref": "WHO AWaRe 2025 | IDSA Stewardship 2025",
    }

def detect_resistance_phenotypes(
    organism: str, sir_map: Dict[str, str]
) -> List[Dict[str, Any]]:
    """
    يكتشف الـ phenotypes المقاومة من نمط S/I/R.
    يعيد قائمة بكل الـ phenotypes المكتشفة.
    """
    if not sir_map:
        return []
    detected = []
    org_lower = organism.lower()

    for ph_name, rule in PHENOTYPE_RULES.items():
        # هل الكائن مرشح لهذا الـ phenotype؟
        if not any(o.lower() in org_lower or org_lower in o.lower()
                   for o in rule["organisms"]):
            continue

        markers   = rule.get("markers", [])
        req_any   = rule.get("require_any", len(markers))  # default: كل الـ markers

        # عدد الـ markers المطابقة
        matched = sum(1 for drug, expected in markers
                      if sir_map.get(drug) == expected)

        if matched >= req_any and matched > 0:
            detected.append({
                "phenotype": ph_name,
                "icon":      rule["icon"],
                "label":     rule["label"],
                "detail":    rule["detail"],
                "action":    rule["action"],
                "isolation": rule.get("isolation", False),
                "matched_markers": [
                    drug for drug, exp in markers if sir_map.get(drug) == exp
                ],
            })

    # MRSA fallback: لو S. aureus + Vancomycin S + Linezolid S → اشتباه MRSA
    if "staphylococcus aureus" in org_lower and "MRSA" not in [d["phenotype"] for d in detected]:
        vanco_s   = sir_map.get("Vancomycin") == "S"
        linezo_s  = sir_map.get("Linezolid")  == "S"
        beta_r    = any(sir_map.get(d) == "R" for d in
                        ["Amoxicillin + Clavulanic acid","Cephalexin","Cefuroxime"])
        if beta_r and (vanco_s or linezo_s):
            detected.append({
                "phenotype": "Possible MRSA",
                "icon":      "⚠️",
                "label":     "Possible MRSA — تأكيد مطلوب",
                "detail":    "نمط مقاومة beta-lactam مع حساسية للـ Vancomycin/Linezolid يشير لـ MRSA.",
                "action":    "أجرِ Cefoxitin disk diffusion أو PCR (mecA) للتأكيد.",
                "isolation": False,
                "matched_markers": [],
            })

    return detected

def run_ast_qc(organism: str, sir_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """
    يفحص نتائج S/I/R ويعيد قائمة بالتناقضات المكتشفة.
    """
    if not sir_map:
        return []
    issues = []
    org_lower = organism.lower()
    for rule in AST_QC_RULES:
        # تحقق من الكائن (لو فاضية → ينطبق على الكل)
        if rule["organisms"]:
            if not any(o.lower() in org_lower or org_lower in o.lower()
                       for o in rule["organisms"]):
                continue
        try:
            if rule["condition"](sir_map):
                _msg = rule["message"]
                # استبدال {r_drug} أولاً (بـ str.replace وليس format) بالدواء المقاوم
                # الفعلي — قبل أي format حتى لا يبحث format عن مفتاح r_drug.
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
                    "fix":      rule["fix"],
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
    n_tested = len(sir_map) if sir_map else 0
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

def rank_sensitive_antibiotics(
    allowed:      List[Dict],
    culture_type: str,
    organism:     str,
    sir_map:      Dict[str, str],
    phenotypes:   List[Dict],
) -> List[Dict]:
    """
    يرتب الأدوية المسموحة بترتيب هرمي صارم (lexicographic) — كل معيار يكسر
    التعادل في المعيار الأهم منه فقط، فلا يتغلب معيار أدنى على أعلى:

      1. نتيجة المزرعة   : S قبل I  (بوابة صارمة — لا يتخطى I دواءً S أبداً)
      2. ملاءمة العينة   : دواء له specimen_note للعينة الحالية أولاً
      3. WHO AWaRe       : Access > Watch > Reserve
      4. طريق الإعطاء     : Oral قبل IV/IM
      5. Priority        : أولوية الـ guidelines (أقل = أفضل)
      6. الاسم           : لضمان ترتيب ثابت (deterministic)

    ملاحظة تصميمية: جمع النقاط كان يسمح لدواء Intermediate ذي AWaRe/route جيد
    أن يتفوق على دواء Sensitive — وهذا خطأ إكلينيكي (الفعالية المخبرية تسبق كل
    شيء). يُحتفظ بـ _score كقيمة عرض تقريبية فقط، لا للترتيب.
    """
    ph_names = [p.get("phenotype", "") for p in phenotypes]
    _sir_rank   = {"S": 0, "I": 1}
    _aware_rank = {"Access": 0, "Watch": 1, "Reserve": 2}

    def sort_key(item):
        name = item.get("name", "")
        sir  = sir_map.get(name)
        k_sir = _sir_rank.get(sir, 2)                       # S=0, I=1, unknown=2
        k_spec = 0 if (item.get("specimen_notes") or {}).get(culture_type) else 1
        aware = item.get("aware")
        k_aware = _aware_rank.get(aware, 3)
        if any(ph in ph_names for ph in ["CRE", "CRAB", "CRPA"]):
            cls = item.get("class", "").lower()
            if "cephalosporin" in cls and sir != "S":
                k_aware += 5
        k_route = 0 if item.get("high_po") else 1
        k_priority = item.get("priority", 99)
        return (k_sir, k_spec, k_aware, k_route, k_priority, name)

    def _display_score(item):
        name = item.get("name", "")
        sir  = sir_map.get(name)
        s = 0
        if sir == "S": s += 4
        elif sir == "I": s += 1
        s += RANKING_WEIGHTS["aware_score"].get(item.get("aware"), 0)
        s += RANKING_WEIGHTS["route_score"]["oral" if item.get("high_po") else "iv"]
        if (item.get("specimen_notes") or {}).get(culture_type):
            s += RANKING_WEIGHTS["specimen_match"]
        s += RANKING_WEIGHTS["priority_bonus"](item.get("priority", 5))
        return s

    scored = [
        {**item, "_score": _display_score(item), "_sir": (sir_map.get(item.get("name", "")) or "—")}
        for item in allowed
    ]
    return sorted(scored, key=sort_key)

def get_infection_syndrome(
    specimen:  str,
    organism:  str,
    age:       int,
    is_preg:   bool,
    is_cath:   bool = False,
) -> Optional[Dict[str, Any]]:
    """
    يعيد السياق السريري للعدوى — يدعم مطابقة مرنة لأسماء العينات.
    """
    # Try exact match first
    syndrome_data = INFECTION_SYNDROMES.get((specimen, None))
    # Fuzzy fallback: match substring
    if not syndrome_data:
        spec_l = specimen.lower()
        for (key_spec, _), data in INFECTION_SYNDROMES.items():
            kl = key_spec.lower()
            if kl in spec_l or spec_l in kl:
                syndrome_data = data
                break
    # Keyword fallback (FIXED: use OrderedDict to ensure longer keys matched first)
    if not syndrome_data:
        spec_l = specimen.lower()
        fallback_map = OrderedDict([
            ("blood culture", "Blood"),
            ("stool culture", "Stool"),
            ("blood", "Blood"),
            ("stool", "Stool"),
            ("fecal", "Stool"),
            ("rectal", "Stool"),
            ("sputum", "Sputum"),
            ("respiratory", "Sputum"),
            ("bal", "Sputum"),
            ("csf", "CSF"),
            ("cerebrospinal", "CSF"),
            ("wound", "Wound Swab"),
            ("swab", "Wound Swab"),
            ("pus", "Pus"),
            ("abscess", "Pus"),
            ("tissue", "Wound Swab"),
        ])
        for keyword, target_key in fallback_map.items():
            if keyword in spec_l and target_key:
                syndrome_data = INFECTION_SYNDROMES.get((target_key, None))
                if syndrome_data:
                    break

    if not syndrome_data:
        return None

    sub_type = syndrome_data["classify"](age, is_preg, is_cath)
    duration  = syndrome_data["duration"].get(sub_type, "حسب الاستجابة السريرية")

    return {
        "syndrome":       syndrome_data["syndrome"],
        "sub_type":       sub_type,
        "first_choice":   syndrome_data["first_choice"],
        "duration":       duration,
        "escalation":     syndrome_data["escalation"],
        "threshold":      syndrome_data["culture_threshold"],
    }
