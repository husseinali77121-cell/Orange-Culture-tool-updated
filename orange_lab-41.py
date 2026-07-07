# © 2025 Dr / Hussein Ali — Orange Lab, 6 October City, Egypt
# Microbiology CDSS — All Rights Reserved
# Unauthorized copying or distribution is prohibited.

import io
import json
import re
import time
import hashlib
import logging
from datetime import datetime, date
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple
from collections import OrderedDict

import streamlit as st

# =========================================================
# Logging — replaces silent exception swallowing.
# In Streamlit Cloud these go to the app logs (Manage app → Logs).
# =========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orange_lab")

try:
    import cv2
    import numpy as np
    import pytesseract
    OCR_AVAILABLE = True
    OCR_IMPORT_ERROR = ""
except Exception as exc:
    cv2 = None
    np = None
    pytesseract = None
    OCR_AVAILABLE = False
    OCR_IMPORT_ERROR = str(exc)

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


from abx_guidelines import (
    ABX_ALIAS_INDEX,
    ABX_GUIDELINES,
    DEFAULT_SPECIMENS,
    normalize_abx_key,
    validate_abx_guidelines,
)
from organism_profile import ORGANISM_PROFILE, validate_organism_profile
from specimen_organism_map import (
    SPECIMEN_ORDER,
    get_organisms_for_specimen,
    validate_specimen_organism_map,
)

# ── Split modules (extracted from monolith) ──────────────────────
from clinical_data import (
    AWARE_COLORS,
    COMMERCIAL_NAMES,
    COMMON_MEDS,
    MDR_INFO,
)
from clinical_engines import (
    analyze_antibiotics,
    assess_pathogenicity,
    calc_creatinine_clearance,
    classify_mdr,
    compute_qa_confidence,
    detect_resistance_phenotypes,
    evaluate_deescalation,
    evaluate_iv_po_switch,
    fuzzy_match,
    get_combination_therapy,
    get_hepatic_recommendations,
    get_infection_syndrome,
    get_renal_severity,
    get_route_label,
    get_treatment_duration,
    predict_esbl,
    rank_sensitive_antibiotics,
    run_ast_qc,
    safe_int,
    suggest_severity,
    uniq_keep_order,
)
from reports import (
    generate_decision_tree_image,
    generate_pdf_html_report,
    generate_qa_report_pdf,
    generate_report,
)
from isolate_registry import IsolateRegistry
from antibiogram import render_antibiogram_page, render_registry_page


# =========================================================
# ملاحظة: Ampicillin, Amoxicillin, Tetracycline, Cephradine
# منقولة بالكامل إلى abx_guidelines.py
# لا توجد بيانات مضادات حيوية في هذا الملف — كل البيانات في abx_guidelines.py
# =========================================================

# =========================================================
# إعداد الصفحة
# =========================================================
st.set_page_config(
    page_title="Microbiology CDSS",
    layout="wide",
    page_icon="🔬"
)

st.markdown("""
<style>
    .stActionButton {display: none !important;}
    #MainMenu {visibility: hidden !important;}
    footer {visibility: hidden !important;}
    header[data-testid="stHeader"] {display: none !important;}
    .app-card {
        padding: 1rem 1.2rem;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        background: rgba(255,255,255,0.02);
        margin-bottom: 1rem;
    }
    .muted-text { color: #9aa0a6; font-size: 0.92rem; }
    .orange-badge {
        display:inline-block; background:#ff8c00; color:white;
        padding:0.25rem 0.7rem; border-radius:999px;
        font-size:0.8rem; font-weight:600;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# الثوابت
# =========================================================
SESSION_TIMEOUT = 30 * 60
BACTERIA_TYPES  = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES  = list(SPECIMEN_ORDER or DEFAULT_SPECIMENS)


# ── Commercial Names Loader ───────────────────────────────────────────







# =========================================================
# تحميل المشتركين
# =========================================================
# ── Password hashing (see auth_utils.py — pure stdlib, unit-tested) ─────────
from auth_utils import hash_password, verify_password


def load_subscribers() -> Dict[str, Dict[str, Optional[str]]]:
    """
    Normalizes subscribers into {email: {"expiry": "YYYY-MM-DD", "password": <hash|None>}}.

    Supported secret formats (backward compatible):
      • Legacy:  {"a@b.com": "2026-12-31"}                       → no password (email-only)
      • Secure:  {"a@b.com": {"expiry": "2026-12-31",
                              "password": "pbkdf2_sha256$..."}}  → password required
    """
    try:
        raw  = st.secrets.get("subscribers_json") or st.secrets.get("subscribers", "{}")
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except Exception as exc:
        logger.exception("load_subscribers: could not parse secrets: %s", exc)
        return {}

    out: Dict[str, Dict[str, Optional[str]]] = {}
    for k, v in data.items():
        email = str(k).strip().lower()
        if isinstance(v, dict):
            out[email] = {
                "expiry":   str(v.get("expiry", "")).strip(),
                "password": (str(v["password"]).strip() if v.get("password") else None),
            }
        else:  # legacy string = expiry only
            out[email] = {"expiry": str(v).strip(), "password": None}
    return out

SUBSCRIBERS = load_subscribers()

# =========================================================
# Session State
# =========================================================
def init_session_state() -> None:
    defaults = {
        "authenticated":      False,
        "email":              "",
        "days_left":          None,
        "last_activity":      None,
        "logout_reason":      "",
        "ocr_data":           None,
        "last_file_hash":     "",
        "sir_map_edited":     {},
        "patient_name_ocr":   "",
        "patient_name_final": "",
        "lab_id":             "",
        "mobile":             "",
        "branch":             "Lasitee Mall",
        # ─── حقول المزرعة الجديدة ─────────────────────────────────────────
        "colony_count":       "≥ 10^5 CFU/mL",
        "date_in":            date.today(),
        "pus_cells_text":     "",
        "rbcs_text":          "",
        # اسم المعمل — قابل للتعديل من الـ sidebar
        "lab_name":           "Orange Lab",
        "lab_city":           "Giza - 6 October",
        # ─── Commercial Names ─────────────────────────────────────────────
        "show_commercial_names": False,
        # ─── Pathogenicity Assessment ─────────────────────────────────────
        "patho_culture_purity":   "Pure growth",
        "patho_symptoms":         [],
        "patho_urinalysis":       "مش معروف / مش مذكور",
        "patho_gram_stain":       "مش متعملة",
        "patho_host_factors":     [],
        "patho_sputum_pus":       "",
        "patho_sputum_epi":       "",
        "patho_sirs":             [],
        "patho_blood_source":     "",
        "patho_wound_type":       "",
        "patho_result":           None,
        # ─── Wizard: three-step flow (Patient → AST → Results) ─────────────
        "wizard_step":             1,      # 1 = Patient/Culture, 2 = AST entry
        "show_results":            False,  # True = viewing results (step 3)
        # ─── Clinical Engines v4 ──────────────────────────────────────────
        "severity_level":          "moderate",  # overwritten by auto-suggest
        "last_patho_specimen":     "",   # tracks specimen that generated patho_result
        "child_pugh_class":        "A",
        "days_on_iv":              3,
        "clinical_improving_48h":  True,
        "tolerating_oral":         True,
        "bacteremia_resolved":     True,
        "hours_on_treatment":      72,
        "de_clinical_improving":   True,
        # ─── PDF Report Options ───────────────────────────────────────────
        "pdf_include_combo":       True,
        "pdf_include_duration":    True,
        "pdf_include_patho":       True,
        # ─── New image/report fields ──────────────────────────────────────
        "referring_physician":     "",
        "culture_condition":       "Aerobic",
        "microbiologist":          "",
        # ─── Cached Computations (prevent regeneration on every widget) ────
        "_img_bytes":              None,
        "_img_hash":               "",
        "_img_error":              False,   # FIXED: added to retry on failure
        "_rpt_text":               "",
        "_rpt_hash":               "",
        "_pdf_bytes":              None,
        "_pdf_hash":               "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# =========================================================
# أدوات مساعدة
# =========================================================

def make_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()






def ensure_ocr_dependencies() -> None:
    if OCR_AVAILABLE:
        return
    st.error(
        "تعذر تحميل مكتبات OCR المطلوبة لتشغيل قراءة الصور.\n\n"
        f"Runtime import error: {OCR_IMPORT_ERROR}"
    )
    st.stop()

@st.cache_data(show_spinner=False)
def get_startup_validation_issues() -> List[str]:
    issues: List[str] = []
    issues.extend(validate_abx_guidelines(
        known_organisms=list(ORGANISM_PROFILE.keys()),
        known_specimens=SPECIMEN_TYPES
    ))
    issues.extend(validate_organism_profile(known_antibiotics=list(ABX_GUIDELINES.keys())))
    issues.extend(validate_specimen_organism_map(known_organisms=list(ORGANISM_PROFILE.keys())))
    deduped: List[str] = []
    seen:    set        = set()
    for issue in issues:
        if issue not in seen:
            deduped.append(issue)
            seen.add(issue)
    return deduped

def normalize_ocr_text(text: str) -> str:
    cleaned = text or ""
    for old, new in {"\u2013": "-", "\u2014": "-", "\u00a0": " ", "|": " "}.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def best_default_index(options: List[str], preferred: Optional[str]) -> int:
    if preferred and preferred in options:
        return options.index(preferred)
    return 0

# =========================================================
# اكتشاف اسم المريض من OCR
# =========================================================
def clean_patient_name(name: str) -> str:
    if not name:
        return ""
    name = normalize_ocr_text(name)
    blacklist = [
        "name", "patient", "patient name", "specimen", "organism", "age", "sex",
        "male", "female", "urine", "culture", "report", "lab", "result",
        "اسم", "المريض", "اسم المريض", "العمر", "النوع", "الجنس",
        "العينة", "المزرعة", "نتيجة", "تقرير", "معمل", "مختبر"
    ]
    low = name.lower()
    for token in blacklist:
        low = low.replace(token.lower(), " ")
    name = low
    name = re.sub(r"[^A-Za-z\u0600-\u06FF\s]", " ", name)
    name = re.sub(r"\s{2,}", " ", name).strip()
    if len(name) < 3:
        return ""
    return name.title() if re.search(r"[A-Za-z]", name) else name

def get_subscription_days_left(email: str) -> Optional[int]:
    email = (email or "").strip().lower()
    if email not in SUBSCRIBERS:
        return None
    expiry_str = SUBSCRIBERS[email].get("expiry", "")
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        today       = datetime.now().date()
        return (expiry_date - today).days
    except Exception as exc:
        logger.warning("Bad expiry for %s (%r): %s", email, expiry_str, exc)
        return None

def show_login_page():
    if st.session_state.get("logout_reason"):
        st.warning(st.session_state.pop("logout_reason"))
    st.markdown("""
    <div style='text-align:center; padding: 3rem 0 1rem 0'>
        <span style='font-size:3rem'>🍊</span>
        <h2 style='margin:0.3rem 0 0.1rem 0'>Microbiology CDSS</h2>
        <p style='color:gray; margin:0'>AI-Assisted Antibiotic Decision Support — Egyptian Market</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("#### 🔐 تسجيل الدخول")
        email    = st.text_input("📧 البريد الإلكتروني", placeholder="example@hospital.com",
                                 label_visibility="collapsed")
        password = st.text_input("🔑 كلمة المرور", type="password",
                                 placeholder="كلمة المرور (اتركها فارغة للحسابات القديمة)")
        login_btn = st.button("دخول", use_container_width=True, type="primary")
        if login_btn:
            return (email.strip().lower(), password)
        st.markdown("---")
        st.markdown("""
        <div style='text-align:center; font-size:0.9rem; color:gray'>
        للحصول على نسخة تجريبية أو اشتراك:<br>
        📞 01016872801 &nbsp;|&nbsp; ✉️ Hussein.ali77121@gmail.com<br><br>
        🔹 تجريبي مجاني: <b>15 يوم</b><br>
        🔹 شهري: <b>200 جنيه</b><br>
        🔹 سنوي: <b>2000 جنيه</b> <span style='color:green'>(توفير 400 ج)</span>
        </div>
        """, unsafe_allow_html=True)
    return None

def check_subscription(email: str, password: str = "") -> bool:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        st.warning("⚠️ أدخل بريدًا إلكترونيًا صحيحًا")
        return False
    if email not in SUBSCRIBERS:
        st.error("❌ هذا البريد غير مسجل في النظام")
        st.info(
            "**للحصول على نسخة تجريبية مجانية (15 يوم) أو اشتراك:**\n\n"
            "📞 01016872801\n\n✉️ Hussein.ali77121@gmail.com\n\n---\n"
            "🔹 تجريبي: **مجاناً - 15 يوم**\n"
            "🔹 شهري: **200 جنيه**\n"
            "🔹 سنوي: **2000 جنيه** *(توفير 400 ج)*"
        )
        return False

    # ── Password check (only enforced if a hash is configured for this user) ──
    stored_hash = SUBSCRIBERS[email].get("password")
    if stored_hash:
        if not password or not verify_password(password, stored_hash):
            st.error("❌ كلمة المرور غير صحيحة")
            logger.info("Failed password attempt for %s", email)
            return False
    else:
        # Legacy account with no password set — allowed, but nudge to secure it.
        st.warning("⚠️ هذا الحساب بدون كلمة مرور — يُفضّل تفعيلها لحماية الاشتراك.")

    days_left = get_subscription_days_left(email)
    if days_left is None:
        st.error("خطأ في بيانات الاشتراك، تواصل مع الدعم")
        return False
    st.session_state.email     = email
    st.session_state.days_left = days_left
    if days_left < 0:
        st.error(f"⏳ انتهى اشتراكك منذ {abs(days_left)} يوم")
        st.info("📞 للتجديد: 01016872801 | ✉️ Hussein.ali77121@gmail.com")
        return False
    if days_left <= 3:
        st.warning(f"⚠️ اشتراكك ينتهي خلال **{days_left} يوم فقط**")
    elif days_left <= 7:
        st.info(f"ℹ️ متبقي **{days_left} أيام** على انتهاء الاشتراك")
    else:
        st.success(f"✅ أهلاً بك! الاشتراك ساري — متبقي {days_left} يومًا")
    return True

def logout(reason: str = "تم تسجيل الخروج.") -> None:
    st.session_state.clear()
    st.session_state["logout_reason"] = reason
    st.rerun()  # FIXED: removed experimental_rerun fallback

def handle_session_timeout() -> None:
    last_activity = st.session_state.get("last_activity")
    if last_activity:
        elapsed = time.time() - last_activity
        if elapsed > SESSION_TIMEOUT:
            logout("انتهت صلاحية الجلسة بسبب عدم النشاط. الرجاء تسجيل الدخول مرة أخرى.")
    st.session_state.last_activity = time.time()

def render_top_bar() -> None:
    left, right = st.columns([6, 1])
    with left:
        days = get_subscription_days_left(st.session_state.get("email", ""))
        st.session_state.days_left = days
        if days is not None:
            if days <= 3:
                st.warning(
                    f"⚠️ اشتراك **{st.session_state.email}** سينتهي خلال **{days} يوم(أيام)** — يُرجى التجديد قريبًا."
                )
            else:
                st.info(f"✅ اشتراك **{st.session_state.email}** سارٍ — متبقي **{days}** يومًا.")
    with right:
        if st.button("تسجيل خروج", use_container_width=True):
            logout("تم تسجيل الخروج بنجاح.")

# =========================================================
# OCR
# =========================================================
def preprocess_image(file_bytes: bytes) -> Tuple[Any, Any]:
    ensure_ocr_dependencies()
    arr  = np.frombuffer(file_bytes, np.uint8)
    img  = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("تعذر قراءة الصورة. تأكد أن الملف صورة سليمة.")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11,
    )
    kernel = np.ones((1, 1), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    return img, thresh

def run_ocr(thresh: Any) -> str:
    ensure_ocr_dependencies()
    configs = ["--psm 6", "--psm 11", "--psm 4"]
    outputs = []
    for cfg in configs:
        for lang in ["ara+eng", "eng"]:
            try:
                txt = pytesseract.image_to_string(thresh, lang=lang, config=cfg)
                txt = normalize_ocr_text(txt)
                if txt:
                    outputs.append(txt)
            except Exception as exc:
                logger.debug("OCR attempt failed (lang=%s cfg=%s): %s", lang, cfg, exc)
                continue
    if not outputs:
        raise RuntimeError("OCR failed: no text extracted")
    return max(outputs, key=lambda x: len(re.sub(r"\s+", "", x)))

def detect_age(text: str) -> Optional[int]:
    for pattern in [r"(\d+)\s*[Yy]ears?", r"Age[:\s]+(\d+)", r"(\d+)\s*[Yy]\b", r"العمر[:\s]+(\d+)"]:
        match = re.search(pattern, text)
        if match:
            value = safe_int(match.group(1), -1)
            if 0 <= value <= 120:
                return value
    return None

def detect_sex(text_lower: str) -> Optional[str]:
    """Robust sex detection — regex with word boundaries, Female checked first.
    Handles: 'sex: male/female', 'sex: m/f', 'sex=male', 'gender: ...', Arabic."""
    # Female first (avoids 'male' substring inside 'female')
    if (re.search(r'(?:sex|gender)\s*[:=]?\s*(?:female|f\b)', text_lower)
            or re.search(r'\bfemale\b', text_lower)
            or "أنثى" in text_lower or "انثى" in text_lower):
        return "Female"
    # Male: word boundary on 'male' so it won't fire on 'female'
    if (re.search(r'(?:sex|gender)\s*[:=]?\s*(?:male|m\b)', text_lower)
            or re.search(r'\bmale\b', text_lower)
            or "ذكر" in text_lower):
        return "Male"
    return None

def detect_specimen(text_lower: str) -> Optional[str]:
    for specimen in SPECIMEN_TYPES:
        if specimen.lower() in text_lower:
            return specimen
    return None

def detect_organism(text_lower: str) -> Optional[str]:
    counts: Dict[str, int] = {}
    for organism in BACTERIA_TYPES:
        c = text_lower.count(organism.lower())
        if c > 0:
            counts[organism] = c
    return max(counts, key=counts.get) if counts else None

def classify_sir_from_line(line: str) -> Optional[str]:
    ll   = line.lower().strip()
    tail = re.search(r"\b([sir])\b\s*$", ll)
    if tail:
        return tail.group(1).upper()
    if re.search(r"\b(sensitive|susceptible|sens)\b", ll):
        return "S"
    if re.search(r"\b(resistant|resist)\b", ll):
        return "R"
    if re.search(r"\b(intermediate|inter)\b", ll):
        return "I"
    return None

def match_antibiotic_from_text(snippet: str) -> Optional[str]:
    snippet_norm = normalize_abx_key(snippet)
    if not snippet_norm:
        return None
    alias_items = sorted(ABX_ALIAS_INDEX.items(), key=lambda item: len(item[0]), reverse=True)
    for alias_norm, abx_name in alias_items:
        if alias_norm and alias_norm in snippet_norm:
            return abx_name
    best_match = None
    best_score = 0.0
    for abx_name, info in ABX_GUIDELINES.items():
        for variant in [abx_name, *info.get("aliases", [])]:
            score = fuzzy_match(variant, snippet)
            if score > best_score:
                best_score = score
                best_match = abx_name
    return best_match if best_score >= 82 else None

def extract_detected_drugs(full_text: str) -> List[str]:
    """
    Scans OCR text for ANY antibiotic name — regardless of S/I/R presence.
    Uses multiple strategies: per-line, per-word, substring matching.
    """
    detected: set = set()
    text_lower = full_text.lower()
    lines = full_text.splitlines()

    # Strategy 1: per-line match (original)
    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue
        matched = match_antibiotic_from_text(line)
        if matched:
            detected.add(matched)

    # Strategy 2: direct substring scan — check every known alias in full text
    # Sorted longest-first to avoid partial matches
    alias_items = sorted(ABX_ALIAS_INDEX.items(), key=lambda x: len(x[0]), reverse=True)
    for alias_norm, abx_name in alias_items:
        if len(alias_norm) >= 4 and alias_norm in text_lower:
            detected.add(abx_name)

    # Strategy 3: check ABX_GUIDELINES keys directly
    for abx_name in ABX_GUIDELINES:
        if len(abx_name) >= 5 and abx_name.lower() in text_lower:
            detected.add(abx_name)
        # Also check aliases from the drug's own aliases list
        for alias in ABX_GUIDELINES[abx_name].get("aliases", []):
            if len(alias) >= 4 and alias.lower() in text_lower:
                detected.add(abx_name)

    return sorted(detected)

@st.cache_data(show_spinner=False)
def detect_pus_cells(text: str) -> str:
    """
    Extract Pus cells / WBCs from OCR text.
    Handles: 6-8, 10-15, >10, Over 100, >100/HPF, TNTC, كثيرة
    """
    # FIXED: removed internal import re and use global re
    text_l = text.lower()

    # ── Text qualifiers (check first) ────────────────────────────────────────
    if re.search(r"tntc|too\s+numerous|innumerable|uncountable", text_l):
        return "TNTC"
    m_over = re.search(r"over\s*(\d+)", text_l)
    if m_over:
        return f"Over {m_over.group(1)}"
    m_gt = re.search(r">\s*(\d+)", text_l)
    if m_gt:
        return f">{m_gt.group(1)}"
    if re.search(r"\+{3,}|كثير", text_l):
        return ">100"

    # ── Numeric patterns ─────────────────────────────────────────────────────
    patterns = [
        r"pus\s*cells?\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
        r"wbcs?\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
        r"(\d+\s*[-–]\s*\d+)\s*/\s*hpf",
        r"(\d+)\s*/\s*hpf",
    ]
    for pat in patterns:
        m = re.search(pat, text_l, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""

def detect_rbcs(text: str) -> str:
    """استخرج قيمة RBCs من نص OCR."""
    patterns = [
        r"rbcs?\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
        r"red\s*blood\s*cells?\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
        r"كريات\s*حمراء\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
        r"erythrocytes?\s*[:\-]?\s*(\d+\s*[-–]\s*\d+|\d+)",
    ]
    text_l = text.lower()
    for pat in patterns:
        m = re.search(pat, text_l, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Handle text qualifiers for RBCs
    if re.search(r"tntc", text_l) and "pus" not in text_l[:text_l.find("tntc")]:
        return "TNTC"
    # Second /HPF line = RBCs
    hpf_lines = [line for line in text_l.splitlines() if "/hpf" in line or "hpf" in line]
    if len(hpf_lines) >= 2:
        _rbc_l = hpf_lines[1]
        m_ov = re.search(r"over\s*(\d+)|>\s*(\d+)", _rbc_l)
        if m_ov:
            n = m_ov.group(1) or m_ov.group(2)
            return f"Over {n}" if "over" in _rbc_l else f">{n}"
        m2 = re.search(r"(\d+\s*[-–]\s*\d+|\d+)", _rbc_l)
        if m2:
            return m2.group(1).strip()
    return ""


def detect_culture_condition(text: str) -> str:
    """استخرج نوع ظروف المزرعة: Aerobic / Anaerobic / Both."""
    text_l = text.lower()
    if re.search(r"both|aerobic\s*[&+]\s*anaerobic|anaerobic\s*[&+]\s*aerobic", text_l):
        return "Both (Aerobic + Anaerobic)"
    if re.search(r"anaerob", text_l):
        return "Anaerobic"
    if re.search(r"aerob", text_l):
        return "Aerobic"
    return ""


def extract_all_data_cached(file_bytes: bytes) -> Dict[str, Any]:
    _, thresh  = preprocess_image(file_bytes)
    full_text  = run_ocr(thresh)
    text_lower = full_text.lower()
    sir_map: Dict[str, str] = {}
    for line in full_text.splitlines():
        line = line.strip()
        if not line:
            continue
        result = classify_sir_from_line(line)
        if not result:
            continue
        matched_abx = match_antibiotic_from_text(line)
        if matched_abx:
            sir_map[matched_abx] = result
    return {
        "patient": {
            "Name":     None,  # الاسم يُدخل يدوياً فقط
            "Age":      detect_age(full_text),
            "Sex":      detect_sex(text_lower),
            "Specimen": detect_specimen(text_lower),
            "Organism": detect_organism(text_lower),
        },
        "drugs":     extract_detected_drugs(full_text),
        "sir_map":   sir_map,
        "raw_text":  full_text,
        # ── New: Microscopy + Condition ──────────────────────────────────
        "pus_cells": detect_pus_cells(full_text),
        "rbcs":      detect_rbcs(full_text),
        "condition": detect_culture_condition(full_text),
    }

# =========================================================
# التحليل السريري
# =========================================================



# =========================================================
# MDR / XDR / PDR Classification — CDC & ECDC 2017
# =========================================================
# تعريف الفئات حسب Magiorakos et al. 2012 (ECDC/CDC)
#
# ⚠️ بعض الأدوية هنا مش في الـ active formulary (abx_guidelines.py):
#    Minocycline, Erythromycin, Clindamycin, Rifampicin
#    → مدرجة هنا فقط لـ MDR resistance scoring من نتيجة الـ AST
#    → مش هتظهر في توصيات العلاج
# =========================================================

# Categories meaningful for Gram-negative organisms (Enterobacterales / non-fermenters)
# Categories meaningful for Gram-positive organisms


# Intrinsic resistance — organism is naturally resistant; EXCLUDE from MDR calc
# (Magiorakos 2012 / EUCAST Expert Rules v3.3 / CLSI M100)




# =========================================================
# ESBL / AmpC / Carbapenemase Predictor
# EUCAST 2026 | CLSI M100 2026 | EUCAST guidance on detection of resistance mechanisms
# =========================================================
# Organisms capable of ESBL production (Enterobacterales).
# Stored as a set; matching is substring-based to handle OCR variants.
# AmpC-prone organisms (chromosomal inducible AmpC — "SPICE/SPACE")



# =========================================================
# Pathogenicity Assessment Module — v2
# Covers: Urine, Sputum (Murray-Washington), Blood (SIRS),
#         Wound/Pus, CSF, Swab
# Includes: Pediatric thresholds, ABU detection
# =========================================================






# ═══════════════════════════════════════════════════════════════════════
# CLINICAL DECISION ENGINES — v4.0
# ① Treatment Duration  ② IV→PO Switch  ③ Hepatic Dosing (Child-Pugh)
# ④ Combination Therapy  ⑤ De-escalation Advisor
# References: IDSA AMR 2025 | Sanford 2025 | WHO AWaRe 2025
#             MERINO 2018 | NINJA 2020 | ATTACK 2023 | STOP-IT 2015
# ═══════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════
# ENGINE 1 — Treatment Duration Engine
# IDSA AMR 2025 | Sanford Guide 2025 | ATS/IDSA CAP 2019
# IDSA UTI 2022 | IDSA SSTI 2014 | STOP-IT trial 2015
# ═══════════════════════════════════════════════════════════════════════





# ═══════════════════════════════════════════════════════════════════════
# ENGINE 2 — IV→PO Switch Engine
# IDSA OPAT 2019 | BNF 2025 | BSAC 2023
# ═══════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════
# ENGINE 3 — Hepatic Dosing (Child-Pugh A/B/C)
# BNF 2025 | Lexicomp 2025 | UpToDate 2025
# ═══════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════
# ENGINE 4 — Combination Therapy Suggester
# IDSA AMR 2025 | WHO Priority Pathogens | ESCAPE organisms
# ═══════════════════════════════════════════════════════════════════════



# ═══════════════════════════════════════════════════════════════════════
# ENGINE 5 — De-escalation Advisor
# WHO AWaRe 2025 | IDSA Stewardship 2025
# ═══════════════════════════════════════════════════════════════════════




# =========================================================
# MODULE 1 — Resistance Phenotype Engine
# يحدد: ESBL / CRE / MRSA / VRE / MDR / XDR / PDR
# المرجع: EUCAST 2026, CLSI M100 2026, CDC/ECDC 2017
# =========================================================



# =========================================================
# MODULE 2 — AST Quality Control Checker
# يتحقق من تناقضات منطقية في نتائج S/I/R
# المرجع: EUCAST Expert Rules v3.3 + CLSI M100
# =========================================================







# =========================================================
# MODULE 3 — Smart Antibiotic Ranking
# يرتب الأدوية الـ Sensitive حسب الأولوية السريرية
# =========================================================



# =========================================================
# MODULE 4 — Infection Syndrome Module
# يربط Specimen + Organism + Phenotype بـ clinical syndrome
# =========================================================




# =========================================================
# أدوات رسم الصورة
# =========================================================


















# =========================================================
# واجهة التطبيق الرئيسية
# =========================================================
if not st.session_state.authenticated:
    login_result = show_login_page()
    if login_result:
        email_input, password_input = login_result
        if check_subscription(email_input, password_input):
            st.session_state.authenticated = True
            st.session_state.last_activity = time.time()
            st.rerun()  # FIXED: removed experimental_rerun fallback
    st.stop()

handle_session_timeout()
render_top_bar()

# =========================================================
# Isolate Registry — durable store + GitHub sync (HVMS pattern)
# =========================================================
REGISTRY_DB_PATH = st.secrets.get("registry_db_path", "isolates.db") \
    if hasattr(st, "secrets") else "isolates.db"


def _gh_registry_config():
    """GitHub persistence config from secrets, or None if not configured."""
    try:
        token  = st.secrets.get("github_token")
        repo   = st.secrets.get("github_repo")
        branch = st.secrets.get("github_branch", "main")
        rpath  = st.secrets.get("registry_remote_path", "isolates.db")
        if token and repo:
            return {"token": token, "repo": repo, "branch": branch, "remote_path": rpath}
    except Exception as exc:
        logger.warning("Registry GitHub config unavailable: %s", exc)
    return None


@st.cache_resource(show_spinner=False)
def get_registry() -> IsolateRegistry:
    """Create the registry once; pull latest DB from GitHub on cold start."""
    reg = IsolateRegistry(REGISTRY_DB_PATH)
    reg.init_db()
    cfg = _gh_registry_config()
    if cfg:
        try:
            reg.sync_pull(**cfg)
            reg.init_db()  # ensure schema exists even on a fresh pulled file
        except Exception as exc:
            logger.warning("Registry initial pull failed: %s", exc)
    return reg


REGISTRY = get_registry()


def _registry_push() -> bool:
    cfg = _gh_registry_config()
    if not cfg:
        return False
    try:
        return REGISTRY.sync_push(**cfg)
    except Exception as exc:
        logger.exception("Registry push failed: %s", exc)
        return False


# ── Navigation (new pages render then st.stop(); analysis flow is default) ──
_page = st.sidebar.radio(
    "القسم",
    ["🔬 تحليل مزرعة", "📇 سجل العزلات", "📊 Antibiogram"],
    key="_nav_page",
)
st.sidebar.caption(f"📇 العزلات المحفوظة: {REGISTRY.count()}")
if not _gh_registry_config():
    st.sidebar.caption("⚠️ مزامنة GitHub غير مفعّلة — الحفظ محلي فقط.")

if _page == "📇 سجل العزلات":
    render_registry_page(REGISTRY)
    if st.button("🔄 مزامنة السجل مع GitHub", key="reg_sync_btn"):
        if _registry_push():
            st.success("✅ تمت المزامنة.")
        else:
            st.warning("مزامنة GitHub غير مفعّلة أو فشلت — راجع الـ secrets.")
    st.stop()

if _page == "📊 Antibiogram":
    render_antibiogram_page(REGISTRY)
    st.stop()

startup_issues = get_startup_validation_issues()
if startup_issues:
    with st.expander("🧪 Data validation at startup", expanded=False):
        st.warning(f"Found {len(startup_issues)} data issue(s).")
        for issue in startup_issues:
            st.write(f"- {issue}")

st.title("🔬 Microbiology CDSS")
st.caption("AI-Assisted Antibiotic Decision Support — Egyptian Market Edition")

# ── اسم المعمل محدد مسبقاً (Orange Lab) ────────────────────────────────────
# Lab name is fixed — change here or via st.secrets
st.session_state.lab_name = st.secrets.get("lab_name", "Orange Lab") if hasattr(st, "secrets") else st.session_state.get("lab_name", "Orange Lab")
st.session_state.lab_city = st.secrets.get("lab_city", "Giza - 6 October") if hasattr(st, "secrets") else st.session_state.get("lab_city", "Giza - 6 October")



uploaded = st.file_uploader(
    "📷 Upload Culture Report Image",
    type=["jpg", "jpeg", "png"]
)

if uploaded:
    file_bytes = uploaded.getvalue()
    file_hash  = make_file_hash(file_bytes)
    is_new     = (st.session_state.ocr_data is None or
                  st.session_state.last_file_hash != file_hash)

    if is_new:
        # FIXED: clean up old session state keys when loading a new image
        old_hash = st.session_state.get("last_file_hash", "")
        if old_hash and old_hash != file_hash:
            keys_to_delete = [k for k in st.session_state if old_hash[:8] in str(k)]
            for key in keys_to_delete:
                del st.session_state[key]

        with st.spinner("🔍 جاري تحليل صورة التقرير..."):
            try:
                payload = extract_all_data_cached(file_bytes)
                st.session_state.ocr_data           = payload
                st.session_state.last_file_hash     = file_hash
                st.session_state.sir_map_edited     = dict(payload["sir_map"])
                # الاسم يُدخل يدوياً — لا نغير ما أدخله المستخدم عند تحميل صورة جديدة
                st.session_state.patient_name_ocr   = ""
                # patient_name_final محفوظ من الجلسة السابقة (لا نمسحه)
                # صورة جديدة → ابدأ من الخطوة الأولى (المريض والمزرعة)
                st.session_state.wizard_step  = 1
                st.session_state.show_results = False
            except Exception as e:
                st.error(f"تعذر تحليل الصورة: {e}")
                st.stop()

    payload        = st.session_state.ocr_data
    patient        = payload["patient"]
    drugs_from_ocr = payload["drugs"]
    raw_text       = payload["raw_text"]

    if not st.session_state.sir_map_edited and payload["sir_map"]:
        st.session_state.sir_map_edited = dict(payload["sir_map"])

    # Compact preview (≈ A5 width) to save vertical space, with a full-size
    # expander so the user can still zoom in to verify the antibiogram values
    # against the OCR result — critical when OCR may misread S/I/R.
    _prev_l, _prev_r = st.columns([1, 1])
    with _prev_l:
        st.image(file_bytes, caption="Preview (مصغّر)", width=380)
    with _prev_r:
        st.caption("📋 راجع النص المستخرج بالأسفل، وكبّر الصورة للتحقق من "
                   "قراءة الحساسية إن لزم.")
        with st.expander("🔍 تكبير الصورة للتحقق", expanded=False):
            st.image(file_bytes, use_container_width=True)

    with st.expander("📝 النص المستخرج من التقرير (OCR)", expanded=False):
        st.text_area("Extracted Text", raw_text, height=220, label_visibility="collapsed")

    # ── Wizard: derive current step (1 Patient → 2 AST → 3 Results) ──────────
    if st.session_state.get("show_results", False):
        _cur_step = 3
    else:
        _cur_step = st.session_state.get("wizard_step", 1)

    # ── Interactive SIDEBAR step navigation (free navigation, not linear) ─────
    # Like a lab-management app: the three phases live in the sidebar; click any
    # one to jump straight to it. The current step is highlighted. Results stay
    # locked until at least one AST value exists (so no empty report is shown).
    _n_ast_now = len(st.session_state.get("sir_map_edited", {}) or {})
    st.sidebar.markdown("### 🧭 خطوات التحليل")
    _steps_meta = [
        (1, "① المريض والمزرعة", True),
        (2, "② الحساسية (AST)",  True),
        (3, "③ النتائج والتقرير", _n_ast_now > 0),
    ]
    for _idx, _label, _enabled in _steps_meta:
        _is_here = (_idx == _cur_step)
        _btn_label = ("● " + _label) if _is_here else _label
        if st.sidebar.button(
            _btn_label,
            key=f"sidebar_step_{_idx}",
            use_container_width=True,
            type=("primary" if _is_here else "secondary"),
            disabled=(_is_here or not _enabled),
            help=(None if _enabled else "أدخل نتيجة حساسية واحدة على الأقل أولاً"),
        ):
            if _idx == 3:
                st.session_state.show_results = True
            else:
                st.session_state.show_results = False
                st.session_state.wizard_step = _idx
            st.rerun()
    if _cur_step == 3 and _n_ast_now == 0:
        # safety: somehow on results with no AST — send back to AST
        st.session_state.show_results = False
        st.session_state.wizard_step = 2
        st.rerun()
    st.sidebar.divider()

    # ── In-page clickable step navigation (always visible, not just sidebar) ──
    # Three buttons across the top of the page. Click any to jump to that step.
    # The current step is highlighted (primary + disabled). Results is locked
    # until an AST value exists. This guarantees navigation is reachable even if
    # the sidebar is collapsed (e.g. on mobile).
    _nav1, _nav2, _nav3 = st.columns(3)
    _step_defs = [
        (_nav1, 1, "① المريض والمزرعة", True),
        (_nav2, 2, "② الحساسية (AST)",  True),
        (_nav3, 3, "③ النتائج والتقرير", _n_ast_now > 0),
    ]
    for _col, _idx, _label, _enabled in _step_defs:
        _is_here = (_idx == _cur_step)
        _mark = "🔵 " if _is_here else ("✅ " if _idx < _cur_step else "")
        if _col.button(
            _mark + _label,
            key=f"inpage_step_{_idx}",
            use_container_width=True,
            type=("primary" if _is_here else "secondary"),
            disabled=(_is_here or not _enabled),
            help=(None if _enabled else "أدخل نتيجة حساسية واحدة على الأقل أولاً"),
        ):
            if _idx == 3:
                st.session_state.show_results = True
            else:
                st.session_state.show_results = False
                st.session_state.wizard_step = _idx
            st.rerun()
    st.markdown("<div style='margin-bottom:8px'></div>", unsafe_allow_html=True)

    # Sequential full-width layout (not side-by-side columns). In steps 2-3 the
    # patient/culture column must still RENDER (its widgets return the values the
    # analysis needs and stay editable), but should be visually hidden so the AST
    # / results take the whole screen. col1 contains nested expanders so it can't
    # itself be an expander; instead we drop an invisible marker inside it and use
    # scoped CSS to collapse the Streamlit block that contains that marker. This
    # keeps execution intact while giving a clean, single-focus screen per step.
    _hide_patient = _cur_step in (2, 3)
    # In step 3 (results) the AST-entry column must also be hidden so the report
    # stands alone; the analysis still runs (it reads sir_map from session_state).
    _hide_ast = _cur_step == 3
    # When the patient column is hidden (steps 2-3), we still want a compact
    # patient summary visible. This external slot sits above the columns and is
    # filled from inside col1 once the values are known.
    _ext_summary_slot = st.container()
    col1 = st.container()
    col2 = st.container()

    # ─── العمود الأيسر ────────────────────────────────────────────────────────
    with col1:
        if _hide_patient:
            # Invisible anchor + CSS: hide the vertical block that holds this
            # marker (the patient column) without removing it from the run.
            # Uses :has() (supported in all current evergreen browsers). If a
            # browser lacks :has(), the column simply stays visible — the app
            # still works and no value is lost.
            st.markdown(
                "<span class='oc-hide-anchor' "
                "style='display:none'></span>"
                "<style>"
                "div[data-testid='stVerticalBlock']:has(> "
                "div[data-testid='stElementContainer'] .oc-hide-anchor),"
                "div[data-testid='stVerticalBlock']:has(> "
                "div[data-testid='element-container'] .oc-hide-anchor){"
                "position:absolute!important;width:1px!important;height:1px!important;"
                "padding:0!important;margin:-1px!important;overflow:hidden!important;"
                "clip:rect(0 0 0 0)!important;white-space:nowrap!important;"
                "border:0!important;}"
                "</style>",
                unsafe_allow_html=True,
            )
        st.subheader("① المريض والمزرعة")

        # Sticky summary card — a placeholder rendered HERE (top of the input
        # column) but filled AFTER all inputs are collected, so the user always
        # sees the current patient/specimen/organism at a glance without
        # scrolling. Streamlit runs top-to-bottom, so we reserve the slot now and
        # populate it once the values exist.
        _summary_slot = st.container()

        # اسم المريض — إدخال يدوي فقط
        patient_name = st.text_input(
            "👤 اسم المريض / Patient Name",
            value=st.session_state.get("patient_name_final", ""),
            placeholder="أدخل اسم المريض",
            help="يظهر في التقرير وصورة الملخص.",
            key=f"pname_{file_hash[:8]}"
        )
        st.session_state.patient_name_final = patient_name.strip()

        _c_lab, _c_mob = st.columns(2)
        with _c_lab:
            lab_id = st.text_input(
                "🆔 كود المعمل / Lab ID",
                value=st.session_state.get("lab_id", ""),
                placeholder="مثال: 2026-01234",
                help="يُستخدم لمنع تكرار نفس المريض في الأنتيبيوجرام (CLSI M39).",
                key=f"labid_{file_hash[:8]}",
            )
            st.session_state.lab_id = lab_id.strip()
        with _c_mob:
            mobile = st.text_input(
                "📱 موبايل / Mobile",
                value=st.session_state.get("mobile", ""),
                placeholder="01xxxxxxxxx",
                key=f"mobile_{file_hash[:8]}",
            )
            st.session_state.mobile = mobile.strip()

        _c_spec, _c_org = st.columns(2)
        with _c_spec:
            culture_type = st.selectbox(
                "🧫 Specimen",
                SPECIMEN_TYPES,
                index=best_default_index(SPECIMEN_TYPES, patient.get("Specimen"))
            )
        filtered_organisms = [
            org for org in get_organisms_for_specimen(culture_type)
            if org in ORGANISM_PROFILE
        ]
        if not filtered_organisms:
            filtered_organisms = BACTERIA_TYPES
        with _c_org:
            organism_type = st.selectbox(
                "🦠 Organism",
                filtered_organisms,
                index=best_default_index(filtered_organisms, patient.get("Organism")),
                help=f"بكتيريا شائعة في عينة {culture_type}",
            )

        # ── حقول المزرعة والمجهر ──────────────────────────────────────────────
        st.divider()
        st.subheader("🔬 Culture & Microscopic Details")

        # Specimen-type flags — used to show ONLY the inputs that are relevant to
        # this specimen (colony count → urine; pus/RBC microscopy → urine; blood
        # bottle source → blood; sputum quality → sputum). This keeps the screen
        # from showing every field for every specimen at once.
        _spec_l      = (culture_type or "").lower()
        _is_urine    = "urine" in _spec_l
        _is_blood    = "blood" in _spec_l
        _is_sputum   = any(k in _spec_l for k in ["sputum", "respir", "bal", "bronch"])
        _is_stool    = any(k in _spec_l for k in ["stool", "fecal", "rectal"])
        _is_csf      = "csf" in _spec_l or "cerebro" in _spec_l
        _is_wound    = any(k in _spec_l for k in ["wound", "pus", "swab", "tissue",
                                                  "abscess", "aspirate"])

        # Colony count (urine only) + date on one row to save vertical space.
        if _is_urine:
            _c_col, _c_date = st.columns(2)
            with _c_col:
                colony_count = st.text_input(
                    "Colony Count (CFU/mL)",
                    value=st.session_state.colony_count,
                    placeholder="≥ 10^5 CFU/mL",
                    key="colony_count_input"
                )
                st.session_state.colony_count = colony_count
            with _c_date:
                date_in = st.date_input(
                    "📅 Date In",
                    value=st.session_state.date_in,
                    key="date_in_input"
                )
                st.session_state.date_in = date_in
        else:
            colony_count = st.session_state.colony_count
            date_in = st.date_input(
                "📅 Date In (تاريخ استلام العينة)",
                value=st.session_state.date_in,
                key="date_in_input"
            )
            st.session_state.date_in = date_in

        # ── Auto-populate Pus/RBCs/Condition from OCR — only ONCE per file ────
        _ocr_done_key = f"_ocr_filled_{file_hash[:12]}"
        if payload and not st.session_state.get(_ocr_done_key, False):
            _ocr_pus = payload.get("pus_cells", "")
            _ocr_rbc = payload.get("rbcs", "")
            _ocr_cnd = payload.get("condition", "")
            _filled  = []
            if _ocr_pus and not st.session_state.get("pus_cells_text",""):
                st.session_state.pus_cells_text = _ocr_pus
                _filled.append(f"Pus: {_ocr_pus}/HPF")
            if _ocr_rbc and not st.session_state.get("rbcs_text",""):
                st.session_state.rbcs_text = _ocr_rbc
                _filled.append(f"RBCs: {_ocr_rbc}/HPF")
            if _ocr_cnd and st.session_state.get("culture_condition","Aerobic") == "Aerobic":
                st.session_state.culture_condition = _ocr_cnd
                _filled.append(f"Condition: {_ocr_cnd}")
            if _filled:
                st.toast("🔍 OCR auto-filled: " + " | ".join(_filled), icon="🔬")
            st.session_state[_ocr_done_key] = True  # never fire again for this file

        # Pus-cell / RBC microscopy is interpreted for urine (pyuria/haematuria)
        # and wound/pus (pus cells). It is not a standard input for blood, CSF or
        # stool — hide it there but keep any stored value.
        if _is_urine or _is_wound:
            c_pus, c_rbc = st.columns(2)
            with c_pus:
                pus_cells_text = st.text_input(
                    "Pus Cells (/HPF)",
                    value=st.session_state.pus_cells_text,
                    placeholder="مثال: 4 - 6",
                    key="pus_cells_input"
                )
                st.session_state.pus_cells_text = pus_cells_text
            with c_rbc:
                rbcs_text = st.text_input(
                    "RBC Cells (/HPF)",
                    value=st.session_state.rbcs_text,
                    placeholder="مثال: 2 - 4",
                    key="rbcs_input"
                )
                st.session_state.rbcs_text = rbcs_text
        else:
            pus_cells_text = st.session_state.pus_cells_text
            rbcs_text      = st.session_state.rbcs_text

        # Organism guidance
        if organism_type in ORGANISM_PROFILE:
            op = ORGANISM_PROFILE[organism_type]
            with st.expander("📌 Organism Guidance", expanded=True):
                st.info(op.get("note", ""))
                spec_ctx = (op.get("specimen_context") or {}).get(culture_type, "")
                if spec_ctx:
                    st.warning(f"**{culture_type} Context:** {spec_ctx}")
                if op.get("first_line"):
                    st.write("**First-line:**", ", ".join(op["first_line"]))
                if op.get("second_line"):
                    st.write("**Second-line:**", ", ".join(op["second_line"]))
                if op.get("third_line"):
                    st.write("**Third-line:**", ", ".join(op["third_line"]))
                if op.get("avoid"):
                    st.error("**Avoid:** " + ", ".join(op["avoid"]))
                if culture_type == "Urine" and op.get("urine_note"):
                    st.info(f"📌 Urine notes:\n{op['urine_note']}")

        st.divider()

        _c_age, _c_sex, _c_wt = st.columns(3)
        with _c_age:
            age = st.number_input("Age (years)", min_value=0, max_value=120,
                                   value=safe_int(patient.get("Age"), 25))
        with _c_sex:
            default_sex = patient.get("Sex") if patient.get("Sex") in ["Female", "Male"] else "Male"
            sex    = st.selectbox("Gender", ["Female", "Male"],
                                  index=0 if default_sex == "Female" else 1)
        with _c_wt:
            weight = st.number_input("Weight (kg)", min_value=5, max_value=300, value=70)

        st.divider()

        st.divider()

        _c_ren, _c_hep, _c_preg = st.columns(3)
        with _c_ren:
            is_renal = st.checkbox("🚩 Renal Impairment")
        with _c_hep:
            is_hepatic = st.checkbox("🚩 Hepatic Impairment")
        with _c_preg:
            is_preg = False
            if sex == "Female" and 18 <= age <= 55:
                is_preg = st.checkbox("🤰 Pregnant")

        cl_cr = 100.0
        if is_renal:
            s_cr  = st.number_input("Serum Creatinine (mg/dL)",
                                    min_value=0.1, max_value=20.0, value=1.0, step=0.1)
            cl_cr = calc_creatinine_clearance(age, weight, s_cr, sex)
            st.metric("CrCl (Cockcroft-Gault)", f"{cl_cr:.1f} ml/min",
                      delta=get_renal_severity(cl_cr),
                      delta_color="normal" if cl_cr >= 60 else ("off" if cl_cr >= 30 else "inverse"))

        current_meds = st.multiselect("💊 Current Medications", COMMON_MEDS)

        # ── Populate the sticky summary card (declared above the inputs) ─────
        # Compact chips: age/sex, specimen, organism, drug count, plus any active
        # clinical flags (renal/hepatic/pregnant). Always visible at the top.
        with _summary_slot:
            _n_abx = len(st.session_state.get("sir_map_edited", {}) or {})
            _sum_chips = [
                f"{int(age)}y", sex, culture_type, organism_type,
                f"{_n_abx} abx" if _n_abx else "no AST yet",
            ]
            _flag_chips = []
            if is_renal:
                _flag_chips.append(("Renal", f"CrCl {cl_cr:.0f}", "#b7770d"))
            if is_hepatic:
                _flag_chips.append(("Hepatic", "impaired", "#b7770d"))
            if is_preg:
                _flag_chips.append(("Pregnant", "⚠", "#922b21"))
            _base = " ".join(
                f"<span style='background:#eef2f5;color:#243b53;padding:2px 9px;"
                f"border-radius:9px;font-size:0.8em;margin:0 5px 4px 0;"
                f"display:inline-block;white-space:nowrap'>{c}</span>"
                for c in _sum_chips
            )
            _flags = " ".join(
                f"<span style='background:{col};color:#fff;padding:2px 9px;"
                f"border-radius:9px;font-size:0.8em;margin:0 5px 4px 0;"
                f"display:inline-block;white-space:nowrap'>{name}: {val}</span>"
                for name, val, col in _flag_chips
            )
            st.markdown(
                "<div style='border:1px solid #d6dde3;border-radius:8px;"
                "padding:8px 10px;margin-bottom:6px;background:#fafbfc'>"
                f"{_base}{_flags}</div>",
                unsafe_allow_html=True,
            )

        # When the patient column is hidden (steps 2-3), surface the SAME summary
        # in the external slot above the columns so context is never lost.
        if _hide_patient:
            with _ext_summary_slot:
                st.markdown(
                    "<div style='border:1px solid #d6dde3;border-radius:8px;"
                    "padding:8px 10px;margin-bottom:8px;background:#fafbfc'>"
                    "<span style='color:#7a8a99;font-size:0.78em;margin-left:6px'>"
                    "① بيانات المريض:</span> "
                    f"{_base}{_flags}</div>",
                    unsafe_allow_html=True,
                )

        with st.expander("🏥 Lab Report Fields", expanded=False):
            _ref_phys = st.text_input(
                "Referred by (Physician Name)",
                value=st.session_state.get("referring_physician",""),
                placeholder="Dr. Ahmed Mohamed",
                key="ref_phys_input"
            )
            st.session_state.referring_physician = _ref_phys

            _culture_cond = st.selectbox(
                "Culture Condition",
                ["Aerobic", "Anaerobic", "Both (Aerobic + Anaerobic)"],
                index=["Aerobic","Anaerobic","Both (Aerobic + Anaerobic)"].index(
                    st.session_state.get("culture_condition","Aerobic")
                ),
                key="culture_cond_sel"
            )
            st.session_state.culture_condition = _culture_cond

            _micro_name = st.text_input(
                "Microbiologist Name",
                value=st.session_state.get("microbiologist",""),
                placeholder="Dr. Aya Gamal",
                key="micro_name_input"
            )
            st.session_state.microbiologist = _micro_name

        # ══════════════════════════════════════════════════════════════════════
        # 🔬 AST-QA ENGINE — Laboratory Consistency Checker
        # ══════════════════════════════════════════════════════════════════════
        try:
            from ast_qa_engine import run_ast_qa_engine, QAIssue
            _qa_sir = st.session_state.get("sir_map_edited") or {}
            _qa_esbl = st.session_state.get("esbl_result")
            _qa_mdr  = st.session_state.get("mdr_result")

            if _qa_sir and organism_type:
                _qa_issues = run_ast_qa_engine(
                    organism=organism_type,
                    specimen=culture_type,
                    sir_map=_qa_sir,
                    esbl_result=_qa_esbl,
                    mdr_result=_qa_mdr,
                )

                _qa_critical = [i for i in _qa_issues if i.severity == "CRITICAL"]
                _qa_high     = [i for i in _qa_issues if i.severity == "HIGH"]
                _qa_medium   = [i for i in _qa_issues if i.severity == "MEDIUM"]
                _qa_low      = [i for i in _qa_issues if i.severity == "LOW"]

                _qa_label = "🟢 AST-QA: No Issues Detected"
                _qa_color = "normal"
                if _qa_critical:
                    _qa_label = f"🔴 AST-QA: {len(_qa_critical)} CRITICAL Issue(s)"
                    _qa_color = "error"
                elif _qa_high:
                    _qa_label = f"🟠 AST-QA: {len(_qa_high)} HIGH Issue(s)"
                    _qa_color = "warning"
                elif _qa_medium or _qa_low:
                    _qa_label = f"🟡 AST-QA: {len(_qa_medium + _qa_low)} Notice(s)"
                    _qa_color = "warning"

                with st.expander(
                    f"🔬 {_qa_label} — Laboratory Consistency Check",
                    expanded=bool(_qa_critical or _qa_high)
                ):
                    if not _qa_issues:
                        st.success("✅ All AST consistency checks passed. No issues detected.")
                    else:
                        st.caption(
                            f"Checked: {len(_qa_sir)} drugs | "
                            f"Issues: {len(_qa_critical)} Critical · "
                            f"{len(_qa_high)} High · "
                            f"{len(_qa_medium)} Medium · "
                            f"{len(_qa_low)} Low"
                        )

                    _SEV_CFG = {
                        "CRITICAL": ("🔴", "error",   "L{level} CRITICAL"),
                        "HIGH":     ("🟠", "warning", "L{level} HIGH"),
                        "MEDIUM":   ("🟡", "warning", "L{level} MEDIUM"),
                        "LOW":      ("🔵", "info",    "L{level} LOW"),
                    }

                    for _qi in _qa_issues:
                        _icon, _type, _lvl_tmpl = _SEV_CFG.get(
                            _qi.severity, ("⚪","info","L{level}")
                        )
                        _lvl_str = _lvl_tmpl.format(level=_qi.level)
                        with st.container():
                            st.markdown(
                                f"**{_icon} [{_lvl_str}] {_qi.category}** — {_qi.message}"
                            )
                            with st.expander("Details & Reference", expanded=False):
                                st.write(_qi.detail)
                                if _qi.drug:
                                    st.caption(f"🧪 Drug(s): {_qi.drug}")
                                if _qi.reference:
                                    st.caption(f"📚 Reference: {_qi.reference}")
                            st.divider()
        except ImportError:
            pass  # ast_qa_engine not available in this environment
        except Exception as _qa_err:
            pass  # Silent fail — QA engine should not break main flow

        # ── Pathogenicity Assessment Module v2 ───────────────────────────────
        # Clear stale patho_result when specimen changes
        if st.session_state.get("last_patho_specimen","") != culture_type:
            st.session_state.patho_result = None
            st.session_state.last_patho_specimen = culture_type
            # Reset specimen-specific symptoms to avoid stale defaults
            st.session_state.patho_symptoms = []
            st.session_state.patho_sirs = []
            st.session_state.patho_blood_source = ""
            st.session_state.patho_wound_type = ""

        st.divider()
        with st.expander("🧫 Pathogenicity Assessment", expanded=False):
            st.caption("هل العينة تمثل عدوى حقيقية أم تلوث؟ — يدعم Urine · Sputum · Blood · Wound · CSF")

            pa_col1, pa_col2 = st.columns(2)
            with pa_col1:
                patho_purity = st.selectbox(
                    "نقاء المزرعة",
                    ["Pure growth", "Mixed growth"],
                    index=0 if st.session_state.patho_culture_purity == "Pure growth" else 1,
                    key="patho_purity_sel"
                )
                st.session_state.patho_culture_purity = patho_purity

                patho_gram = st.selectbox(
                    "Gram Stain",
                    ["مش متعملة",
                     "WBCs + Gram Positive Cocci",
                     "WBCs + Gram Negative Rods",
                     "Organisms بدون WBCs",
                     "طبيعية (No organisms seen)"],
                    key="patho_gram_sel"
                )
                st.session_state.patho_gram_stain = patho_gram

            with pa_col2:
                # Urinalysis only for Urine
                if "urine" in culture_type.lower():
                    patho_urinalysis = st.selectbox(
                        "نتيجة Urinalysis",
                        ["مش معروف / مش مذكور", "Urinalysis طبيعي",
                         "Pyuria (WBCs > 5/HPF)", "Nitrites Positive", "Hematuria"],
                        key="patho_ua_sel"
                    )
                    st.session_state.patho_urinalysis = patho_urinalysis
                else:
                    patho_urinalysis = "مش معروف / مش مذكور"
                    st.caption("🔬 Urinalysis — خاص بمزارع البول فقط")

            # ── Specimen-specific fields ──────────────────────────────────────
            spec_lower_ui = culture_type.lower()

            # Urine symptoms
            if "urine" in spec_lower_ui:
                patho_symptoms = st.multiselect(
                    "الأعراض الكلينيكية",
                    ["Dysuria / Frequency / Urgency", "Fever (> 38°C)",
                     "Flank pain / Loin pain", "Nocturnal enuresis",
                     "Abdominal pain", "Nausea / Vomiting", "Asymptomatic"],
                    default=st.session_state.patho_symptoms,
                    key="patho_symp_urine"
                )

            # Sputum — Murray-Washington fields
            elif "sputum" in spec_lower_ui or "respiratory" in spec_lower_ui:
                st.markdown("**Murray-Washington Criteria**")
                mw_c1, mw_c2 = st.columns(2)
                with mw_c1:
                    patho_sputum_pus = st.text_input(
                        "WBC/LPF (Pus cells per low-power field)",
                        value=st.session_state.patho_sputum_pus,
                        placeholder="مثال: 30",
                        key="patho_mw_pus"
                    )
                    st.session_state.patho_sputum_pus = patho_sputum_pus
                with mw_c2:
                    patho_sputum_epi = st.text_input(
                        "Epithelial cells/LPF",
                        value=st.session_state.patho_sputum_epi,
                        placeholder="مثال: 5",
                        key="patho_mw_epi"
                    )
                    st.session_state.patho_sputum_epi = patho_sputum_epi
                st.caption("✅ Adequate: WBC ≥25 & Epi <10 | ❌ Reject: Epi ≥25")
                patho_symptoms = st.multiselect(
                    "الأعراض التنفسية",
                    ["Productive cough / Purulent sputum", "Fever (> 38°C)",
                     "Dyspnea", "Pleuritic chest pain", "Asymptomatic"],
                    default=st.session_state.patho_symptoms,
                    key="patho_symp_sputum"
                )

            # Blood — SIRS criteria
            elif "blood" in spec_lower_ui:
                st.markdown("**SIRS Criteria** (اختر كل المعايير الموجودة)")
                patho_sirs = st.multiselect(
                    "SIRS Criteria",
                    ["Fever > 38°C or Temp < 36°C",
                     "HR > 90 bpm",
                     "RR > 20 or PaCO₂ < 32",
                     "WBC > 12,000 or < 4,000 or >10% bands"],
                    default=st.session_state.patho_sirs,
                    key="patho_sirs_sel"
                )
                st.session_state.patho_sirs = patho_sirs
                patho_blood_source = st.selectbox(
                    "Bottles / Source",
                    ["غير محدد", "Single bottle positive",
                     "Multiple bottles positive", "Source identified (CVC/wound)"],
                    key="patho_blood_src"
                )
                st.session_state.patho_blood_source = patho_blood_source
                patho_symptoms = st.session_state.patho_symptoms

            # Wound / Swab
            elif any(w in spec_lower_ui for w in ["wound", "pus", "swab", "abscess"]):
                patho_wound_type = st.selectbox(
                    "نوع الجرح",
                    ["غير محدد", "Surgical / Post-op wound",
                     "Chronic / Diabetic wound", "Traumatic wound",
                     "Superficial wound", "Deep tissue / Abscess"],
                    key="patho_wound_type_sel"
                )
                st.session_state.patho_wound_type = patho_wound_type
                patho_symptoms = st.multiselect(
                    "علامات العدوى",
                    ["Erythema / Warmth / Swelling", "Purulent discharge",
                     "Fever (> 38°C)", "Pain / Tenderness", "Asymptomatic"],
                    default=st.session_state.patho_symptoms,
                    key="patho_symp_wound"
                )
            elif any(k in culture_type.lower() for k in ["stool","fecal","rectal","gi"]):
                patho_symptoms = st.multiselect(
                    "الأعراض الجهاز الهضمي",
                    ["Fever (> 38°C)", "Bloody diarrhea", "Watery diarrhea",
                     "Vomiting", "Abdominal cramps", "Asymptomatic"],
                    default=st.session_state.patho_symptoms,
                    key="patho_symp_stool"
                )
            else:
                patho_symptoms = st.multiselect(
                    "الأعراض الكلينيكية",
                    ["Fever (> 38°C)", "Localized pain", "Asymptomatic"],
                    default=st.session_state.patho_symptoms,
                    key="patho_symp_other"
                )

            st.session_state.patho_symptoms = patho_symptoms

            # Host factors (universal)
            patho_host = st.multiselect(
                "عوامل المضيف",
                ["Immunosuppressants / Steroids",
                 "Urinary catheter", "Central line / PICC",
                 "تاريخ UTIs متكررة", "Recurrent infections",
                 "Diabetes",
                 "Renal abnormality / Vesicoureteral reflux",
                 "Pregnant", "Pre-surgical"],
                default=st.session_state.patho_host_factors,
                key="patho_host_sel"
            )
            st.session_state.patho_host_factors = patho_host

            if st.button("🔬 احسب Pathogenicity Score", use_container_width=True, key="patho_calc_btn"):
                # Build kwargs based on specimen
                patho_kwargs = dict(
                    specimen=culture_type,
                    organism=organism_type,
                    colony_count_text=colony_count,
                    culture_purity=patho_purity,
                    symptoms=patho_symptoms,
                    pus_cells_text=pus_cells_text,
                    urinalysis_result=patho_urinalysis,
                    gram_stain=patho_gram,
                    age=age,
                    sex=sex,
                    host_factors=patho_host,
                )
                if "sputum" in spec_lower_ui or "respiratory" in spec_lower_ui:
                    patho_kwargs["sputum_pus_cells"]  = st.session_state.patho_sputum_pus
                    patho_kwargs["sputum_epithelial"] = st.session_state.patho_sputum_epi
                if "blood" in spec_lower_ui:
                    patho_kwargs["sirs_criteria"]  = st.session_state.patho_sirs
                    patho_kwargs["blood_source"]   = st.session_state.patho_blood_source
                if any(w in spec_lower_ui for w in ["wound","pus","swab","abscess"]):
                    patho_kwargs["wound_type"] = st.session_state.patho_wound_type

                patho_result = assess_pathogenicity(**patho_kwargs)
                st.session_state.patho_result = patho_result

            # ── Display Result (persists after button) ────────────────────
            patho_result = st.session_state.get("patho_result")
            if patho_result:
                sc    = patho_result["score"]
                color = patho_result["color"]
                flags = patho_result.get("special_flags", [])

                st.markdown(f"### Pathogenicity Score: **{sc}%**")
                st.progress(sc / 100)

                if color == "error":
                    st.error(patho_result["verdict"])
                elif color == "warning":
                    st.warning(patho_result["verdict"])
                else:
                    st.success(patho_result["verdict"])

                # ABU badge
                if patho_result.get("abu_detected"):
                    st.info("🔵 **Asymptomatic Bacteriuria (ABU) Detected** — راجع IDSA 2019")

                # Murray-Washington badge
                if "MW_REJECT" in flags:
                    st.error("🧫 **Murray-Washington: Specimen REJECTED** — إعادة أخذ العينة ضرورية")
                elif "MW_ADEQUATE" in flags:
                    st.success("🧫 **Murray-Washington: Adequate Sputum** ✅")
                elif "MW_MIXED" in flags:
                    st.warning("🧫 **Murray-Washington: Mixed Quality** — تحليل بتحفظ")

                # SIRS badge
                if "SIRS_HIGH" in flags:
                    st.error("🩸 **SIRS ≥3 criteria** — Sepsis Probable")
                elif "SIRS_MET" in flags:
                    st.warning("🩸 **SIRS 2 criteria** — Bacteremia Possible")

                # Pediatric badge
                if "PEDIATRIC_UTI" in flags:
                    st.info("👶 **Pediatric threshold applied** (Age < 2 yrs — any growth significant)")

                st.info(patho_result["interpretation"])

                col_pos, col_neg = st.columns(2)
                with col_pos:
                    if patho_result["factors_pos"]:
                        st.markdown("**✅ Supporting Factors**")
                        for f in patho_result["factors_pos"]:
                            st.write(f)
                with col_neg:
                    if patho_result["factors_neg"]:
                        st.markdown("**⚠️ Against Infection**")
                        for f in patho_result["factors_neg"]:
                            st.write(f)

                st.markdown("**📋 التوصيات:**")
                for rec in patho_result["recommendations"]:
                    st.write(f"• {rec}")

    # ══════════════════════════════════════════════════════════════════════
    # WIZARD GATE ①→② : after Patient/Culture, advance to AST entry
    # ══════════════════════════════════════════════════════════════════════
    # In step 1 we stop here so the user sees only the patient/culture form.
    # col1 above always executes (its widget values are needed later); this gate
    # only controls whether the AST step and results render.
    if _cur_step == 1:
        st.divider()
        if st.button("التالي: إدخال الحساسية ▶️", type="primary",
                     use_container_width=True, key="wiz_to_ast"):
            st.session_state.wizard_step = 2
            st.rerun()
        st.caption("💡 يمكنك التنقّل بين الخطوات من القائمة الجانبية في أي وقت.")
        st.stop()


    # ─── العمود الأيمن ────────────────────────────────────────────────────────
    with col2:
        # AST entry must always execute (it builds sir_map from the widgets). In
        # step 3 we tuck it into a collapsed expander so the report stands alone,
        # while still running. The AST panel has no inner expanders, so wrapping it
        # in one is safe. In steps 1-2 it's a plain container (fully visible).
        if _hide_ast:
            _ast_host = st.expander("② الحساسية (AST) — تم — اضغط للتعديل",
                                    expanded=False)
        else:
            _ast_host = st.container()
        with _ast_host:
            if not _hide_ast:
                st.subheader("② إدخال الحساسية (AST)")

            # ══════════════════════════════════════════════════════════════
            # AST Input Panel — OCR + Manual Entry موحّد
            # ══════════════════════════════════════════════════════════════
            ocr_sir_map = payload["sir_map"]
            sir_options = ["S", "I", "R"]

            st.markdown("**📊 نتائج المزرعة — S / I / R**")
            st.caption("✅ من OCR تلقائياً — عدّل أي قيمة خطأ، احذف مضاداً، أو أضِف مضاداً فاته الـ OCR من الأسفل")

            # ── Drugs detected by OCR WITH S/I/R ─────────────────────────
            all_known   = sorted(ABX_GUIDELINES.keys())
            ocr_drugs   = list(ocr_sir_map.keys())

            # Drugs OCR found by NAME but couldn't determine S/I/R for
            ocr_detected_no_sir = [d for d in drugs_from_ocr
                                    if d not in ocr_sir_map and d]

            if ocr_detected_no_sir:
                st.markdown(
                    f"**🔍 OCR اكتشف {len(ocr_detected_no_sir)} مضاد بدون نتيجة S/I/R واضحة:**",
                    help="OCR وجد أسماء هذه الأدوية في الورقة لكن لم يتعرف على النتيجة — حدد النتيجة يدوياً"
                )
                no_sir_cols = st.columns(min(len(ocr_detected_no_sir), 3))
                for idx_d, drug_no_sir in enumerate(ocr_detected_no_sir):
                    col_d = no_sir_cols[idx_d % 3]
                    assign = col_d.selectbox(
                        f"⚠️ {drug_no_sir}",
                        ["—", "S", "I", "R"],
                        key=f"no_sir_{drug_no_sir}_{file_hash[:8]}",
                        help=f"OCR وجد '{drug_no_sir}' في النص — حدد النتيجة أو اتركها"
                    )
                    if assign != "—":
                        if drug_no_sir not in ocr_drugs:
                            ocr_drugs.append(drug_no_sir)
                        ocr_sir_map[drug_no_sir] = assign
                st.divider()

            # ── Manually-added drugs are persisted per-file in session state so they
            # render INSIDE the same list below (not in a separate section). The
            # add-control itself is placed AFTER the list for a natural top-down flow.
            _manual_key = f"manual_added_{file_hash[:8]}"
            if _manual_key not in st.session_state:
                st.session_state[_manual_key] = []
            _manual_names = [d for d in st.session_state[_manual_key]
                             if d not in ocr_drugs]

            # ترتيب موحّد: أدوية OCR أولاً (بترتيب اكتشافها) ثم المُضافة يدوياً — كلها
            # في نفس القائمة وبنفس الشكل، مع بادج ➕ للتمييز فقط.
            unified_drugs = ocr_drugs + [d for d in _manual_names if d not in ocr_drugs]
            _manual_set   = set(_manual_names)

            edited_sir: Dict[str, str] = {}

            # ── Deleted drugs (persisted per file) ───────────────────────────
            _del_key = f"deleted_drugs_{file_hash[:8]}"
            if _del_key not in st.session_state:
                st.session_state[_del_key] = set()

            if unified_drugs:
                st.markdown(
                    "<small style='color:#555'>🔍 من OCR &nbsp;·&nbsp; "
                    "<span style='color:#1a6b3a'>➕ = مُضاف يدوياً</span> &nbsp;·&nbsp; "
                    "اضغط ❌ لحذف مضاد:</small>",
                    unsafe_allow_html=True)
                label_icons = {"S": "🟢", "I": "🟡", "R": "🔴"}
                for i in range(0, len(unified_drugs), 3):
                    row_drugs = unified_drugs[i: i + 3]
                    row_cols  = st.columns(3)
                    for col, drug in zip(row_cols, row_drugs):
                        _is_manual = drug in _manual_set
                        # زر استعادة لو الدواء محذوف
                        if drug in st.session_state[_del_key]:
                            if col.button(f"↩️ {drug}", key=f"restore_{drug}_{file_hash[:8]}",
                                          help="استعادة المضاد"):
                                st.session_state[_del_key].discard(drug)
                                st.rerun()
                            continue
                        # القيمة الحالية: للـ OCR من ocr_sir_map، للمُضاف يدوياً افتراضي S
                        _default = ocr_sir_map[drug] if drug in ocr_sir_map else "S"
                        cur = st.session_state.sir_map_edited.get(drug, _default)
                        if cur not in sir_options:
                            cur = "S"
                        _badge = "➕ " if _is_manual else ""
                        _name_color = "#1a6b3a" if _is_manual else "inherit"
                        _c1, _c2, _c3 = col.columns([4, 3, 1])
                        _c1.markdown(
                            f"<small style='color:{_name_color}'>{label_icons.get(cur,'')} "
                            f"{_badge}**{drug}**</small>",
                            unsafe_allow_html=True)
                        new_val = _c2.selectbox(
                            "##",
                            options=sir_options,
                            index=sir_options.index(cur),
                            key=f"sir_{drug}_{file_hash[:8]}",
                            label_visibility="collapsed"
                        )
                        if _c3.button("❌", key=f"del_{drug}_{file_hash[:8]}",
                                      help=f"حذف {drug}"):
                            st.session_state[_del_key].add(drug)
                            st.rerun()
                        edited_sir[drug] = new_val

            # ── Add-a-drug control — DIRECTLY BELOW the list, so a newly chosen drug
            # appears at the bottom of the SAME list above (no separate section, no
            # jumping down). Searchable single-select = fast, typo-free entry.
            _already = set(ocr_drugs) | set(_manual_names) | set(ocr_detected_no_sir)
            _add_options = [d for d in all_known if d not in _already]
            _add_col1, _add_col2 = st.columns([5, 2])
            _pick = _add_col1.selectbox(
                "➕ أضف مضاداً فاته الـ OCR",
                options=["— اختر مضاداً —"] + _add_options,
                index=0,
                key=f"add_pick_{file_hash[:8]}",
                help="ابدأ بكتابة اسم المضاد للبحث السريع؛ سيظهر فوراً أسفل نفس القائمة أعلاه",
            )
            _add_sir = _add_col2.selectbox(
                "النتيجة",
                options=sir_options,
                index=0,
                key=f"add_sir_{file_hash[:8]}",
                label_visibility="visible",
            )
            if _add_col1.button("➕ أضِف إلى القائمة", key=f"add_btn_{file_hash[:8]}",
                                use_container_width=True):
                if _pick and _pick != "— اختر مضاداً —":
                    if _pick not in st.session_state[_manual_key]:
                        st.session_state[_manual_key].append(_pick)
                    # seed its S/I/R so it renders with the chosen value immediately
                    st.session_state.sir_map_edited[_pick] = _add_sir
                    st.session_state[_del_key].discard(_pick)
                    st.rerun()

            # Apply deletions
            _deleted = st.session_state.get(_del_key, set())
            edited_sir = {d: v for d, v in edited_sir.items() if d not in _deleted}
            st.session_state.sir_map_edited = edited_sir

            # sir_map = كل الأدوية بعد الحذف
            sir_map = dict(edited_sir)

            # final_drugs = كل الأدوية التي أُدخلت نتائجها
            final_drugs = list(sir_map.keys())

            # ── ملخص سريع ─────────────────────────────────────────────────
            if sir_map:
                s_count = sum(1 for v in sir_map.values() if v == "S")
                i_count = sum(1 for v in sir_map.values() if v == "I")
                r_count = sum(1 for v in sir_map.values() if v == "R")
                st.caption(
                    f"📊 إجمالي: {len(sir_map)} مضاد &nbsp;|&nbsp; "
                    f"🟢 Sensitive: {s_count} &nbsp;|&nbsp; "
                    f"🟡 Intermediate: {i_count} &nbsp;|&nbsp; "
                    f"🔴 Resistant: {r_count}"
                )

        # ══════════════════════════════════════════════════════════════
        # WIZARD GATE ②→③ : after AST entry, advance to Results
        # ══════════════════════════════════════════════════════════════
        # Step 2 (AST): show "back to patient" + "view results" and STOP before
        # any result renders. Step 3 (results): show "back to editing" and let the
        # analysis run. All inputs persist in session_state across steps.
        if not st.session_state.get("show_results", False):
            st.divider()
            if not final_drugs:
                st.info("➕ أدخل نتائج الحساسية (AST) بالأعلى، ثم اضغط لعرض التحليل.")
            _go = st.button(
                "عرض التحليل والتوصيات والتقرير ▶️",
                type="primary", use_container_width=True,
                disabled=not final_drugs,
                key="wizard_go_results",
            )
            if _go:
                st.session_state.show_results = True
                st.rerun()
            st.caption("💡 يمكنك التنقّل بين الخطوات من القائمة الجانبية في أي وقت.")
            st.stop()
        else:
            st.caption("📄 النتائج والتقرير بالأسفل — للتعديل استخدم القائمة الجانبية.")
            st.divider()

        # ── تحليل المضادات ────────────────────────────────────────────────────
        # النقطة ٤: analyze_antibiotics يُستدعى مباشرة بقيم اللحظة
        # فأي تغيير في أي widget يُعيد تشغيل Streamlit → تحديث فوري
        allowed, warned, banned, preg_warn_items, interactions_alerts = analyze_antibiotics(
            final_drugs=final_drugs,
            organism_type=organism_type,
            culture_type=culture_type,
            age=age, sex=sex,
            is_renal=is_renal, cl_cr=cl_cr,
            is_preg=is_preg, is_hepatic=is_hepatic,
            current_meds=current_meds,
            sir_map=sir_map,
        )

        if interactions_alerts:
            st.warning("⚡ Interactions / Hepatic Warnings")
            for alert in interactions_alerts:
                st.write(alert)

        # ── MDR / XDR / PDR Classification ───────────────────────────────────
        mdr_result  = classify_mdr(organism_type, sir_map)
        esbl_result = predict_esbl(organism_type, sir_map)

        # ── Results Dashboard (at-a-glance summary card) ─────────────────────
        # A compact, colour-coded row of the key headline findings, shown BEFORE
        # the detailed sections so the user sees the bottom line immediately.
        # Display-only — it reads results already computed, changes no logic.
        if sir_map:
            _dash_pheno = detect_resistance_phenotypes(organism_type, sir_map)
            _dash_qc    = run_ast_qc(organism_type, sir_map)
            _dash_qa    = compute_qa_confidence(_dash_qc, sir_map, organism_type)
            _dash_patho = st.session_state.get("patho_result") or {}

            _mdr_lvl = mdr_result.get("level")
            _esbl_p  = esbl_result.get("probability")
            _esbl_c  = esbl_result.get("confidence", 0)
            _has_carbapenemase = any("carbapenem" in str(p.get("phenotype", "")).lower()
                                     or "CRE" in str(p.get("phenotype", ""))
                                     or "CRAB" in str(p.get("phenotype", ""))
                                     or "CRPA" in str(p.get("phenotype", ""))
                                     for p in _dash_pheno)
            _is_mrsa_ph = any("MRSA" in str(p.get("phenotype", "")).upper() for p in _dash_pheno)
            _is_vre_ph  = any("VRE" in str(p.get("phenotype", "")).upper() for p in _dash_pheno)

            st.markdown("#### 📋 Summary")
            _d = st.columns(4)
            # Susceptible options
            _d[0].metric("🟢 Options", f"{len(allowed)}",
                         help="عدد الخيارات الحسّاسة المناسبة")
            # QA
            _d[1].metric("QA", _dash_qa.get("label", "—"),
                         help="جودة نتائج الحساسية (AST QC)")
            # MDR level
            _d[2].metric("Resistance",
                         _mdr_lvl if _mdr_lvl else "None",
                         help="تصنيف المقاومة المتعددة")
            # Pathogenicity
            if _dash_patho.get("score") is not None:
                _d[3].metric("Pathogenicity", f"{_dash_patho.get('score')}%",
                             help="احتمالية أن العينة عدوى حقيقية")
            else:
                _d[3].metric("Pathogenicity", "—",
                             help="شغّل تقييم الإمراضية للحصول على النتيجة")

            # Second row of flags — only shown when relevant, as coloured chips
            _flags = []
            if _esbl_p and _esbl_p not in ("low", None):
                _flags.append(("ESBL", f"{_esbl_p} ({_esbl_c}%)", "#b7770d"))
            if _has_carbapenemase:
                _flags.append(("Carbapenemase", "possible", "#922b21"))
            if _is_mrsa_ph:
                _flags.append(("MRSA", "positive", "#922b21"))
            if _is_vre_ph:
                _flags.append(("VRE", "positive", "#922b21"))
            if _mdr_lvl in ("XDR", "PDR"):
                _flags.append((_mdr_lvl, "⚠️", "#922b21"))
            if _flags:
                _chips = " ".join(
                    f"<span style='background:{c};color:#fff;padding:2px 10px;"
                    f"border-radius:10px;font-size:0.8em;margin-right:6px;white-space:nowrap'>"
                    f"{name}: {val}</span>"
                    for name, val, c in _flags
                )
                st.markdown(f"<div style='margin:4px 0 2px'>{_chips}</div>",
                            unsafe_allow_html=True)
            st.divider()

        if mdr_result["level"] or (esbl_result.get("probability") and esbl_result["probability"] not in ("low", None)):
            with st.expander("🧬 Resistance Classification", expanded=True):

                # MDR/XDR/PDR
                if mdr_result["level"]:
                    info = MDR_INFO[mdr_result["level"]]
                    _rc  = mdr_result["resistant_count"]
                    _rt  = mdr_result["total_tested"]
                    _cats = ", ".join(mdr_result["resistant_categories"])
                    _gram = mdr_result.get("gram", "")
                    _msg = (f"{info['icon']} **{info['label']}**  \n"
                            f"{info['detail']}  \n"
                            f"Resistant categories ({_rc}/{_rt}, Gram-{_gram}): {_cats}  \n"
                            f"🔹 {info['action']}")
                    if mdr_result["level"] == "MDR":
                        st.warning(_msg)
                    else:
                        st.error(_msg)
                    # Reliability warnings
                    for _w in mdr_result.get("warnings", []):
                        st.caption(_w)

                # ESBL Predictor
                prob = esbl_result.get("probability")
                _conf = esbl_result.get("confidence", 0)
                _mech = esbl_result.get("mechanism", "")
                if prob == "carbapenemase":
                    _em = (f"[!!] {_mech or 'Possible Carbapenemase (KPC/MBL/OXA)'} "
                           f"(confidence {_conf}%)\n"
                           + esbl_result["detail"] + "  \n🔹 " + esbl_result["action"])
                    st.error(_em)
                elif prob == "ampc":
                    _em = (f"[!] Possible AmpC β-Lactamase (confidence {_conf}%)\n"
                           + esbl_result["detail"] + "  \n🔹 " + esbl_result["action"])
                    st.error(_em)
                elif prob == "high":
                    _em = (f"[!] High Probability ESBL Producer (confidence {_conf}%)\n"
                           + esbl_result["detail"] + "  \n🔹 " + esbl_result["action"])
                    st.error(_em)
                elif prob == "moderate":
                    _em = (f"[~] ESBL Confirmation Recommended (confidence {_conf}%)\n"
                           + esbl_result["detail"] + "  \n🔹 " + esbl_result["action"])
                    st.warning(_em)

        # ── Resistance Phenotype Engine ──────────────────────────────────
        phenotypes = detect_resistance_phenotypes(organism_type, sir_map)
        if phenotypes:
            with st.expander("🦠 Resistance Phenotypes Detected", expanded=True):
                for ph in phenotypes:
                    isolation_tag = "  🚨 **عزل فوري مطلوب**" if ph["isolation"] else ""
                    msg = (f"{ph['icon']} **{ph['label']}**{isolation_tag}  \n"
                           f"{ph['detail']}  \n"
                           f"🔹 {ph['action']}")
                    if ph["isolation"]:
                        st.error(msg)
                    else:
                        st.warning(msg)
                    if ph.get("matched_markers"):
                        st.caption(f"Evidence: {', '.join(ph['matched_markers'])}")

        # ── AST Quality Control Checker ───────────────────────────────────
        if sir_map:
            qc_issues = run_ast_qc(organism_type, sir_map)
            qa_confidence = compute_qa_confidence(qc_issues, sir_map, organism_type)

            with st.expander(
                f"{qa_confidence['icon']} AST Quality Control — "
                f"{qa_confidence['level']} ({qa_confidence['score']}/100)"
                + (f" — {len(qc_issues)} Issue(s)" if qc_issues else ""),
                expanded=bool(qc_issues)
            ):
                st.caption("تحقق تلقائي من منطقية نتائج المزرعة وفق EUCAST Expert Rules")

                # Confidence score summary
                st.markdown(
                    f"<div style='padding:2mm 3mm;border-radius:2mm;"
                    f"background:{qa_confidence['color']}15;"
                    f"border:1px solid {qa_confidence['color']};margin-bottom:2mm'>"
                    f"<b style='color:{qa_confidence['color']}'>"
                    f"{qa_confidence['icon']} {qa_confidence['level']} — {qa_confidence['score']}/100</b>"
                    f"<ul style='margin:1mm 0 0 4mm;padding:0;font-size:0.85em'>"
                    + "".join(f"<li>{r}</li>" for r in qa_confidence["reasons"])
                    + "</ul></div>",
                    unsafe_allow_html=True,
                )

                if qc_issues:
                    for issue in qc_issues:
                        icon = "❌" if issue["severity"] == "error" else "⚠️"
                        if issue["severity"] == "error":
                            st.error(f"{icon} **[{issue['id']}]** {issue['message']}  \n✏️ {issue['fix']}")
                        else:
                            st.warning(f"{icon} **[{issue['id']}]** {issue['message']}  \n✏️ {issue['fix']}")
                else:
                    st.success("✅ All AST consistency checks passed. No issues detected.")

                # QA Report PDF — للميكروبيولوجي فقط، منفصل عن تقرير الطبيب
                st.divider()
                st.caption("📄 تقرير الجودة الداخلي (للميكروبيولوجي فقط — لا يُرسل للطبيب)")
                if WEASYPRINT_AVAILABLE:
                    _qa_pdf_bytes = generate_qa_report_pdf(
                        organism=organism_type,
                        specimen=culture_type,
                        sir_map=sir_map,
                        qc_issues=qc_issues,
                        confidence=qa_confidence,
                        microbiologist=st.session_state.get("microbiologist", ""),
                        patient_ref=st.session_state.get("patient_name_final", "") or "",
                    )
                    if _qa_pdf_bytes:
                        st.download_button(
                            "⬇️ Download AST-QA Report (PDF)",
                            data=_qa_pdf_bytes,
                            file_name=f"AST-QA-Report-{datetime.now().strftime('%Y%m%d-%H%M')}.pdf",
                            mime="application/pdf",
                            key="qa_report_pdf_dl",
                        )
                    else:
                        st.caption("⚠️ تعذر إنشاء ملف PDF لتقرير الجودة.")
                else:
                    st.caption("⚠️ WeasyPrint غير متاح — لا يمكن إنشاء PDF.")

        # ── Smart Antibiotic Ranking ──────────────────────────────────────
        if allowed:
            # FIXED: removed dir() check, use phenotypes directly
            ranked = rank_sensitive_antibiotics(
                allowed, culture_type, organism_type, sir_map,
                phenotypes
            )
            with st.expander("🏆 Smart Antibiotic Ranking", expanded=False):
                st.caption("مرتب حسب: نتيجة المزرعة + WHO AWaRe + طريق الإعطاء + ملاءمة العينة")
                _aic = {"Access": "🟢", "Watch": "🟡", "Reserve": "🔴"}
                for i, item in enumerate(ranked[:8], 1):
                    sir_badge  = item.get("_sir", "—")
                    aware      = item.get("aware", "")
                    route      = "💊 Oral" if item.get("high_po") else "💉 IV/IM"
                    score      = item.get("_score", 0)
                    aware_icon = _aic.get(aware, "⚪")
                    st.markdown(
                        f"**{i}.** {item['name']} &nbsp; "
                        f"`{sir_badge}` &nbsp; {aware_icon} {aware} &nbsp; {route} &nbsp;"
                        f"<small style='color:gray'>score:{score}</small>",
                        unsafe_allow_html=True)

        # ── Infection Syndrome Module ─────────────────────────────────────
        syndrome_info = get_infection_syndrome(
            specimen=culture_type,
            organism=organism_type,
            age=age,
            is_preg=is_preg,
            is_cath=False,
        )
        if syndrome_info:
            with st.expander(f"🏥 Infection Syndrome: {syndrome_info['syndrome']}", expanded=False):
                s1, s2 = st.columns(2)
                with s1:
                    st.markdown(f"**النوع:** {syndrome_info['sub_type']}")
                    st.markdown(f"**مدة العلاج:** {syndrome_info['duration']}")
                    st.markdown(f"**الخط الأول (guidelines):** {', '.join(syndrome_info['first_choice'])}")
                with s2:
                    st.info(f"**Escalation:** {syndrome_info['escalation']}")
                    st.caption(f"📌 Culture threshold: {syndrome_info['threshold']}")

        if is_preg and preg_warn_items:
            st.markdown("---")
            st.markdown("### 🤰 Pregnancy — Use With Caution")
            st.info(
                "الأدوية التالية **ليست محظورة تلقائيًا** لكنها تحتاج تقييمًا طبيًا دقيقًا.\n\n"
                "**القرار النهائي للطبيب المعالج حصراً.**"
            )
            for item in preg_warn_items:
                with st.expander(f"⚠️ {item['name']} — تفاصيل التحذير"):
                    for line in (item.get("preg_note") or "").splitlines():
                        st.write(line)

        if banned:
            with st.expander("🚫 Contraindicated / Ineffective", expanded=True):
                cat_labels = {
                    "resistant": "مقاوم في المزرعة",
                    "renal":     "قصور كلوي",
                    "pregnancy": "ممنوع في الحمل",
                    "child":     "غير مناسب للعمر",
                    "organism":  "غير فعال للجرثومة",
                    "other":     "موانع أخرى",
                }
                for item in banned:
                    st.error(
                        f"💊 {item['name']}  [{cat_labels.get(item['category'],'')}]\n"
                        f"{item['reason_short']}"
                    )

        if warned:
            with st.expander("🟡 Warnings / Dose Adjustment Required", expanded=True):
                _interm = [w for w in warned if w.get("warning_reason") == "intermediate_culture"]
                _others = [w for w in warned if w.get("warning_reason") != "intermediate_culture"]
                if _interm:
                    _names = ", ".join(
                        w['name'] + (f" [{sir_map[w['name']]}]" if sir_map and w['name'] in sir_map else "")
                        for w in _interm
                    )
                    st.warning(
                        f"⚠ Intermediate (I) on culture — use only if no better option: **{_names}**"
                    )
                for item in _others:
                    sir_tag = (f" [{sir_map[item['name']]}]"
                               if sir_map and item['name'] in sir_map else "")
                    if item.get("warning_reason") == "esbl_bli_uti_only":
                        st.warning(
                            f"**{item['name']}{sir_tag}** — {item.get('esbl_note','')}"
                        )
                    else:
                        st.warning(f"**{item['name']}{sir_tag}** — {item.get('renal_note','')}")

        if allowed:
            st.success(f"🟢 {len(allowed)} Recommended Option(s)")
            for item in allowed:
                sir_badge = (f" [{sir_map[item['name']]}]"
                             if sir_map and item['name'] in sir_map else "")
                preg_flag = " 🤰" if (is_preg and item.get("preg_status") == "Warn") else ""
                aware_val = item.get("aware", "Unknown")
                color_val = AWARE_COLORS.get(aware_val, aware_val)
                with st.expander(
                    f"{item['name']}{sir_badge}{preg_flag} — {color_val}", expanded=False
                ):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Class:** {item.get('class','-')}")
                    c2.write(f"**Route:** {get_route_label(item)}")
                    st.write(f"**Note:** {item.get('note','-')}")
                    spec_note = (item.get("specimen_notes") or {}).get(culture_type, "")
                    if spec_note:
                        st.info(f"**{culture_type} Note:** {spec_note}")
                    if is_renal:
                        st.caption(f"Renal: {item.get('renal_note','-')}")
                    if is_preg and item.get("preg_status") == "Warn":
                        pn = (item.get("preg_note") or "").splitlines()
                        if pn:
                            st.caption(f"🤰 {pn[0]}")
        elif not banned and not warned:
            st.info("اختر المضادات الحساسة أو المناسبة من القائمة أعلاه.")

        # ── التقرير والصورة ──────────────────────────────────────────────────
        if final_drugs:
            st.divider()

            # مصدر الترتيب الموحّد — يُحسب هنا لضمان توفره (كان يُعرّف داخل كتلة
            # أخرى مشروطة → NameError محتمل)، ونفس منطق rank_sensitive_antibiotics.
            ranked = rank_sensitive_antibiotics(
                allowed, culture_type, organism_type, sir_map, phenotypes
            )

            # بناء قوائم الصورة
            reserve_names = uniq_keep_order([
                item['name'] for item in (allowed + warned)
                if item.get("aware") == "Reserve"
            ])
            # مصدر ترتيب واحد موحّد: نفس ترتيب rank_sensitive_antibiotics
            # (الحساسية أولاً ثم العينة ثم AWaRe ثم الطريق) — نستبعد الـ Reserve
            # من قائمة الـ PREFERRED فقط (تظهر منفصلة كـ Reserve).
            preferred_sorted = [
                item for item in ranked if item.get("aware") != "Reserve"
            ]
            preferred_names = [item['name'] for item in preferred_sorted]
            # للصورة: نضيف badge [A] أو [W] بجانب الاسم
            preferred_with_badge = [
                (f"{item['name']} [A]" if item.get('aware') == 'Access'
                 else f"{item['name']} [W]" if item.get('aware') == 'Watch'
                 else item['name'])
                for item in preferred_sorted
            ]
            # النقطة ٣: use_caution يشمل warned + preg_warn
            preg_caution_names = [item['name'] for item in preg_warn_items]
            use_caution_names  = uniq_keep_order(
                [item['name'] for item in warned if item['name'] not in reserve_names]
                + preg_caution_names
            )
            # Build banned names WITH reason tag for the image (same logic as PDF)
            _esbl_prob_img    = esbl_result.get("probability","low") if esbl_result else "low"
            _img_esbl_like    = _esbl_prob_img in ("high","ampc")
            _img_carbapenemase= _esbl_prob_img == "carbapenemase"
            _img_mrsa         = any("MRSA" in str(p.get("phenotype","")).upper() for p in (phenotypes or [])) \
                                or "mrsa" in organism_type.lower()
            def _img_ban_tag(bd):
                cat = bd.get("category",""); nm = bd.get("name","")
                _s = sir_map.get(nm,"")
                _cl = (ABX_GUIDELINES.get(nm,{}).get("class","") or "").lower()
                if cat == "resistant" or _s == "R":         return "(R)"
                if cat == "pregnancy":                       return "(Pregnancy)"
                if cat in ("child","pediatric"):             return "(Pediatric)"
                if cat == "renal":                           return "(Renal)"
                if cat == "organism":
                    _bl = any(k in _cl for k in ("penicillin","cephalosporin","carbapenem"))
                    if _img_mrsa and _bl:          return "(MRSA)"
                    if _img_carbapenemase and _bl: return "(Carbapenemase)"
                    if _img_esbl_like and _bl:     return "(ESBL)"
                    return "(Intrinsic R)"
                return "(Avoid)"
            _seen_ban = set()
            banned_names = []
            for item in banned:
                nm = item.get("name","")
                if nm and nm not in _seen_ban:
                    _seen_ban.add(nm)
                    banned_names.append(f"{nm} {_img_ban_tag(item)}")
            org_profile    = ORGANISM_PROFILE.get(organism_type, {})
            # الـ first-line في ORGANISM_PROFILE قائمة عامة للميكروب وغير مفلترة
            # بنتيجة المزرعة — قد تحتوي دواءً مقاوماً هنا. نُبقي فقط ما اجتاز فلتر
            # الحساسية (موجود في allowed)، وبنفس ترتيب rank_sensitive_antibiotics.
            _profile_fl    = org_profile.get("first_line", []) or []
            _allowed_names = {it.get("name", "") for it in allowed}
            _ranked_names  = [it.get("name", "") for it in ranked]
            first_line_l   = [
                d for d in _ranked_names
                if d in _profile_fl and d in _allowed_names
            ]

            notes: List[str] = []
            if is_renal:
                notes.append(f"Renal impairment: CrCl {cl_cr:.1f} ml/min — dose adjustment required.")
            if is_preg:
                notes.append("Pregnancy: use with caution; consult specialist.")
            if age < 18:
                notes.append("Pediatric age: verify age-specific suitability.")
            # ── Add note if no preferred options (Access/Watch) ────────────
            if not preferred_with_badge:
                notes.append("No clear Access/Watch oral options — see Caution/Reserve columns.")
            if banned:
                notes.append(f"{len(banned)} contraindicated / ineffective antibiotics.")
            if warned:
                notes.append(f"{len(warned)} antibiotics need caution or dose adjustment.")
            notes.append("Treatment guided by severity and local resistance patterns.")
            notes.append("De-escalate based on culture & sensitivity.")

            # Ensure syndrome_info is always defined for engines
            # FIXED: removed dir() check and use syndrome_info directly
            # syndrome_info is already defined above

            # ════════════════════════════════════════════════════════════
            # CLINICAL ENGINES UI — v4.0
            # ════════════════════════════════════════════════════════════
            st.divider()
            st.markdown("### 🔬 Advanced Analysis")
            st.caption("أدوات إضافية اختيارية — مدة العلاج، العلاج التوليفي، "
                       "التحويل من الوريد للفم، جرعات الكبد، وخفض التصعيد. "
                       "اضغط أي قسم لفتحه.")

            # ── ① Treatment Duration ─────────────────────────────────
            with st.expander("⏱️ Treatment Duration", expanded=False):
                st.caption("Evidence-based duration — IDSA AMR 2025 | Sanford 2025")

                # ── Auto-suggest severity from patient factors ─────────────
                _auto = suggest_severity(
                    specimen=culture_type, age=age, sex=sex,
                    is_preg=is_preg, is_renal=is_renal, cl_cr=cl_cr,
                    host_factors=st.session_state.get("patho_host_factors", []),
                    symptoms=st.session_state.get("patho_symptoms", []),
                )
                _suggested   = _auto["suggested"]
                _auto_reasons = _auto["reasons"]

                # Only auto-set on first load or when user hasn't overridden
                _sev_key = f"severity_manual_{culture_type}_{organism_type}"
                if not st.session_state.get(_sev_key):
                    st.session_state.severity_level = _suggested

                # Show auto-suggestion chip
                _chip_color = {"mild": "#f39c12", "moderate": "#e67e22",
                               "severe": "#c0392b"}[_suggested]
                st.markdown(
                    "**🤖 Auto-suggested:** "
                    f"<span style='background:{_chip_color};color:white;"
                    "padding:1px 8px;border-radius:8px;font-size:0.85em'>"
                    f"{_suggested.upper()}</span> "
                    f"<small style='color:gray'>— {_auto_reasons[0] if _auto_reasons else ''}</small>",
                    unsafe_allow_html=True,
                )

                _sev = st.selectbox(
                    "Case Severity (يمكنك التعديل يدوياً)",
                    ["mild", "moderate", "severe"],
                    index=["mild","moderate","severe"].index(
                        st.session_state.get("severity_level","moderate")),
                    format_func=lambda x:{"mild":"🟡 Mild","moderate":"🟠 Moderate","severe":"🔴 Severe"}[x],
                    key="sev_sel_ui")

                # Mark as manually overridden if changed
                if _sev != _suggested:
                    st.session_state[_sev_key] = True
                    if _sev != st.session_state.get("severity_level"):
                        st.caption(f"ℹ️ تم تعديل الشدة يدوياً من {_suggested} → {_sev}")
                else:
                    st.session_state[_sev_key] = False

                st.session_state.severity_level = _sev
                _syn_lbl = syndrome_info["syndrome"] if syndrome_info else ""
                _dur = get_treatment_duration(
                    specimen=culture_type, organism=organism_type,
                    syndrome=_syn_lbl, age=age, sex=sex,
                    is_renal=is_renal, phenotypes=phenotypes, severity=_sev)
                _d1, _d2, _d3 = st.columns(3)
                _d1.metric("Standard", f"{_dur.get('standard_days',_dur.get('standard','?'))}d")
                _d2.metric("Range", f"{_dur.get('min_days','?')}–{_dur.get('max_days','?')}d")
                _d3.metric("IV / PO", f"IV:{_dur.get('iv_days',0)}d · PO:{_dur.get('po_days',0)}d")
                st.info(f"📋 {_dur.get('notes','')}")
                if _dur.get("follow_up_culture"):
                    st.warning("🔄 Follow-up culture recommended after treatment completion")
                st.caption(f"📚 {_dur.get('ref','')}")

            # ── ② Combination Therapy (auto if MDR phenotype) ────────
            _combos = get_combination_therapy(phenotypes)
            if _combos:
                with st.expander(f"🔬 Combination Therapy ({len(_combos)} phenotype)", expanded=True):
                    st.caption("MDR/XDR combination therapy — IDSA AMR 2025")
                    for _cs in _combos:
                        _pd = _cs["data"]
                        _urg = _pd["urgency"]
                        (st.error if _urg=="CRITICAL" else st.warning)(f"**{_urg}** — {_pd['title']}")
                        for _op in _pd["options"]:
                            _avoid = "AVOID" in _op.get("evidence","") or "AVOID" in _op["combo"].upper()
                            if _avoid:
                                st.error(f"🚫 **{_op['combo']}** | {_op.get('caution','')}")
                            else:
                                with st.container(border=True):
                                    _ca, _cb = st.columns([3,1])
                                    with _ca:
                                        st.markdown(f"**{_op['combo']}** — {_op['evidence']}")
                                        st.caption(_op["indication"])
                                        if _op.get("caution"): st.warning(_op["caution"])
                                    with _cb:
                                        st.caption(_op["ref"])

            # ── ③ IV → PO Switch ──────────────────────────────────────
            with st.expander("💊 IV → PO Switch Evaluation", expanded=False):
                st.caption("OPAT switch criteria — IDSA 2019 | BNF 2025")
                _sw1, _sw2 = st.columns(2)
                with _sw1:
                    _sw_drug = st.selectbox("Current IV drug",
                        [""] + [d["name"] for d in allowed], key="sw_drug_sel")
                    _sw_days = st.number_input("Days on IV", min_value=0, max_value=30,
                        value=st.session_state.get("days_on_iv",3), key="sw_days_num")
                    st.session_state.days_on_iv = _sw_days
                with _sw2:
                    _sw_i = st.checkbox("Clinical improvement documented",
                        value=st.session_state.get("clinical_improving_48h",True), key="sw_i_chk")
                    _sw_o = st.checkbox("Tolerating oral medications",
                        value=st.session_state.get("tolerating_oral",True), key="sw_o_chk")
                    _sw_b = st.checkbox("No active bacteremia",
                        value=st.session_state.get("bacteremia_resolved",True), key="sw_b_chk")
                    st.session_state.clinical_improving_48h = _sw_i
                    st.session_state.tolerating_oral        = _sw_o
                    st.session_state.bacteremia_resolved    = _sw_b
                if _sw_drug:
                    _swr = evaluate_iv_po_switch(
                        drug_name=_sw_drug,
                        syndrome=syndrome_info["syndrome"] if syndrome_info else "",
                        clinical_improving=_sw_i, tolerating_oral=_sw_o,
                        bacteremia_resolved=_sw_b, days_on_iv=_sw_days)
                    (st.success if _swr["can_switch"] else st.warning)(_swr["verdict"])
                    _sc1, _sc2 = st.columns(2)
                    with _sc1:
                        st.markdown("**✅ Supporting factors:**")
                        for _s in _swr["supporters"]: st.write(f"• {_s}")
                    with _sc2:
                        st.markdown("**⚠️ Blocking factors:**")
                        for _b in _swr["blockers"]: st.write(f"• {_b}")
                    st.caption(f"📚 {_swr['ref']}")
                else:
                    st.info("Select the current IV drug to evaluate switch criteria")

            # ── ④ Hepatic Dosing — Child-Pugh ─────────────────────────
            if is_hepatic:
                with st.expander("🟡 Hepatic Dosing — Child-Pugh", expanded=True):
                    st.caption("Dose adjustments in hepatic impairment — BNF 2025 | Lexicomp 2025")
                    _cp = st.selectbox("Child-Pugh Class", ["A","B","C"],
                        index=["A","B","C"].index(st.session_state.get("child_pugh_class","A")),
                        format_func=lambda x:{"A":"A — Mild (5-6pts)","B":"B — Moderate (7-9pts)","C":"C — Severe (10-15pts)"}[x],
                        key="cp_sel")
                    st.session_state.child_pugh_class = _cp
                    _hr = get_hepatic_recommendations(allowed, _cp)
                    _act = [r for r in _hr if r["requires_action"]]
                    _nrm = [r for r in _hr if not r["requires_action"]]
                    if _act:
                        st.markdown("**⚠️ Adjustments required:**")
                        for _r in _act:
                            (st.error if "Avoid" in _r["level"] else st.warning)(
                                f"{'❌' if 'Avoid' in _r['level'] else '⚠️'} "
                                f"**{_r['name']}**: {_r['recommendation']} — _{_r['note']}_")
                    if _nrm:
                        with st.expander(f"✅ {len(_nrm)} drugs: no hepatic adjustment needed"):
                            for _r in _nrm: st.caption(f"✅ {_r['name']}: {_r['recommendation']}")
                    if not _hr:
                        st.success("✅ No hepatic dose adjustments needed for current recommendations")
                    st.caption("📚 BNF 2025 | Lexicomp 2025 | UpToDate 2025")

            # ── ⑤ De-escalation Advisor ───────────────────────────────
            with st.expander("📉 De-escalation Advisor", expanded=False):
                st.caption("Antibiotic stewardship — WHO AWaRe 2025 | IDSA Stewardship 2025")
                _de1, _de2 = st.columns(2)
                with _de1:
                    _de_h = st.number_input("Hours on current therapy",
                        min_value=0, max_value=336, step=12,
                        value=st.session_state.get("hours_on_treatment",72), key="de_h_num")
                    st.session_state.hours_on_treatment = _de_h
                with _de2:
                    _de_i = st.checkbox("Clinical improvement documented",
                        value=st.session_state.get("de_clinical_improving",True), key="de_i_chk")
                    st.session_state.de_clinical_improving = _de_i
                _der = evaluate_deescalation(
                    allowed=allowed, phenotypes=phenotypes,
                    hours_on_treatment=_de_h, clinical_improving=_de_i)
                if _der["can_deescalate"]: st.success("✅ De-escalation recommended")
                elif _de_h < 48: st.info("ℹ️ Complete 48h course before reassessment")
                else: st.warning("⚠️ Review required before de-escalation")
                for _rec in _der["recommendations"]: st.write(_rec)
                st.caption(f"📚 {_der['ref']}")

            st.divider()

            # ── Commercial Names Toggle ────────────────────────────────────────
            show_commercial = st.checkbox(
                "📋 إضافة الأسماء التجارية (Commercial Names) في التقرير؟",
                value=st.session_state.get("show_commercial_names", False),
                key="show_commercial_chk",
                help="يضيف أسماء العلامات التجارية بجانب كل مضاد حيوي في ملف TXT فقط"
            )
            st.session_state.show_commercial_names = show_commercial
            if show_commercial and not COMMERCIAL_NAMES:
                st.warning("⚠️ ملف `commercial_names.txt` غير موجود في مجلد البرنامج.")
            elif show_commercial:
                st.caption(f"✅ {len(COMMERCIAL_NAMES)} دواء مسجّل في قاموس الأسماء التجارية")

            # ── التقرير النصي — cached to prevent lag on every keystroke ──────
            st.markdown("### 📋 التقرير السريري")

            _lab  = st.session_state.get("lab_name", "Orange Lab")
            _city = st.session_state.get("lab_city", "")
            _pt   = patient_name.strip() or "غير محدد"

            # Hash all inputs that affect the report. Must mirror every argument
            # passed to generate_report() below, or a changed value leaves a
            # stale report cached on screen.
            _patho = st.session_state.get("patho_result") or {}
            # Full pathogenicity signature — not just score: verdict and the
            # factor/recommendation lists change the report even when score is
            # unchanged.
            _patho_sig = (
                f"{_patho.get('score','')}"
                f":{_patho.get('verdict','')}"
                f":{len(_patho.get('factors_pos', []) or [])}"
                f":{len(_patho.get('factors_neg', []) or [])}"
                f":{hash(str(_patho.get('recommendations','')))}"
            )
            _allowed_sig = ",".join(d.get("name", "") for d in allowed)
            _warned_sig  = ",".join(d.get("name", "") for d in warned)
            _banned_sig  = ",".join(d.get("name", "") for d in banned)
            _inter_sig   = "|".join(sorted(interactions_alerts or []))
            _rpt_input_hash = hashlib.md5((
                f"{_pt}|{age}|{sex}|{weight}|{cl_cr}|{is_renal}|{is_preg}|{is_hepatic}"
                f"|{organism_type}|{culture_type}|{colony_count}|{date_in}"
                f"|{pus_cells_text}|{rbcs_text}|{str(sorted(sir_map.items()))}"
                f"|A:{_allowed_sig}|W:{_warned_sig}|B:{_banned_sig}|I:{_inter_sig}"
                f"|{show_commercial}|{_lab}|{_city}|{_patho_sig}"
            ).encode()).hexdigest()[:16]

            if st.session_state.get("_rpt_hash") != _rpt_input_hash:
                _new_report = generate_report(
                    patient_name=_pt,
                    age=age, sex=sex, weight=weight,
                    cl_cr=cl_cr, is_renal=is_renal,
                    is_preg=is_preg, is_hepatic=is_hepatic,
                    allowed=allowed, warned=warned, banned=banned,
                    preg_warn_items=preg_warn_items,
                    organism=organism_type, specimen=culture_type,
                    interactions=interactions_alerts, sir_map=sir_map,
                    colony_count=colony_count,
                    date_in=str(date_in),
                    pus_cells=pus_cells_text,
                    rbcs=rbcs_text,
                    lab_name=_lab,
                    lab_city=_city,
                    patho_assessment=st.session_state.get("patho_result"),
                    show_commercial_names=show_commercial,
                )
                st.session_state._rpt_text = _new_report
                st.session_state._rpt_hash = _rpt_input_hash

            auto_report = st.session_state.get("_rpt_text", "")

            # معاينة للقراءة فقط
            if auto_report:
                st.text_area(
                    "نص التقرير",
                    value=auto_report,
                    height=300,
                    disabled=True,
                    label_visibility="collapsed",
                    key=f"rpt_{_rpt_input_hash}"
                )
                st.download_button(
                    "📥 تنزيل التقرير (TXT)",
                    data=auto_report,
                    file_name=(f"CDSS_{organism_type.replace(' ','_')}_"
                               f"{_pt.replace(' ','_')[:12]}_"
                               f"{datetime.now().strftime('%Y%m%d_%H%M')}.txt"),
                    mime="text/plain",
                    use_container_width=True,
                    type="primary",
                )

            # ── PDF Report ────────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### 📄 PDF Clinical Report")

            # Language + options row
            _pdf_lang_col, _popt1, _popt2, _popt3 = st.columns([2,1,1,1])
            _pdf_lang  = _pdf_lang_col.radio(
                "Report Language",
                options=["ar", "en"],
                format_func=lambda x: "🌐 Arabic + English (Bilingual)" if x == "ar"
                                      else "🇬🇧 English Only",
                index=["ar","en"].index(st.session_state.get("pdf_lang","ar")),
                horizontal=True,
                key="pdf_lang_radio",
            )
            st.session_state.pdf_lang = _pdf_lang
            _pdf_combo = _popt1.checkbox("Combination",
                value=st.session_state.get("pdf_include_combo",True), key="pdf_cb_combo")
            _pdf_dur   = _popt2.checkbox("Duration",
                value=st.session_state.get("pdf_include_duration",True), key="pdf_cb_dur")
            _pdf_patho = _popt3.checkbox("Pathogenicity",
                value=st.session_state.get("pdf_include_patho",True), key="pdf_cb_patho")
            st.session_state.pdf_include_combo    = _pdf_combo
            st.session_state.pdf_include_duration = _pdf_dur
            st.session_state.pdf_include_patho    = _pdf_patho

            if WEASYPRINT_AVAILABLE:
                _cp_pdf  = st.session_state.get("child_pugh_class", "A")
                _sev_pdf = st.session_state.get("severity_level", "moderate")
                _lang_lbl = "English Only" if _pdf_lang == "en" else "Arabic + English"

                if st.button(f"🔄 Generate PDF ({_lang_lbl})", key="gen_pdf_btn",
                             use_container_width=True,
                             help="Click to generate report — takes a few seconds"):
                    _dur_for_pdf = get_treatment_duration(
                        specimen=culture_type, organism=organism_type,
                        syndrome=syndrome_info["syndrome"] if syndrome_info else "",
                        age=age, sex=sex, is_renal=is_renal,
                        phenotypes=phenotypes, severity=_sev_pdf,
                    ) if _pdf_dur else None
                    _combo_for_pdf = get_combination_therapy(phenotypes) if _pdf_combo else None
                    _hep_for_pdf   = (get_hepatic_recommendations(allowed, _cp_pdf)
                                      if is_hepatic else None)
                    with st.spinner("Generating PDF report..."):
                        try:
                            _new_pdf = generate_pdf_html_report(
                                patient_name         = _pt,
                                age=age, sex=sex, weight=weight,
                                cl_cr=cl_cr, is_renal=is_renal,
                                is_preg=is_preg, is_hepatic=is_hepatic,
                                allowed=allowed, warned=warned, banned=banned,
                                preg_warn_items=preg_warn_items,
                                organism=organism_type, specimen=culture_type,
                                sir_map=sir_map,
                                interactions=interactions_alerts,
                                mdr_result=mdr_result,
                                esbl_result=esbl_result,
                                phenotypes=phenotypes,
                                colony_count=colony_count,
                                date_in=str(date_in),
                                pus_cells=pus_cells_text,
                                rbcs=rbcs_text,
                                lab_name=_lab,
                                lab_city=_city,
                                patho_assessment=(st.session_state.get("patho_result")
                                                  if _pdf_patho else None),
                                duration_data=_dur_for_pdf,
                                combo_suggestions=_combo_for_pdf,
                                show_commercial_names=show_commercial,
                                child_pugh=_cp_pdf,
                                hepatic_recs=_hep_for_pdf,
                                lang=_pdf_lang,
                            )
                            if _new_pdf:
                                st.session_state._pdf_bytes = _new_pdf
                                st.session_state._pdf_lang_used = _pdf_lang
                                st.success("✅ PDF ready — click download below")
                            else:
                                st.error("PDF generation failed — check weasyprint installation")
                        except Exception as _pdf_err:
                            st.error(f"PDF error: {_pdf_err}")

                # Download button
                if st.session_state.get("_pdf_bytes"):
                    _lang_suffix = "EN" if st.session_state.get("_pdf_lang_used") == "en" else "AR_EN"
                    st.download_button(
                        f"📄 Download PDF ({_lang_suffix})",
                        data=st.session_state._pdf_bytes,
                        file_name=(f"CDSS_{organism_type.replace(' ','_')}_"
                                   f"{_pt.replace(' ','_')[:12]}_"
                                   f"{_lang_suffix}_"
                                   f"{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"),
                        mime="application/pdf",
                        use_container_width=True,
                        type="secondary",
                    )
            else:
                st.info("أضف `weasyprint` إلى requirements.txt لتفعيل تصدير PDF")

            # ── صورة الملخص ──────────────────────────────────────────────────
            st.divider()
            st.markdown("### 🖼️ صورة ملخص الحالة")
            st.caption("تتحدث فوراً عند أي تغيير في البيانات")

            if PIL_AVAILABLE:
                # Hash-based cache: regenerate ONLY when an input that actually
                # affects the drawn image changes. The hash must therefore mirror
                # every argument passed to generate_decision_tree_image() below —
                # otherwise a changed value leaves a stale image on screen.
                _ph_sig = "|".join(sorted(
                    str(p.get("phenotype", "")) for p in (phenotypes or [])
                ))
                _mdr_sig = (f"{mdr_result.get('level','')}"
                            f":{mdr_result.get('resistant_count','')}"
                            f"/{mdr_result.get('total_tested','')}")
                _esbl_sig = (f"{esbl_result.get('probability','')}"
                             f":{esbl_result.get('confidence','')}")
                _img_input_hash = hashlib.md5((
                    f"{patient_name}|{age}|{sex}|{weight}|{cl_cr}|{is_renal}|{is_preg}"
                    f"|{is_hepatic}|{organism_type}|{culture_type}|{colony_count}|{date_in}"
                    f"|{pus_cells_text}|{rbcs_text}|{str(sorted(sir_map.items()))}"
                    # lists actually drawn on the image (not just their counts)
                    f"|FL:{','.join(first_line_l)}"
                    f"|PF:{','.join(preferred_with_badge)}"
                    f"|UC:{','.join(use_caution_names)}"
                    f"|BN:{','.join(banned_names)}"
                    f"|RS:{','.join(reserve_names)}"
                    f"|{_mdr_sig}|{_esbl_sig}|PH:{_ph_sig}"
                    f"|{st.session_state.get('lab_name','')}|{st.session_state.get('lab_city','')}"
                    f"|{st.session_state.get('referring_physician','')}"
                    f"|{st.session_state.get('culture_condition','Aerobic')}"
                    f"|{st.session_state.get('microbiologist','')}"
                ).encode()).hexdigest()[:16]

                # FIXED: added _img_error to retry on failure
                if (st.session_state.get("_img_hash") != _img_input_hash
                        or not st.session_state.get("_img_bytes")
                        or st.session_state.get("_img_error")):
                    try:
                        _new_img = generate_decision_tree_image(
                            patient_name=patient_name.strip() or "غير محدد",
                            age=age, sex=sex, weight=weight,
                            cl_cr=cl_cr, is_renal=is_renal, is_preg=is_preg,
                            organism=organism_type, specimen=culture_type,
                            first_line=first_line_l,
                            preferred=preferred_with_badge,
                            use_caution=use_caution_names,
                            contraindicated=banned_names,
                            reserve=reserve_names,
                            notes=notes,
                            colony_count=colony_count,
                            date_in=str(date_in),
                            pus_cells=pus_cells_text,
                            rbcs=rbcs_text,
                            lab_name=st.session_state.get("lab_name", "Orange Lab"),
                            lab_city=st.session_state.get("lab_city", ""),
                            mdr_result=mdr_result,
                            esbl_result=esbl_result,
                            phenotypes=phenotypes,
                            referring_physician=st.session_state.get("referring_physician",""),
                            culture_condition=st.session_state.get("culture_condition","Aerobic"),
                            microbiologist=st.session_state.get("microbiologist",""),
                        )
                        st.session_state._img_bytes = _new_img
                        st.session_state._img_hash  = _img_input_hash
                        st.session_state._img_error = False
                    except Exception as _img_err:
                        st.error(f"خطأ في توليد الصورة: {_img_err}")
                        st.session_state._img_error = True

                img_bytes = st.session_state.get("_img_bytes")
                if img_bytes:
                    st.image(img_bytes,
                             caption=f"Microbiology CDSS | {patient_name.strip() or organism_type} | {str(date_in)}",
                             use_container_width=True)

                    # أزرار التنزيل والطباعة
                    dl_col, pr_col = st.columns(2)
                    with dl_col:
                        st.download_button(
                            "📥 تنزيل الصورة (PNG — Ultra HD)",
                            data=img_bytes,
                            file_name=f"Orange_ClinicalTree_{organism_type.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                            mime="image/png",
                            use_container_width=True,
                        )
                    with pr_col:
                        # زر الطباعة: يفتح الصورة في tab جديد → Ctrl+P للطباعة
                        import base64 as _b64
                        b64 = _b64.b64encode(img_bytes).decode()
                        # نستخدم <a> بدل button لأن Streamlit يحجب onclick
                        print_html = """<a
  href="data:image/png;base64,{b64}"
  target="_blank"
  style="
    display:block;
    text-align:center;
    padding:0.45rem 1rem;
    background:#1B4F9E;
    color:white;
    border-radius:8px;
    font-size:0.95rem;
    font-weight:600;
    text-decoration:none;
    line-height:2;
  ">🖨️ فتح للطباعة (Ctrl+P)</a>"""
                        st.markdown(print_html, unsafe_allow_html=True)
                        st.caption("افتح الرابط ← Ctrl+P أو ⌘+P للطباعة")

            else:
                st.warning("⚠️ أضف `Pillow` لـ requirements.txt لتفعيل صورة الملخص.")

    # ═══════════════════════════════════════════════════════════════════════
    # 💾 Save this culture to the Isolate Registry (feeds the Antibiogram)
    # ═══════════════════════════════════════════════════════════════════════
    st.divider()
    with st.container():
        st.subheader("💾 حفظ في سجل العزلات")
        st.caption(
            "بيتخزّن الميكروب + نتيجة الحساسية + بيانات المريض عشان يتحسبوا في "
            "الأنتيبيوجرام. راجع البيانات فوق الأول، وبعدين احفظ."
        )

        _sir_to_save = {
            k: v for k, v in dict(st.session_state.get("sir_map_edited", {})).items()
            if str(v).strip().upper() in ("S", "I", "R")
        }

        # concise mechanism label (ESBL/AmpC/Carbapenemase + MRSA)
        _mech_res   = predict_esbl(organism_type, _sir_to_save) or {}
        _mech_label = _mech_res.get("mechanism", "") or ""
        _org_l = (organism_type or "").lower()
        if ("staph" in _org_l) and (_sir_to_save.get("Oxacillin") == "R"
                                    or _sir_to_save.get("Cefoxitin") == "R"):
            _mech_label = (f"{_mech_label} | MRSA".strip(" |")) if _mech_label else "MRSA"

        _branch = st.selectbox(
            "🏢 الفرع / Branch",
            ["Lasitee Mall", "Al-Mihwar Al-Markazi"],
            index=["Lasitee Mall", "Al-Mihwar Al-Markazi"].index(
                st.session_state.get("branch", "Lasitee Mall")
            ) if st.session_state.get("branch") in
                 ["Lasitee Mall", "Al-Mihwar Al-Markazi"] else 0,
            key="branch_select",
        )
        st.session_state.branch = _branch

        _has_id = any([st.session_state.get("lab_id"),
                       st.session_state.get("mobile"),
                       st.session_state.get("patient_name_final")])
        if not _has_id:
            st.warning(
                "⚠️ مفيش أي معرّف للمريض (كود/موبايل/اسم). ينفع تحفظ، بس مش هينفع "
                "منع التكرار في الأنتيبيوجرام — كل حفظة هتتحسب لوحدها."
            )
        if not _sir_to_save:
            st.info("ℹ️ مفيش نتائج حساسية (S/I/R) لحفظها بعد.")

        _save_disabled = (not _sir_to_save)
        if st.button("💾 احفظ في السجل", type="primary",
                     disabled=_save_disabled, key="save_isolate_btn"):
            _record = {
                "date_in":      str(st.session_state.get("date_in", "")),
                "branch":       _branch,
                "lab_id":       st.session_state.get("lab_id", ""),
                "patient_name": st.session_state.get("patient_name_final", ""),
                "mobile":       st.session_state.get("mobile", ""),
                "age":          age,
                "sex":          sex,
                "specimen":     culture_type,
                "organism":     organism_type,
                "sir":          _sir_to_save,
                "mechanism":    _mech_label,
            }
            try:
                _rid = REGISTRY.add_isolate(_record)
                get_registry.clear()  # refresh cached count on next rerun
                if _registry_push():
                    st.success(f"✅ اتحفظت واتزامنت مع GitHub. (ID: {_rid[:8]})")
                else:
                    st.success(f"✅ اتحفظت محليًا. (ID: {_rid[:8]})")
                    st.caption("مزامنة GitHub غير مفعّلة — فعّلها في secrets للحفظ الدائم.")
            except Exception as _exc:
                logger.exception("Saving isolate failed: %s", _exc)
                st.error(f"تعذّر الحفظ: {_exc}")

st.divider()
st.markdown("""
<div style="text-align:center;color:gray;font-size:0.9rem;">
  <strong>Developed by Dr / Hussein Ali | Orange Lab</strong><br>
  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | BNF 2025 | Egypt National Guidelines
</div>
""", unsafe_allow_html=True)
