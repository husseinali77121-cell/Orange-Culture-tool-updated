# © 2025 Dr / Hussein Ali — Orange Lab, 6 October City, Egypt
# Microbiology CDSS — All Rights Reserved
# Unauthorized copying or distribution is prohibited.

import io
import json
import re
import time
import hashlib
from datetime import datetime, date
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

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
SIR_LABELS      = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
BACTERIA_TYPES  = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES  = list(SPECIMEN_ORDER or DEFAULT_SPECIMENS)

AWARE_COLORS = {
    "Access":  "🟢 Access",
    "Watch":   "🟡 Watch",
    "Reserve": "🔴 Reserve",
}

# ── Commercial Names Loader ───────────────────────────────────────────
def load_commercial_names(filepath: str = "commercial_names.txt") -> Dict[str, str]:
    """Loads commercial names — multi-path search for Streamlit Cloud compatibility."""
    import os as _os
    result: Dict[str, str] = {}
    # __file__ may be undefined in some exec contexts → guard it
    try:
        _base = _os.path.dirname(_os.path.abspath(__file__))
    except NameError:
        _base = _os.getcwd()
    for _p in [filepath,
                _os.path.join(_base, filepath),
                _os.path.join(_os.getcwd(), filepath)]:
        try:
            with open(_p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        g, _, b = line.partition("=")
                        g, b = g.strip(), b.strip()
                        if g and b:
                            result[g.lower()] = b
            if result:
                break
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return result

COMMERCIAL_NAMES: Dict[str, str] = load_commercial_names()

def get_commercial_name(generic: str) -> str:
    return COMMERCIAL_NAMES.get(generic.lower(), "")

COMMON_MEDS = [
    "Antacids (مضادات الحموضة)",
    "Warfarin (مضادات التخثر)",
    "NSAIDs (مسكنات الألم)",
    "SSRI (أدوية الاكتئاب)",
    "Valproic acid (مضادات الصرع)",
]

RENAL_BAN_REASONS = {
    "nitrofurantoin": (
        "Nitrofurantoin يحتاج وظيفة كلى سليمة ليتركز في البول.\n"
        "عند CrCl < 30 مل/د:\n"
        "- لا يصل لتركيز علاجي في البول → لا يقتل الجرثومة.\n"
        "- يتراكم في الدم → خطر سُمية رئوية وعصبية.\n"
        "السبب: الدواء يُطرح كلياً عبر الترشيح الكبيبي."
    ),
}

CHILD_BAN_REASONS = {
    "fluoroquinolone": (
        "الفلوروكينولونات قد تؤثر على غضاريف النمو في الأطفال < 18 سنة.\n"
        "تُستخدم فقط عند انعدام البدائل وبقرار متخصص."
    ),
    "tetracycline": (
        "Doxycycline والتتراسيكلينات قد تترسب في العظام والأسنان النامية.\n"
        "قد تسبب تلوينًا دائمًا للأسنان وتأثيرًا على نمو العظام.\n"
        "ممنوعة غالباً تحت 8 سنوات."
    ),
}

ORGANISM_AVOID_CLASS_MAP = {
    "cephalosporins (كل الجيل)": ["cephalosporin"],
    "cephalosporins":            ["cephalosporin"],
    "tetracyclines":             ["tetracycline"],
    "aminoglycosides":           ["aminoglycoside"],
    "carbapenems":               ["carbapenem"],
    "beta-lactams (alone)":      ["penicillin", "cephalosporin", "carbapenem"],
    "beta-lactams":              ["penicillin", "cephalosporin", "carbapenem"],
}

# =========================================================
# تحميل المشتركين
# =========================================================
def load_subscribers() -> Dict[str, str]:
    try:
        raw  = st.secrets.get("subscribers_json") or st.secrets.get("subscribers", "{}")
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
        return {str(k).strip().lower(): str(v).strip() for k, v in data.items()}
    except Exception:
        return {}

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
def fuzzy_match(a: str, b: str) -> float:
    a = (a or "").lower().strip()
    b = (b or "").lower().strip()
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 100.0
    return SequenceMatcher(None, a, b).ratio() * 100

def make_file_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()

def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def calc_creatinine_clearance(age: int, weight: float, scr: float, sex: str) -> float:
    if scr <= 0:
        return 0.0
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
    expiry_str = SUBSCRIBERS[email]
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        today       = datetime.now().date()
        return (expiry_date - today).days
    except Exception:
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
        login_btn = st.button("دخول", use_container_width=True, type="primary")
        if login_btn:
            return email.strip().lower()
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

def check_subscription(email: str) -> bool:
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
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

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
            except Exception:
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
    if any(t in text_lower for t in ["female", "sex: ", "gender: female", "أنثى", "انثى"]):
        return "Female"
    if any(t in text_lower for t in ["male", "sex: m", "gender: male", "ذكر"]):
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
    import re
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
    import re
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
    import re
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
    _mech = predict_esbl(organism_type, sir_map) if sir_map else {"probability": None}
    _mech_prob = _mech.get("probability")
    _is_esbl_like   = _mech_prob in ("high", "ampc")
    _is_carbapenemase = _mech_prob == "carbapenemase"

    # ── Detect MRSA from AST markers (Oxacillin/Cefoxitin R), not just name ────
    # A S. aureus with Oxacillin-R or Cefoxitin-R IS MRSA → ALL beta-lactams fail
    # (except anti-MRSA cephalosporins like Ceftaroline, not in this formulary).
    _org_l_aa = organism_type.lower()
    _is_staph = ("staphylococcus" in _org_l_aa or "staph" in _org_l_aa
                 or _org_l_aa == "mrsa" or _org_l_aa == "mssa")
    _mrsa_marker_R = (sir_map.get("Oxacillin") == "R"
                      or sir_map.get("Cefoxitin") == "R"
                      or _org_l_aa == "mrsa")
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

    # ── Specimen-specific filtering ───────────────────────────────────────────
    is_stool_gi = any(k in culture_type.lower() for k in ["stool","fecal","rectal"])
    if is_stool_gi:
        # UTI-only drugs inappropriate for GI infections
        _uti_only = {"Nitrofurantoin", "Fosfomycin"}
        allowed = [d for d in allowed if d.get("name") not in _uti_only]
        warned  = [d for d in warned  if d.get("name") not in _uti_only]

    is_urine = "urine" in culture_type.lower()
    if not is_urine:
        # Colony count thresholds are UTI-specific — don't apply to other specimens
        pass  # analyze_antibiotics doesn't use colony count, ok

    return allowed, warned, banned, preg_warn_items, sorted(set(interactions_alerts))

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
MDR_CATEGORIES = {
    "Aminoglycosides":              ["Gentamicin","Amikacin"],
    "Antipseudomonal Penics":       ["Piperacillin + Tazobactam"],
    "Extended-Sp Cephalosporins":   ["Ceftriaxone","Cefotaxime","Cefixime","Cefuroxime"],
    "Carbapenems":                  ["Imipenem/Cilastatin","Meropenem","Ertapenem"],
    "Fluoroquinolones":             ["Ciprofloxacin","Levofloxacin","Ofloxacin","Norfloxacin"],
    "Folate PI":                    ["Trimethoprim/Sulfamethoxazole"],
    "Penicillins+BLI":              ["Amoxicillin + Clavulanic acid","Ampicillin/Sulbactam"],
    "Polymyxins":                   ["Colistin"],
    "Cephalosporins-4th":           ["Cefepime"],
    "Cephalosporins-3rd-AP":        ["Ceftazidime","Cefoperazone","Cefoperazone + Sulbactam"],
    "Glycopeptides":                ["Vancomycin"],
    "Oxazolidinones":               ["Linezolid"],
    "Nitrofurans":                  ["Nitrofurantoin"],
    "Fosfomycins":                  ["Fosfomycin"],
    "Tetracyclines":                ["Doxycycline","Tetracycline","Minocycline"],  # Minocycline: MDR scoring only
    "Macrolides":                   ["Azithromycin","Clarithromycin","Erythromycin"],  # Erythromycin: MDR scoring only
    "Lincosamides":                 ["Clindamycin"],     # MDR scoring only
    "Rifamycins":                   ["Rifampicin"],      # MDR scoring only
}

# Categories meaningful for Gram-negative organisms (Enterobacterales / non-fermenters)
MDR_CATEGORIES_GRAM_NEG = frozenset([
    "Aminoglycosides", "Antipseudomonal Penics", "Extended-Sp Cephalosporins",
    "Carbapenems", "Fluoroquinolones", "Folate PI", "Penicillins+BLI",
    "Polymyxins", "Cephalosporins-4th", "Cephalosporins-3rd-AP",
    "Nitrofurans", "Fosfomycins", "Tetracyclines",
])
# Categories meaningful for Gram-positive organisms
MDR_CATEGORIES_GRAM_POS = frozenset([
    "Glycopeptides", "Oxazolidinones", "Macrolides", "Lincosamides",
    "Tetracyclines", "Fluoroquinolones", "Folate PI", "Rifamycins",
    "Aminoglycosides", "Penicillins+BLI", "Nitrofurans",
])

GRAM_POSITIVE_ORGANISMS = frozenset([
    "staphylococcus aureus", "mrsa", "mssa",
    "staphylococcus epidermidis", "staphylococcus saprophyticus",
    "enterococcus faecalis", "enterococcus faecium", "enterococcus spp.", "vre",
    "streptococcus pneumoniae", "streptococcus pyogenes",
    "streptococcus agalactiae", "streptococcus viridans",
    "listeria monocytogenes", "corynebacterium",
])

# Intrinsic resistance — organism is naturally resistant; EXCLUDE from MDR calc
# (Magiorakos 2012 / EUCAST Expert Rules v3.3 / CLSI M100)
INTRINSIC_RESISTANCE = {
    "proteus mirabilis":      ["Nitrofurantoin", "Colistin", "Tetracycline", "Tigecycline"],
    "proteus spp.":           ["Nitrofurantoin", "Colistin", "Tetracycline"],
    "proteus vulgaris":       ["Nitrofurantoin", "Colistin", "Ampicillin"],
    "morganella morganii":    ["Nitrofurantoin", "Colistin", "Amoxicillin + Clavulanic acid"],
    "serratia marcescens":    ["Nitrofurantoin", "Colistin", "Ampicillin"],
    "pseudomonas aeruginosa": ["Trimethoprim/Sulfamethoxazole", "Tetracycline",
                               "Tigecycline", "Ertapenem"],
    "klebsiella pneumoniae":  ["Ampicillin"],
    "klebsiella spp.":        ["Ampicillin"],
    "enterobacter cloacae":   ["Amoxicillin + Clavulanic acid", "Ampicillin"],
    "enterobacter spp.":      ["Amoxicillin + Clavulanic acid", "Ampicillin"],
    "citrobacter spp.":       ["Ampicillin", "Amoxicillin + Clavulanic acid"],
    "stenotrophomonas maltophilia": ["Imipenem/Cilastatin", "Meropenem", "Ertapenem"],
    "enterococcus faecalis":  ["Cephalexin", "Cefuroxime", "Ceftriaxone",
                               "Cefotaxime", "Gentamicin", "Amikacin"],
    "enterococcus faecium":   ["Cephalexin", "Cefuroxime", "Ceftriaxone", "Gentamicin"],
}

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
    • Category flagged non-susceptible if non-susceptible to ≥1 agent in it
    • Reliability warning when too few categories testable
    """
    if not sir_map:
        return {"level": None, "resistant_categories": [], "total_tested": 0}

    # 1. Strip intrinsic resistance
    clean_map = _remove_intrinsic_resistance(organism, sir_map)

    # 2. Choose category set by Gram stain
    org_l = organism.lower().strip()
    is_gram_pos = any(g in org_l for g in GRAM_POSITIVE_ORGANISMS)
    applicable = MDR_CATEGORIES_GRAM_POS if is_gram_pos else MDR_CATEGORIES_GRAM_NEG

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
        # Non-susceptible = R or I
        if any(clean_map.get(d) in ("R", "I") for d in tested):
            resistant_cats.append(cat)
        else:
            susceptible_cats.append(cat)

    total_cats = len(resistant_cats) + len(susceptible_cats)
    r_count    = len(resistant_cats)

    if total_cats == 0:
        return {"level": None, "resistant_categories": [], "total_tested": 0}

    # XDR/PDR require enough categories tested to be meaningful (Magiorakos:
    # XDR = susceptible to ≤2 categories out of the full applicable panel).
    # Without a broad panel we cannot reliably call XDR/PDR → cap at MDR.
    _enough_for_xdr = total_cats >= 6

    if r_count >= total_cats and _enough_for_xdr:
        level = "PDR"
    elif (total_cats - r_count) <= 2 and r_count >= 3 and _enough_for_xdr:
        level = "XDR"
    elif r_count >= 3:
        level = "MDR"
    else:
        level = None

    # If pattern looks like XDR/PDR but panel too small, flag it but keep MDR
    _capped = False
    if not _enough_for_xdr and r_count >= 3 and (total_cats - r_count) <= 2:
        _capped = True

    # Reliability flag
    reliable = total_cats >= 4
    warnings = []
    if not reliable:
        warnings.append(f"⚠️ Only {total_cats} categories testable — MDR classification may be unreliable.")
    if single_drug_cats:
        warnings.append(f"⚠️ Categories judged on a single agent: {', '.join(single_drug_cats)}")
    if _capped:
        warnings.append("⚠️ Resistance pattern suggests XDR/PDR, but too few categories tested to confirm — reported as MDR. Expand the panel.")

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

MDR_INFO = {
    "MDR": {
        "label":  "MDR — Multi-Drug Resistant",
        "color":  "warning",
        "icon":   "⚠️",
        "detail": "مقاوم لعامل واحد على الأقل في 3 فئات دوائية أو أكثر.",
        "action": "تجنب الأدوية المقاومة. استشر الصيدلي السريري.",
    },
    "XDR": {
        "label":  "XDR — Extensively Drug Resistant",
        "color":  "error",
        "icon":   "🔴",
        "detail": "مقاوم لمعظم الفئات الدوائية — حساس لفئتين أو أقل فقط.",
        "action": "يستلزم استشارة متخصص. الخيارات محدودة جداً.",
    },
    "PDR": {
        "label":  "PDR — Pan-Drug Resistant",
        "color":  "error",
        "icon":   "🚨",
        "detail": "مقاوم لجميع الفئات الدوائية المتاحة.",
        "action": "حالة طارئة — استشارة معدية فورية. لا خيارات قياسية.",
    },
}

# =========================================================
# ESBL / AmpC / Carbapenemase Predictor
# EUCAST 2026 | CLSI M100 2026 | EUCAST guidance on detection of resistance mechanisms
# =========================================================
# Organisms capable of ESBL production (Enterobacterales).
# Stored as a set; matching is substring-based to handle OCR variants.
ESBL_PRODUCERS = frozenset([
    "escherichia coli", "e. coli", "e.coli",
    "klebsiella pneumoniae", "klebsiella spp.", "klebsiella oxytoca",
    "proteus mirabilis", "proteus spp.",
    "enterobacter cloacae", "enterobacter spp.", "enterobacter aerogenes",
    "citrobacter freundii", "citrobacter koseri", "citrobacter spp.",
    "serratia marcescens", "serratia spp.",
    "morganella morganii", "providencia spp.",
])
# AmpC-prone organisms (chromosomal inducible AmpC — "SPICE/SPACE")
AMPC_PRODUCERS = frozenset([
    "enterobacter cloacae", "enterobacter spp.", "enterobacter aerogenes",
    "citrobacter freundii", "citrobacter spp.",
    "serratia marcescens", "serratia spp.",
    "morganella morganii", "providencia spp.",
    "pseudomonas aeruginosa", "hafnia alvei",
])

ESBL_MARKERS = {
    # Primary 3rd-gen oxyimino-cephalosporins — best ESBL indicators
    "primary":   ["Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefpodoxime"],
    # Cefepime is 4th-gen — may stay S in ESBL → secondary only
    "secondary": ["Cefepime"],
    # Lower-gen cephalosporins
    "medium":    ["Cefuroxime", "Cefixime", "Cefaclor", "Cephalexin"],
}
CARBAPENEMS = ["Imipenem/Cilastatin", "Meropenem", "Ertapenem"]

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
        return {"probability": None, "confidence": 0}

    org_l = organism.lower().strip()
    is_producer = any(p in org_l or org_l in p for p in ESBL_PRODUCERS)
    is_ampc_prone = any(p in org_l or org_l in p for p in AMPC_PRODUCERS)
    if not is_producer and not is_ampc_prone:
        return {"probability": None, "confidence": 0}

    def _ns(drug):  # non-susceptible = R or I
        return sir_map.get(drug) in ("R", "I")
    def _r(drug):
        return sir_map.get(drug) == "R"

    primary_R = [d for d in ESBL_MARKERS["primary"] if _r(d)]
    second_R  = [d for d in ESBL_MARKERS["secondary"] if _r(d)]
    med_R     = [d for d in ESBL_MARKERS["medium"] if _r(d)]
    cefoxitin_R = _r("Cefoxitin")

    carb_R_list = [d for d in CARBAPENEMS if _r(d)]
    erta_R   = _r("Ertapenem")
    mero_R   = _r("Meropenem")
    mero_I   = sir_map.get("Meropenem") == "I"
    
    # ── 1. Carbapenemase tiers (highest priority) ─────────────────────────
    if len(carb_R_list) >= 2:
        return {
            "probability": "carbapenemase",
            "confidence": 92,
            "mechanism": "Carbapenemase (KPC / MBL / OXA-48-like)",
            "markers_R": carb_R_list + primary_R,
            "detail": f"مقاومة لـ ≥2 كاربابينيم ({', '.join(carb_R_list)}) — نمط Carbapenemase صريح.",
            "action": "أرسل للمختبر المرجعي فوراً (PCR/mCIM). عزل صارم. Colistin/Ceftazidime-Avibactam.",
        }
    if erta_R and (sir_map.get("Meropenem") in ("S", "I")) and not mero_R:
        # Classic OXA-48 fingerprint — common in Egypt / Middle East
        return {
            "probability": "carbapenemase",
            "confidence": 70,
            "mechanism": "Possible OXA-48-like carbapenemase",
            "markers_R": ["Ertapenem"] + primary_R,
            "detail": "Ertapenem R مع Meropenem S/I — نمط مُوحٍ بـ OXA-48 (شائع في مصر/الشرق الأوسط).",
            "action": "أكد بـ mCIM / PCR (OXA-48). راقب بحذر؛ قد تكون الكاربابينيمات أقل فعالية.",
        }
    if len(carb_R_list) == 1 or mero_I:
        return {
            "probability": "carbapenemase",
            "confidence": 55,
            "mechanism": "Possible carbapenemase (low-level)",
            "markers_R": carb_R_list or ["Meropenem (I)"],
            "detail": "مقاومة/توسط لكاربابينيم واحد — يستلزم اختبار تأكيدي.",
            "action": "أجرِ mCIM/CarbaNP. قد يكون فقدان بورين + ESBL/AmpC وليس carbapenemase حقيقياً.",
        }

    # ── 2. AmpC (3rd-gen R + Cefoxitin R in AmpC-prone) ───────────────────
    if is_ampc_prone and primary_R and cefoxitin_R:
        return {
            "probability": "ampc",
            "confidence": 75,
            "mechanism": "Possible AmpC β-lactamase (derepressed/inducible)",
            "markers_R": primary_R + ["Cefoxitin"],
            "detail": "مقاومة لـ 3rd-gen + Cefoxitin في كائن AmpC-prone — نمط AmpC وليس ESBL.",
            "action": "تجنب 3rd-gen cephalosporins حتى لو S. استخدم Cefepime أو Carbapenem. لا يُكتشف بـ DDST.",
        }

    # ── 3. ESBL ───────────────────────────────────────────────────────────
    if len(primary_R) >= 2:
        return {
            "probability": "high",
            "confidence": 88,
            "mechanism": "ESBL (Extended-Spectrum β-Lactamase)",
            "markers_R": primary_R + second_R,
            "detail": f"مقاومة لـ {', '.join(primary_R)} — احتمال ESBL مرتفع.",
            "action": "استخدم Carbapenem للعدوى الشديدة (MERINO 2018). تجنب جميع cephalosporins.",
        }
    if len(primary_R) == 1:
        # Classic single-marker ESBL pattern (e.g., Ceftriaxone R, Meropenem S)
        carbS = any(sir_map.get(d) == "S" for d in CARBAPENEMS)
        return {
            "probability": "high" if carbS else "moderate",
            "confidence": 72 if carbS else 60,
            "mechanism": "Probable ESBL",
            "markers_R": primary_R + med_R,
            "detail": f"مقاومة لـ {primary_R[0]}" + (" مع كاربابينيم حساس — نمط ESBL كلاسيكي." if carbS else "."),
            "action": "أكد بـ Double-Disk Synergy Test (DDST) أو PCR. عامل كـ ESBL حتى التأكيد.",
        }
    if len(med_R) >= 2:
        return {
            "probability": "moderate",
            "confidence": 50,
            "mechanism": "Possible ESBL (lower-gen cephalosporin resistance)",
            "markers_R": med_R,
            "detail": "مقاومة لـ ≥2 من الجيل الأقل — يستدعي تأكيد ESBL.",
            "action": "أجرِ DDST. قد يكون ESBL مبكر أو آلية أخرى.",
        }

    return {"probability": "low", "confidence": 10}

# =========================================================
# Pathogenicity Assessment Module — v2
# Covers: Urine, Sputum (Murray-Washington), Blood (SIRS),
#         Wound/Pus, CSF, Swab
# Includes: Pediatric thresholds, ABU detection
# =========================================================
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
        "Staphylococcus aureus", "Staphylococcus epidermidis",
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
        "Staphylococcus aureus", "Moraxella catarrhalis",
        "Acinetobacter baumannii", "Enterobacter spp.",
        "Escherichia coli", "Serratia marcescens",
    ]
    URT_CONTAMINANTS_SPUTUM = [
        "Streptococcus viridans", "Neisseria spp.", "Candida spp.",
        "Candida albicans", "Staphylococcus epidermidis",
        "Corynebacterium spp.",
    ]
    TRUE_BLOOD_PATHOGENS = [
        "Staphylococcus aureus", "Streptococcus pneumoniae",
        "Escherichia coli", "Klebsiella pneumoniae", "Pseudomonas aeruginosa",
        "Acinetobacter baumannii", "Enterococcus faecalis", "Enterococcus spp.",
        "Candida albicans", "Candida spp.", "Salmonella spp.",
        "Neisseria meningitidis", "Listeria monocytogenes",
    ]
    BLOOD_CONTAMINANTS = [
        "Staphylococcus epidermidis", "Corynebacterium spp.",
        "Bacillus spp.", "Propionibacterium spp.", "Micrococcus spp.",
    ]

    spec_lower = specimen.lower()

    # ══════════════════════════════════════════════════════════════════
    # URINE
    # ══════════════════════════════════════════════════════════════════
    if "urine" in spec_lower:

        # Pediatric threshold: < 2 years → any growth significant
        if age < 2:
            score += 20
            factors_pos.append("✅ Infant < 2 yrs — any colony count clinically significant")
            special_flags.append("PEDIATRIC_UTI")

        # Organism context
        if organism in TYPICAL_UROPATHOGENS:
            score += 20
            factors_pos.append(f"✅ {organism} — typical uropathogen")
        elif organism in ATYPICAL_UROPATHOGENS:
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
    elif "sputum" in spec_lower or "respiratory" in spec_lower or "bal" in spec_lower:

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
        if organism in RESPIRATORY_PATHOGENS:
            score += 20
            factors_pos.append(f"✅ {organism} — recognized respiratory pathogen")
        elif organism in URT_CONTAMINANTS_SPUTUM:
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
    elif "blood" in spec_lower:

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
        if organism in TRUE_BLOOD_PATHOGENS:
            score += 25
            factors_pos.append(f"✅ {organism} — true bloodstream pathogen; single positive = significant")
        elif organism in BLOOD_CONTAMINANTS:
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
        elif "Single bottle" in blood_source and organism in BLOOD_CONTAMINANTS:
            score -= 15
            factors_neg.append("⚠️ Single bottle + contaminant organism — likely contamination")

        # Source identified
        if blood_source and "source" in blood_source.lower():
            score += 10
            factors_pos.append(f"➕ Source identified: {blood_source}")

    # ══════════════════════════════════════════════════════════════════
    # CSF
    # ══════════════════════════════════════════════════════════════════
    elif "csf" in spec_lower or "cerebrospinal" in spec_lower:
        score += 40
        factors_pos.append("✅ CSF — any growth is always clinically significant (sterile site)")
        special_flags.append("CSF_ALWAYS_SIGNIFICANT")

    # ══════════════════════════════════════════════════════════════════
    # STOOL / GI
    # ══════════════════════════════════════════════════════════════════
    elif "stool" in spec_lower or "fecal" in spec_lower or "rectal" in spec_lower:

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

        if organism in GI_TRUE_PATHOGENS:
            score += 40
            factors_pos.append(f"✅ {organism} — obligate GI pathogen; always clinically significant")
            special_flags.append("GI_TRUE_PATHOGEN")
        elif organism in GI_NORMAL_FLORA:
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
    elif any(w in spec_lower for w in ["wound", "pus", "abscess", "swab"]):
        wound_lower = wound_type.lower() if wound_type else ""

        if organism in NORMAL_SKIN_FLORA and not wound_lower:
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
            factors_neg.append("➕ Superficial wound — assess depth and clinical signs")

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
        factors_pos.append("✅ Pregnancy — any bacteriuria requires treatment")
    if not host_factors:
        score -= 5
        factors_neg.append("➕ No host risk factors identified")

    # Pediatric global flag
    if age < 3 and "PEDIATRIC_UTI" not in special_flags and "csf" not in spec_lower:
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
        verdict = "🟢 SPECIMEN INADEQUATE — Reject & Repeat"
        color   = "success"
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
    t = text.lower().strip()
    if any(x in t for x in ["≥", ">=", ">10^5", ">100000", "10^5", "≥10", ">=10"]):
        if "10^5" in t or "100000" in t or "≥10^5" in t:
            return 100000
        if "10^4" in t or "10000" in t:
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
TREATMENT_DURATION_DB: Dict[str, Any] = {
    "UTI_uncomplicated_female": {
        "label": "Uncomplicated UTI (Female)",
        "days": (3, 7), "standard": 5, "iv_days": 0, "po_days": 5,
        "notes": "3d TMP-SMX | 5d Nitrofurantoin | 3-7d FQ (not preferred)",
        "follow_up_culture": False, "ref": "IDSA UTI Guidelines 2022",
    },
    "UTI_complicated": {
        "label": "Complicated UTI",
        "days": (7, 14), "standard": 10, "iv_days": 3, "po_days": 7,
        "notes": "7d if rapid response | 14d for males or catheter-associated",
        "follow_up_culture": True, "ref": "IDSA 2022",
    },
    "Pyelonephritis_outpatient": {
        "label": "Pyelonephritis (Outpatient)",
        "days": (7, 14), "standard": 7, "iv_days": 0, "po_days": 7,
        "notes": "7d FQ | 14d if beta-lactam used. Verify sensitivities.",
        "follow_up_culture": True, "ref": "IDSA 2022",
    },
    "Pyelonephritis_inpatient": {
        "label": "Pyelonephritis (Inpatient)",
        "days": (10, 14), "standard": 14, "iv_days": 3, "po_days": 11,
        "notes": "IV until afebrile 24-48h → step-down to high-bioavailability oral",
        "follow_up_culture": True, "ref": "IDSA 2022",
    },
    "CAP_mild": {
        "label": "CAP — Mild (Outpatient)",
        "days": (5, 7), "standard": 5, "iv_days": 0, "po_days": 5,
        "notes": "5 days adequate for mild CAP. No CURB-65 risk factors.",
        "follow_up_culture": False, "ref": "IDSA/ATS CAP Guidelines 2019",
    },
    "CAP_moderate": {
        "label": "CAP — Moderate (Inpatient)",
        "days": (7, 10), "standard": 7, "iv_days": 2, "po_days": 5,
        "notes": "IV until clinical stability → oral step-down. CRP-guided preferred.",
        "follow_up_culture": False, "ref": "IDSA/ATS 2019",
    },
    "CAP_severe": {
        "label": "CAP — Severe (ICU)",
        "days": (10, 14), "standard": 10, "iv_days": 7, "po_days": 3,
        "notes": "Reassess at day 5. Consider PCT/CRP-guided de-escalation.",
        "follow_up_culture": True, "ref": "IDSA/ATS 2019",
    },
    "HAP_VAP": {
        "label": "HAP / VAP",
        "days": (7, 14), "standard": 8, "iv_days": 8, "po_days": 0,
        "notes": "8d adequate for most HAP/VAP. Non-fermenters (Pseudomonas, CRAB) → 14d.",
        "follow_up_culture": True, "ref": "ATS/IDSA HAP/VAP 2016",
    },
    "Bacteremia_GNB": {
        "label": "GNB Bacteremia",
        "days": (7, 14), "standard": 14, "iv_days": 14, "po_days": 0,
        "notes": "14d IV. Source control mandatory. Echo if Staph aureus.",
        "follow_up_culture": True, "ref": "IDSA 2025",
    },
    "Bacteremia_MSSA": {
        "label": "MSSA Bacteremia",
        "days": (14, 42), "standard": 14, "iv_days": 14, "po_days": 0,
        "notes": "Min 14d IV (uncomplicated) | 28-42d (complicated/endovascular). Echo mandatory.",
        "follow_up_culture": True, "ref": "IDSA Bacteremia 2025",
    },
    "Bacteremia_MRSA": {
        "label": "MRSA Bacteremia",
        "days": (14, 42), "standard": 14, "iv_days": 14, "po_days": 0,
        "notes": "Vancomycin AUC/MIC target 400-600. Min 14d (uncomplicated) | 42d (endocarditis).",
        "follow_up_culture": True, "ref": "IDSA MRSA Guidelines 2011 (updated 2025)",
    },
    "Meningitis_pneumococcal": {
        "label": "Pneumococcal Meningitis",
        "days": (10, 14), "standard": 14, "iv_days": 14, "po_days": 0,
        "notes": "Dexamethasone 0.15mg/kg q6h x4d adjunct. IV throughout.",
        "follow_up_culture": True, "ref": "IDSA Meningitis Guidelines",
    },
    "Meningitis_GNB": {
        "label": "Gram-Negative Meningitis",
        "days": (21, 21), "standard": 21, "iv_days": 21, "po_days": 0,
        "notes": "21d IV for GNB meningitis. Verify CSF sterilization.",
        "follow_up_culture": True, "ref": "IDSA Meningitis Guidelines",
    },
    "SSTI_mild": {
        "label": "SSTI — Mild (Cellulitis)",
        "days": (5, 7), "standard": 5, "iv_days": 0, "po_days": 5,
        "notes": "5d oral adequate for uncomplicated cellulitis without systemic signs.",
        "follow_up_culture": False, "ref": "IDSA SSTI Guidelines 2014",
    },
    "SSTI_moderate": {
        "label": "SSTI — Moderate",
        "days": (7, 14), "standard": 7, "iv_days": 2, "po_days": 5,
        "notes": "IV until afebrile + local improvement → step-down oral.",
        "follow_up_culture": False, "ref": "IDSA SSTI 2014",
    },
    "SSTI_severe": {
        "label": "SSTI — Severe / Necrotizing",
        "days": (10, 21), "standard": 14, "iv_days": 14, "po_days": 0,
        "notes": "IV + surgical source control. ID consult mandatory.",
        "follow_up_culture": True, "ref": "IDSA SSTI 2014",
    },
    "Osteomyelitis": {
        "label": "Osteomyelitis",
        "days": (42, 84), "standard": 42, "iv_days": 14, "po_days": 28,
        "notes": "IV 2 weeks → high-bioavailability oral 4+ weeks. Total ≥6 weeks.",
        "follow_up_culture": True, "ref": "IDSA Osteomyelitis 2012",
    },
    "Intraabdominal_mild": {
        "label": "Intraabdominal Infection (Source Controlled)",
        "days": (4, 7), "standard": 4, "iv_days": 2, "po_days": 2,
        "notes": "4d if source controlled (STOP-IT trial 2015). Extend only for ongoing sepsis.",
        "follow_up_culture": False, "ref": "IDSA IAI 2010 | STOP-IT 2015",
    },
    "Intraabdominal_severe": {
        "label": "Intraabdominal Infection (Severe)",
        "days": (7, 14), "standard": 7, "iv_days": 5, "po_days": 2,
        "notes": "7-10d. Ongoing signs → reassess source control.",
        "follow_up_culture": True, "ref": "IDSA IAI 2010",
    },
    "GI_mild": {
        "label": "GI Infection — Mild/Moderate (Supportive Care)",
        "days": (0, 5), "standard": 0, "iv_days": 0, "po_days": 0,
        "notes": "Most GI infections: supportive care (fluids, electrolytes). "
                 "Antibiotics ONLY for: bloody diarrhea, immunocompromised, "
                 "severe dehydration, Salmonella typhi, Shigella, C. diff.",
        "follow_up_culture": False, "ref": "IDSA Foodborne GI 2017 | WHO 2025",
    },
    "GI_severe": {
        "label": "Severe GI Infection / Immunocompromised",
        "days": (3, 7), "standard": 5, "iv_days": 2, "po_days": 3,
        "notes": "Azithromycin or Ciprofloxacin 3-5d. C. diff → Vancomycin/Fidaxomicin 10-14d. "
                 "Salmonella typhi → 7-14d. Reassess daily.",
        "follow_up_culture": True, "ref": "IDSA 2017 | Sanford 2025",
    },
}

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
        key = "Meningitis_pneumococcal" if "pneumoniae" in org else "Meningitis_GNB"
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

    d = TREATMENT_DURATION_DB[key].copy()
    mn, mx = d["days"]
    notes_extra = []
    if has_mdr:
        mx = max(mx, 14)
        notes_extra.append("MDR organism: extended duration may be required.")
    if is_renal: notes_extra.append("Renal impairment: monitor drug levels closely.")
    if age > 65:  notes_extra.append("Elderly: monitor for toxicity; shorter courses if responding.")
    if notes_extra:
        d["notes"] = d["notes"] + " | " + " | ".join(notes_extra)
    d.update({"min_days": mn, "max_days": mx, "standard_days": d["standard"]})
    return d


# ═══════════════════════════════════════════════════════════════════════
# ENGINE 2 — IV→PO Switch Engine
# IDSA OPAT 2019 | BNF 2025 | BSAC 2023
# ═══════════════════════════════════════════════════════════════════════
HIGH_BIOAVAILABILITY: Dict[str, int] = {
    # Keys match abx_guidelines.py drug names exactly for cross-module consistency
    "Ciprofloxacin": 95, "Levofloxacin": 99, "Ofloxacin": 95, "Norfloxacin": 30,
    "Metronidazole": 99, "Linezolid": 100,
    "Trimethoprim/Sulfamethoxazole": 90, "Doxycycline": 93,
    "Minocycline": 95, "Clindamycin": 87,           # MDR/REF only — not in formulary
    "Rifampicin": 95,                                # MDR/REF only — not in formulary
    "Amoxicillin": 90,                               # plain Amoxicillin
    "Amoxicillin + Clavulanic acid": 65,             # fixed: was "Amoxicillin-Clavulanate"
    "Cephalexin": 90, "Cephradine": 90,
    "Cefuroxime": 52, "Cefixime": 50,
    "Nitrofurantoin": 85, "Fosfomycin": 36,
    "Azithromycin": 37, "Clarithromycin": 52,
    "Erythromycin": 35,                              # MDR/REF only — not in formulary
    "Trimethoprim": 90,                              # standalone (subset of TMP-SMX)
}
ALWAYS_IV_SYNDROMES = frozenset([
    "endocarditis", "meningitis", "septic shock", "bacteremia",
    "necrotizing fasciitis", "osteomyelitis (acute)", "vap",
])

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


# ═══════════════════════════════════════════════════════════════════════
# ENGINE 3 — Hepatic Dosing (Child-Pugh A/B/C)
# BNF 2025 | Lexicomp 2025 | UpToDate 2025
# ═══════════════════════════════════════════════════════════════════════
HEPATIC_DOSING: Dict[str, Dict] = {
    # ── Keys MUST match abx_guidelines.py drug names exactly for lookup to work ──
    # Drugs marked [MDR/REF only] appear in MDR_CATEGORIES or combo recommendations
    # but are NOT in the active formulary (abx_guidelines.py) — hepatic data kept
    # for reference display only.
    "Metronidazole":                 {"A": ("Normal","No adjustment"), "B": ("Reduce 50%","Reduce dose by 50%"), "C": ("Avoid/Reduce","Avoid if possible; if essential max 500mg q12h"), "note": "Extensive hepatic metabolism"},
    "Clindamycin":                   {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution; reduce 25-50%"), "C": ("Avoid","Avoid — accumulation risk"), "note": "Primary hepatic metabolism [MDR/REF only]"},
    "Rifampicin":                    {"A": ("Normal (no jaundice)","Normal if no jaundice"), "B": ("Max 8mg/kg/d","Max 8mg/kg/day; weekly LFTs"), "C": ("Avoid","Avoid — hepatotoxic + CYP inducer"), "note": "Hepatotoxic + strong CYP inducer [MDR/REF only]"},
    "Erythromycin":                  {"A": ("Normal","No adjustment"), "B": ("Reduce 25%","Reduce dose by 25%"), "C": ("Reduce 50%","Reduce 50% or avoid"), "note": "Cholestatic hepatitis risk [MDR/REF only]"},
    "Ceftriaxone":                   {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment; max 2g/day"), "C": ("Max 2g/day","2g/day maximum — biliary sludge risk"), "note": "Dual hepatic/renal elimination"},
    "Linezolid":                     {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No adjustment — primarily renal"), "note": "No hepatic dose adjustment required"},
    "Vancomycin":                    {"A": ("Renal-based","AUC/MIC monitoring"), "B": ("Renal-based","AUC/MIC monitoring"), "C": ("Renal-based","AUC/MIC monitoring"), "note": "Primarily renal — no hepatic adjustment"},
    "Ciprofloxacin":                 {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution"), "C": ("Reduce 50%","Reduce by 50% in severe failure"), "note": "Partial hepatic metabolism"},
    "Doxycycline":                   {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution"), "C": ("Avoid","Avoid in severe hepatic failure"), "note": "Biliary excretion pathway"},
    # ── Key fixed: was "Amoxicillin-Clavulanate" → now matches abx_guidelines ──
    "Amoxicillin + Clavulanic acid": {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Avoid","Avoid — Clavulanate-associated DILI risk"), "note": "Clavulanate linked to drug-induced liver injury"},
    # ── Key fixed: was "Piperacillin-Tazobactam" → now matches abx_guidelines ──
    "Piperacillin + Tazobactam":     {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal (renal)","No hepatic adjustment — monitor renal"), "note": "Primarily renal elimination"},
    "Tigecycline":                   {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Reduce","100mg loading then 12.5mg q12h in Child-Pugh C"), "note": "Biliary excretion — adjust in severe impairment [MDR/REF only]"},
    "Colistin":                      {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Renal-based","Based on CrCl — primarily renal"), "note": "Primarily renal elimination"},
    "Nitrofurantoin":                {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution"), "C": ("Avoid","Avoid in hepatic failure"), "note": "Cholestatic hepatitis risk"},
    "Chloramphenicol":               {"A": ("Caution","Use with caution"), "B": ("Avoid","Avoid"), "C": ("Avoid","Avoid — gray syndrome risk"), "note": "Hepatic glucuronidation — accumulates [MDR/REF only]"},
    "Trimethoprim/Sulfamethoxazole": {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution"), "C": ("Avoid","Avoid in severe hepatic failure"), "note": "Hepatic acetylation — accumulates"},
    "Azithromycin":                  {"A": ("Normal","No adjustment"), "B": ("Caution","Monitor LFTs"), "C": ("Avoid","Avoid in severe hepatic failure"), "note": "Biliary excretion — hepatic impairment increases exposure"},
    "Clarithromycin":                {"A": ("Normal","No adjustment"), "B": ("Caution","Use with caution"), "C": ("Avoid","Avoid — accumulation + QT risk"), "note": "Hepatic CYP3A4 metabolism"},
    "Meropenem":                     {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Caution","No formal adjustment — monitor clinically"), "note": "Minimal hepatic metabolism"},
    "Imipenem/Cilastatin":           {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Caution","No formal adjustment — monitor seizure risk"), "note": "Minimal hepatic metabolism"},
    # ── Additional entries — BNF 2025 / Lexicomp 2025 ─────────────────────
    "Levofloxacin":                  {"A": ("Normal","No adjustment"), "B": ("Caution","Monitor LFTs"), "C": ("Caution","No formal adjustment — primarily renal; monitor"), "note": "Partial hepatic metabolism — primarily renal"},
    "Ofloxacin":                     {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment — primarily renal"), "note": "Primarily renal elimination"},
    "Norfloxacin":                   {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment — primarily renal"), "note": "Primarily renal elimination"},
    "Ertapenem":                     {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment required"), "note": "Primarily renal elimination"},
    "Ampicillin/Sulbactam":          {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment — primarily renal"), "note": "Primarily renal elimination"},
    "Fosfomycin":                    {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment"), "note": "Primarily renal elimination"},
    "Cephalexin":                    {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal","No hepatic adjustment"), "note": "Primarily renal elimination"},
    "Gentamicin":                    {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal (renal)","Primarily renal — no hepatic adjustment; monitor nephrotoxicity"), "note": "Primarily renal — ototoxic + nephrotoxic"},
    "Amikacin":                      {"A": ("Normal","No adjustment"), "B": ("Normal","No adjustment"), "C": ("Normal (renal)","Primarily renal — no hepatic adjustment; monitor nephrotoxicity"), "note": "Primarily renal — ototoxic + nephrotoxic"},

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


# ═══════════════════════════════════════════════════════════════════════
# ENGINE 4 — Combination Therapy Suggester
# IDSA AMR 2025 | WHO Priority Pathogens | ESCAPE organisms
# ═══════════════════════════════════════════════════════════════════════
COMBINATION_THERAPY: Dict[str, Dict] = {
    "CRAB": {
        "title": "Carbapenem-Resistant A. baumannii (CRAB)",
        "urgency": "CRITICAL",
        "options": [
            {"combo": "Ampicillin-Sulbactam (high-dose 9g q8h) + Colistin", "evidence": "★★★",
             "indication": "Sulbactam has intrinsic activity vs A. baumannii — first-line combination",
             "caution": "", "ref": "ATTACK trial 2023 | IDSA 2025"},
            {"combo": "Cefiderocol ± Sulbactam", "evidence": "★★★",
             "indication": "Novel siderophore cephalosporin — active against CRAB if susceptible",
             "caution": "", "ref": "CREDIBLE-CR trial | IDSA 2025"},
            {"combo": "Colistin + Meropenem (2g q8h extended infusion 3h)", "evidence": "★★",
             "indication": "When novel agents unavailable — carbapenem synergy",
             "caution": "CAUTION: Monitor renal function closely", "ref": "IDSA 2025"},
            {"combo": "Colistin + Rifampicin + Meropenem (Triple)", "evidence": "★★",
             "indication": "XDR CRAB — triple therapy as last resort",
             "caution": "CAUTION: Monitor LFTs (Rifampicin)", "ref": "AIDA trial | IDSA 2025"},
        ]
    },
    "CRPA": {
        "title": "Carbapenem-Resistant Pseudomonas aeruginosa (CRPA)",
        "urgency": "CRITICAL",
        "options": [
            {"combo": "Ceftolozane-Tazobactam + Amikacin", "evidence": "★★★",
             "indication": "If Ceftolozane-Taz susceptible — preferred for CRPA",
             "caution": "", "ref": "IDSA AMR 2025"},
            {"combo": "Aztreonam + Ceftazidime-Avibactam", "evidence": "★★★",
             "indication": "MBL/NDM-producing CRPA — complementary beta-lactam mechanism",
             "caution": "Susceptibility testing for combination required", "ref": "IDSA 2025"},
            {"combo": "Cefiderocol monotherapy", "evidence": "★★",
             "indication": "XDR CRPA — if no other options available",
             "caution": "", "ref": "IDSA 2025"},
            {"combo": "Colistin + Meropenem (extended infusion)", "evidence": "★★",
             "indication": "When novel agents unavailable",
             "caution": "CAUTION: Mandatory renal monitoring", "ref": "IDSA 2025"},
        ]
    },
    "CRE": {
        "title": "Carbapenem-Resistant Enterobacterales (CRE)",
        "urgency": "CRITICAL",
        "options": [
            {"combo": "Ceftazidime-Avibactam", "evidence": "★★★",
             "indication": "KPC-producing CRE — first-line therapy",
             "caution": "", "ref": "RECAPTURE trial | IDSA 2025"},
            {"combo": "Meropenem-Vaborbactam", "evidence": "★★★",
             "indication": "KPC-producing CRE — alternative to Ceft-Avib",
             "caution": "", "ref": "TANGO-II trial | IDSA 2025"},
            {"combo": "Ceftazidime-Avibactam + Aztreonam", "evidence": "★★★",
             "indication": "MBL-producing CRE (NDM, VIM, IMP) — synergistic combination",
             "caution": "", "ref": "IDSA 2025"},
            {"combo": "Colistin + Meropenem high-dose (2g q8h 3h infusion)", "evidence": "★★",
             "indication": "When novel agents unavailable — heteroresistance approach",
             "caution": "CAUTION: Nephrotoxicity risk", "ref": "IDSA 2025"},
        ]
    },
    "MRSA": {
        "title": "Methicillin-Resistant S. aureus (MRSA)",
        "urgency": "HIGH",
        "options": [
            {"combo": "Vancomycin — AUC/MIC target 400-600", "evidence": "★★★",
             "indication": "MRSA bacteremia | endocarditis | pneumonia — first-line",
             "caution": "TDM mandatory: AUC/MIC-guided (not trough-only)", "ref": "IDSA MRSA 2011 (updated 2025)"},
            {"combo": "Daptomycin (8-10 mg/kg) + Ceftaroline", "evidence": "★★★",
             "indication": "Persistent MRSA bacteremia | refractory endocarditis",
             "caution": "Daptomycin INEFFECTIVE for pneumonia (inactivated by surfactant)", "ref": "IDSA 2025"},
            {"combo": "Vancomycin + Rifampicin", "evidence": "★★★",
             "indication": "Biofilm infections: prosthetic joint, CIED, vascular graft",
             "caution": "NEVER use Rifampicin as monotherapy — rapid resistance", "ref": "IDSA 2025"},
            {"combo": "Linezolid 600mg q12h", "evidence": "★★★",
             "indication": "MRSA pneumonia — superior to Vancomycin (ZEPHyR trial)",
             "caution": "Avoid >2 weeks | Weekly CBC monitoring | Serotonin syndrome risk", "ref": "ZEPHyR trial 2012 | IDSA 2025"},
            {"combo": "AVOID: Vancomycin + Piperacillin-Tazobactam", "evidence": "AVOID",
             "indication": "Contraindicated combination — increased AKI without efficacy benefit",
             "caution": "NINJA trial 2020: increased nephrotoxicity", "ref": "NINJA trial 2020"},
        ]
    },
    "VRE": {
        "title": "Vancomycin-Resistant Enterococcus (VRE)",
        "urgency": "HIGH",
        "options": [
            {"combo": "Linezolid 600mg q12h", "evidence": "★★★",
             "indication": "VRE — drug of choice for serious infections",
             "caution": "Weekly CBC monitoring; myelosuppression risk", "ref": "IDSA 2025"},
            {"combo": "Daptomycin (8-12 mg/kg) + Ampicillin", "evidence": "★★★",
             "indication": "VRE bacteremia | endocarditis — Ampicillin restores Daptomycin activity even for VRE",
             "caution": "Weekly CK monitoring", "ref": "IDSA 2025 | Synergy studies"},
            {"combo": "Daptomycin high-dose (≥10 mg/kg) monotherapy", "evidence": "★★",
             "indication": "VRE bacteremia when Ampicillin not available",
             "caution": "Monitor CK weekly", "ref": "IDSA 2025"},
        ]
    },
    "ESBL": {
        "title": "ESBL-Producing Enterobacterales",
        "urgency": "MODERATE",
        "options": [
            {"combo": "Ertapenem (definitive therapy)", "evidence": "★★★",
             "indication": "ESBL UTI/intraabdominal — carbapenem-sparing for bacteremia (if MIC allows)",
             "caution": "", "ref": "IDSA 2025"},
            {"combo": "Meropenem (severe / bacteremia)", "evidence": "★★★",
             "indication": "ESBL bacteremia — superior to Pip-Taz (MERINO trial)",
             "caution": "", "ref": "MERINO trial 2018 | IDSA 2025"},
            {"combo": "AVOID: Piperacillin-Tazobactam for bacteremia", "evidence": "AVOID",
             "indication": "Inferior to carbapenems for ESBL bacteremia — inoculum effect",
             "caution": "MERINO trial 2018: Pip-Taz inferior for ESBL bloodstream infections", "ref": "MERINO trial 2018"},
        ]
    },
}

def get_combination_therapy(phenotypes: List[Dict]) -> List[Dict]:
    """Combination therapy suggestions based on detected phenotypes — IDSA AMR 2025"""
    results  = []
    ph_names = [p.get("phenotype", "") for p in phenotypes]
    for ph in ["CRAB", "CRPA", "CRE", "MRSA", "VRE", "ESBL", "MDR"]:
        if ph in ph_names and ph in COMBINATION_THERAPY:
            results.append({"phenotype": ph, "data": COMBINATION_THERAPY[ph]})
    return results


# ═══════════════════════════════════════════════════════════════════════
# ENGINE 5 — De-escalation Advisor
# WHO AWaRe 2025 | IDSA Stewardship 2025
# ═══════════════════════════════════════════════════════════════════════
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




# =========================================================
# MODULE 1 — Resistance Phenotype Engine
# يحدد: ESBL / CRE / MRSA / VRE / MDR / XDR / PDR
# المرجع: EUCAST 2026, CLSI M100 2026, CDC/ECDC 2017
# =========================================================
PHENOTYPE_RULES = {
    "MRSA": {
        "organisms": ["Staphylococcus aureus","MRSA"],
        "markers":   [("Oxacillin","R"), ("Cefoxitin","R")],
        "fallback":  [("Vancomycin","S"), ("Linezolid","S")],  # حساس لهم → likely MRSA
        "icon":  "🔴",
        "label": "MRSA — Methicillin-Resistant S. aureus",
        "detail": "مقاوم للـ Methicillin (mecA gene). جميع البيتا-لاكتام غير فعالة.",
        "action": "Vancomycin أو Linezolid حسب الشدة. بروتوكول عزل إلزامي.",
        "isolation": True,
    },
    "VRE": {
        "organisms": ["Enterococcus faecalis","Enterococcus faecium","VRE"],
        "markers":   [("Vancomycin","R")],
        "icon":  "🔴",
        "label": "VRE — Vancomycin-Resistant Enterococcus",
        "detail": "مقاوم للـ Vancomycin (vanA/vanB gene). خطر انتشار في المستشفى.",
        "action": "Linezolid أو Daptomycin. عزل فوري. إبلاغ مكافحة العدوى.",
        "isolation": True,
    },
    "CRE": {
        "organisms": ["Klebsiella spp.","E. coli","Escherichia coli",
                      "Enterobacter cloacae","Enterobacter spp.",
                      "Proteus mirabilis","Klebsiella pneumoniae",
                      "Serratia marcescens","Citrobacter spp."],
        "markers":   [("Imipenem/Cilastatin","R"),("Meropenem","R"),("Ertapenem","R")],
        "require_any": 1,  # واحد كافٍ
        "icon":  "🚨",
        "label": "CRE — Carbapenem-Resistant Enterobacteriaceae",
        "detail": "مقاوم للكاربابينيم — أخطر أنماط المقاومة في العالم.",
        "action": "Colistin + Fosfomycin أو Ceftazidime-Avibactam. أرسل للمختبر المرجعي فوراً.",
        "isolation": True,
    },
    "CRAB": {
        "organisms": ["Acinetobacter baumannii"],
        "markers":   [("Imipenem/Cilastatin","R"),("Meropenem","R")],
        "require_any": 1,
        "icon":  "🚨",
        "label": "CRAB — Carbapenem-Resistant Acinetobacter baumannii",
        "detail": "XDR/PDR Acinetobacter — أصعب الكائنات علاجاً في ICU.",
        "action": "Colistin ± Rifampicin. بروتوكول ICU خاص. استشارة معدية.",
        "isolation": True,
    },
    "CRPA": {
        "organisms": ["Pseudomonas aeruginosa"],
        "markers":   [("Imipenem/Cilastatin","R"),("Meropenem","R"),
                      ("Piperacillin + Tazobactam","R"),("Ceftazidime","R")],
        "require_any": 2,
        "icon":  "🔴",
        "label": "CRPA — Carbapenem-Resistant Pseudomonas aeruginosa",
        "detail": "مقاوم للكاربابينيم مع مقاومة متعددة. خيارات علاجية محدودة.",
        "action": "Colistin أو Ceftolozane-Tazobactam. Combination therapy مطلوبة.",
        "isolation": True,
    },
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


# =========================================================
# MODULE 2 — AST Quality Control Checker
# يتحقق من تناقضات منطقية في نتائج S/I/R
# المرجع: EUCAST Expert Rules v3.3 + CLSI M100
# =========================================================
AST_QC_RULES = [
    # ── Impossible combinations (EUCAST Expert Rules) ──────────────────
    {
        "id": "QC001",
        "desc": "Vancomycin-S مع Colistin-S في نفس الوقت غير منطقي لغرام سالب",
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Acinetobacter baumannii","Proteus mirabilis"],
        "condition": lambda s: s.get("Vancomycin")=="S" and s.get("Colistin")=="S",
        "severity": "error",
        "message": "Vancomycin لا يعمل على الغرام سالبات أبداً — نتيجة Vancomycin-S خاطئة.",
        "fix": "راجع نتيجة Vancomycin — يجب أن تكون R (مقاوم طبيعياً).",
    },
    {
        "id": "QC002",
        "desc": "Nitrofurantoin-S مع Proteus — مقاومة طبيعية",
        "organisms": ["Proteus mirabilis","Proteus spp."],
        "condition": lambda s: s.get("Nitrofurantoin")=="S",
        "severity": "error",
        "message": "Proteus mirabilis مقاوم طبيعياً لـ Nitrofurantoin (intrinsic) — EUCAST.",
        "fix": "نتيجة Nitrofurantoin-S لـ Proteus خاطئة — يجب أن تكون R.",
    },
    {
        "id": "QC003",
        "desc": "Carbapenem-S مع Colistin-R وجميع الخيارات R — غير منطقي",
        "organisms": [],  # ينطبق على الكل
        "condition": lambda s: (
            any(s.get(d)=="S" for d in ["Imipenem/Cilastatin","Meropenem"]) and
            s.get("Colistin")=="R" and
            sum(1 for v in s.values() if v=="R") >= 6
        ),
        "severity": "warning",
        "message": "Carbapenem-S مع Colistin-R ومقاومة واسعة — تحقق من هوية الكائن.",
        "fix": "تأكد من صحة التعريف (identification) — النمط غير معتاد.",
    },
    {
        "id": "QC004",
        "desc": "Cephalosporin-S مع Carbapenem-R في Enterobacteriaceae",
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis","Enterobacter cloacae"],
        "condition": lambda s: (
            any(s.get(d)=="S" for d in ["Ceftriaxone","Cefotaxime","Cefepime"]) and
            any(s.get(d)=="R" for d in ["Imipenem/Cilastatin","Meropenem","Ertapenem"])
        ),
        "severity": "warning",
        "message": "Carbapenem-R مع Cephalosporin-S — نمط نادر يستدعي التحقق.",
        "fix": "أعد الاختبار. قد يكون خطأ في القراءة أو نمط OXA-48 غير نمطي.",
    },
    {
        "id": "QC005",
        "desc": "Linezolid-R في Staphylococcus — نادر جداً",
        "organisms": ["Staphylococcus aureus","MRSA"],
        "condition": lambda s: s.get("Linezolid")=="R",
        "severity": "warning",
        "message": "Linezolid-R في S. aureus نادر جداً — تأكيد ضروري.",
        "fix": "أعد الاختبار بطريقة مختلفة (Etest أو Broth microdilution).",
    },
    {
        "id": "QC006",
        "desc": "Cephalosporin-S مع ESBL-phenotype — تناقض",
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis"],
        "condition": lambda s: (
            any(s.get(d)=="R" for d in ["Ceftriaxone","Cefotaxime"]) and
            any(s.get(d)=="S" for d in [
                "Cefuroxime","Cefuroxime sodium","Cephalexin","Cefaclor",
                "Cefadroxil","Cefixime","Cefoperazone","Cefoperazone + Sulbactam"
            ]) and
            # Only flag if a 2nd/3rd-gen is S while 3rd-gen is R (true contradiction)
            # Ignore if ALL tested cephalosporins are R (consistent ESBL — no flag)
            not all(
                s.get(d) in ("R", None)
                for d in ["Cefuroxime","Cefuroxime sodium","Cephalexin","Cefepime",
                           "Ceftazidime","Cefotaxime","Cefixime","Cefoperazone"]
                if s.get(d) is not None
            )
        ),
        "severity": "warning",
        "message": "Ceftriaxone-R مع Cephalosporin-S — Inoculum Effect محتمل في ESBL.",
        "fix": "ESBL Inoculum Effect: الحساسية في الـ Lab قد لا تنعكس في الجسم — تجنب جميع Cephalosporins حتى لو S في الـ AST (EUCAST 2026).",
    },
    {
        "id": "QC007",
        "desc": "Vancomycin-S في Gram-negatives",
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Acinetobacter baumannii","Proteus mirabilis",
                      "Enterobacter cloacae","Stenotrophomonas maltophilia"],
        "condition": lambda s: s.get("Vancomycin")=="S",
        "severity": "error",
        "message": "Vancomycin غير فعال على الغرام سالبات — نتيجة خاطئة.",
        "fix": "احذف نتيجة Vancomycin — لا تُختبر على الغرام سالبات.",
    },
    {
        "id": "QC008",
        "desc": "Colistin-S في Proteus — مقاومة طبيعية",
        "organisms": ["Proteus mirabilis","Proteus spp."],
        "condition": lambda s: s.get("Colistin")=="S",
        "severity": "error",
        "message": "Proteus مقاوم طبيعياً لـ Colistin (intrinsic) — EUCAST.",
        "fix": "نتيجة Colistin-S لـ Proteus خاطئة — يجب أن تكون R.",
    },
]

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
                issues.append({
                    "id":       rule["id"],
                    "severity": rule["severity"],
                    "message":  rule["message"],
                    "fix":      rule["fix"],
                })
        except Exception:
            continue
    return issues


# =========================================================
# MODULE 3 — Smart Antibiotic Ranking
# يرتب الأدوية الـ Sensitive حسب الأولوية السريرية
# =========================================================
RANKING_WEIGHTS = {
    "aware_score":     {"Access": 3, "Watch": 2, "Reserve": 1, None: 0},
    "route_score":     {"oral": 2, "iv": 1},
    "specimen_match":  2,   # bonus لو الدواء له specimen_note للعينة دي
    "priority_bonus":  lambda p: max(0, 6 - p),  # priority 1 → +5, priority 5 → +1
}

def rank_sensitive_antibiotics(
    allowed:      List[Dict],
    culture_type: str,
    organism:     str,
    sir_map:      Dict[str, str],
    phenotypes:   List[Dict],
) -> List[Dict]:
    """
    يرتب الأدوية المسموحة حسب:
    1. Culture result (S أفضل من I)
    2. AWaRe (Access > Watch > Reserve)
    3. Route (Oral preferred)
    4. Specimen appropriateness
    5. Priority في الـ guidelines
    """
    ph_names = [p["phenotype"] for p in phenotypes]

    scored = []
    for item in allowed:
        score = 0
        name  = item.get("name", "")

        # Culture result
        sir = sir_map.get(name)
        if sir == "S":
            score += 4
        elif sir == "I":
            score += 1

        # AWaRe
        score += RANKING_WEIGHTS["aware_score"].get(item.get("aware"), 0)

        # Route
        if item.get("high_po"):
            score += RANKING_WEIGHTS["route_score"]["oral"]
        else:
            score += RANKING_WEIGHTS["route_score"]["iv"]

        # Specimen match
        if (item.get("specimen_notes") or {}).get(culture_type):
            score += RANKING_WEIGHTS["specimen_match"]

        # Priority bonus
        p = item.get("priority", 5)
        score += RANKING_WEIGHTS["priority_bonus"](p)

        # Phenotype penalty: CRE/CRAB → penalize cephalosporins
        if any(ph in ph_names for ph in ["CRE","CRAB","CRPA"]):
            cls = item.get("class","").lower()
            if "cephalosporin" in cls and sir != "S":
                score -= 3
        # Extra penalty for Reserve drugs
        if item.get("aware") == "Reserve" and sir == "S":
            score -= 1  # slight penalty — prefer Access/Watch

        scored.append({**item, "_score": score, "_sir": sir or "—"})

    return sorted(scored, key=lambda x: x["_score"], reverse=True)


# =========================================================
# MODULE 4 — Infection Syndrome Module
# يربط Specimen + Organism + Phenotype بـ clinical syndrome
# =========================================================
INFECTION_SYNDROMES = {
    ("Urine", None): {
        "syndrome":  "Urinary Tract Infection (UTI)",
        "classify":  lambda age, is_preg, is_cath: (
            "Complicated UTI" if (is_cath or age > 65) else
            "Pregnancy-associated UTI" if is_preg else
            "Uncomplicated UTI"
        ),
        "first_choice": ["Nitrofurantoin","Fosfomycin","Trimethoprim/Sulfamethoxazole"],
        "duration": {"Uncomplicated UTI": "3-5 أيام", "Complicated UTI": "7-14 يوم",
                     "Pregnancy-associated UTI": "7 أيام"},
        "escalation": "لو فشل الخط الأول أو CrCl < 30 → Ciprofloxacin أو Cefixime",
        "culture_threshold": "≥ 10³ CFU/mL للأعراض، ≥ 10⁵ بدون أعراض",
    },
    ("Blood", None): {
        "syndrome":  "Bloodstream Infection (BSI) / Bacteremia",
        "classify":  lambda age, is_preg, is_cath: (
            "Catheter-Related BSI (CRBSI)" if is_cath else "Community/Hospital BSI"
        ),
        "first_choice": ["Ceftriaxone","Piperacillin-Tazobactam","Meropenem (MDR/severe)"],
        "duration": {"Community/Hospital BSI": "14-21 يوم (حسب المصدر)",
                     "Catheter-Related BSI (CRBSI)": "14 يوم + إزالة الكاتيتر"},
        "escalation": "MDR/XDR → Meropenem ± Amikacin. Endocarditis اشتباه → اتشاور",
        "culture_threshold": "2 sets blood cultures قبل المضاد",
    },
    ("Sputum", None): {
        "syndrome":  "Respiratory Tract Infection",
        "classify":  lambda age, is_preg, is_cath: (
            "HAP/VAP" if is_cath else ("Severe CAP" if age > 65 else "CAP")
        ),
        "first_choice": ["Amoxicillin + Clavulanic acid","Levofloxacin","Azithromycin"],
        "duration": {"CAP": "5-7 أيام", "Severe CAP": "7-10 أيام (>65y)", "HAP/VAP": "7-14 يوم"},
        "escalation": "Pseudomonas/Acinetobacter → anti-pseudomonal mandatory",
        "culture_threshold": "≥ 10⁵ CFU/mL BAL أو ≥ 10⁶ في Sputum",
    },
    ("Wound Swab", None): {
        "syndrome":  "Skin & Soft Tissue Infection (SSTI)",
        "classify":  lambda age, is_preg, is_cath: "SSTI",
        "first_choice": ["Cephalexin","Amoxicillin + Clavulanic acid"],
        "duration": {"SSTI": "5-10 أيام حسب الشدة"},
        "escalation": "MRSA اشتباه → TMP/SMX أو Doxycycline. Diabetic foot → broader coverage",
        "culture_threshold": "أخذ عينة من العمق — لا من السطح",
    },
    ("Pus", None): {
        "syndrome":  "Abscess / Deep Infection",
        "classify":  lambda age, is_preg, is_cath: "Abscess",
        "first_choice": ["Amoxicillin + Clavulanic acid","Metronidazole"],
        "duration": {"Abscess": "Drainage + 5-7 أيام"},
        "escalation": "Intra-abdominal → Metronidazole إلزامي. Carbapenem لو ESBL",
        "culture_threshold": "Drainage culture — أدق من swab",
    },
    ("Stool", None): {
        "syndrome":  "Gastrointestinal Infection",
        "classify":  lambda age, is_preg, is_cath: (
            "Severe GI / Immunocompromised" if (age < 2 or age > 65 or is_preg) else "Mild-Moderate GI Infection"
        ),
        "first_choice": ["Azithromycin", "Ciprofloxacin (if susceptible)"],
        "duration": {
            "Mild-Moderate GI Infection": "Supportive care — antibiotics usually NOT needed",
            "Severe GI / Immunocompromised": "3-5 days (Azithromycin/Cipro)",
        },
        "escalation": "C. diff → Vancomycin PO / Fidaxomicin. Salmonella typhi → 7-14d Ceftriaxone.",
        "culture_threshold": "Stool culture for severe/immunocompromised cases only",
    },
    ("Stool Culture", None): {
        "syndrome":  "Gastrointestinal Infection",
        "classify":  lambda age, is_preg, is_cath: (
            "Severe GI / Immunocompromised" if (age < 2 or age > 65 or is_preg) else "Mild-Moderate GI Infection"
        ),
        "first_choice": ["Azithromycin", "Ciprofloxacin (if susceptible)"],
        "duration": {"GI Infection": "Supportive care preferred — antibiotics for severe cases only"},
        "escalation": "C. diff → Vancomycin/Fidaxomicin | Salmonella typhi → 7-14d",
        "culture_threshold": "Culture for severe/immunocompromised only",
    },
    ("CSF", None): {
        "syndrome":  "Central Nervous System Infection (Meningitis)",
        "classify":  lambda age, is_preg, is_cath: "Bacterial Meningitis",
        "first_choice": ["Ceftriaxone","Meropenem"],
        "duration": {"Bacterial Meningitis": "10-14 يوم (7 لـ N. meningitidis)"},
        "escalation": "ابدأ تجريبياً فوراً ولا تنتظر culture. Dexamethasone قبل المضاد",
        "culture_threshold": "CSF culture + Gram stain + Ag testing",
    },
}

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
    # Keyword fallback
    if not syndrome_data:
        spec_l = specimen.lower()
        fallback_map = {
            "urine": "Urine", "culture": None, "stool": "Stool",
            "stool culture": "Stool", "fecal": "Stool", "rectal": "Stool",
            "blood": "Blood", "blood culture": "Blood",
            "sputum": "Sputum", "respiratory": "Sputum", "bal": "Sputum",
            "csf": "CSF", "cerebrospinal": "CSF",
            "wound": "Wound Swab", "swab": "Wound Swab",
            "pus": "Pus", "abscess": "Pus", "tissue": "Wound Swab",
        }
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



# =========================================================
# أدوات رسم الصورة
# =========================================================
def _draw_rbox(draw: Any, box: tuple, bg: tuple, bd: tuple,
               radius: int = 14, width: int = 3) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=bg, outline=bd, width=width)

def _tw(draw: Any, text: str, font: Any) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception:
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
        return result

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
            # Clean up extra spaces
            result = re.sub(r'\s+', ' ', result).strip()
        return result

    # ── AWaRe helpers ────────────────────────────────────────────────────
    AWARE_CLR  = {"Access": "#1e8449", "Watch": "#b7770d", "Reserve": "#922b21"}
    AWARE_PILL = {"Access": "background:#1e8449;color:#fff",
                  "Watch":  "background:#b7770d;color:#fff",
                  "Reserve":"background:#922b21;color:#fff"}
    AWARE_CARD = {"Access": "background:#eafaf1;border:0.8pt solid #1e8449",
                  "Watch":  "background:#fef9e7;border:0.8pt solid #b7770d",
                  "Reserve":"background:#fdf2f2;border:0.8pt solid #922b21"}
    TIER_LBL   = {"Access": "First-line", "Watch": "Alternative", "Reserve": "Reserve / MDR"}

    ranked   = sorted(allowed,
                      key=lambda d: ({"Access":0,"Watch":1,"Reserve":2}.get(d.get("aware"),3),
                                     d.get("priority",99)))
    mdr_class = mdr_result.get("level","") if mdr_result else ""
    ph_labels = [p.get("phenotype","") for p in phenotypes]
    esbl_prob = esbl_result.get("probability","low")
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
"""

    def hdr_html(page_lbl: str) -> str:
        mdr_pills = ""
        if mdr_class: mdr_pills += pill(mdr_class, "background:#922b21;color:#fff")+" "
        for ph in ph_labels[:3]: mdr_pills += pill(ph, "background:#6e2fa0;color:#fff")+" "
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
    <b style="font-size:10pt">{page_lbl}</b><br>
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
            _rnl  = _esc(_rd.get("renal_note","")) if is_renal else ""
            if _tlbl != prev_tier:
                H.append(f'<div class="tier-sep" style="color:{_clr};border-color:{_clr}">{_tlbl}</div>')
                prev_tier = _tlbl
            H.append(
                f'<div class="ranked-row" style="{_ccss};border-radius:1.5mm;padding:1mm 2.5mm;margin:0.3mm 0">'
                '<div style="flex:1">'
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
                'border-radius:1.5mm;font-size:8pt">'
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

    # ── DOSE ADJUSTMENT / USE WITH CAUTION — full detailed section ──────
    if warned:
        H.append('<div class="sec-ttl" style="margin-top:0.6mm;color:#b7770d;border-bottom-color:#b7770d">'
                 f'{_T["dose_adj"]}</div>')
        if is_renal:
            H.append('<div style="font-size:8.5pt;color:#888;margin-bottom:1mm">'
                     f'{_T["renal_label"]} = {cl_cr:.1f} ml/min</div>')
        for _wd in warned:
            _wname = _esc(_wd.get("name",""))
            _waw   = _esc(_wd.get("aware",""))
            _wreason = _wd.get("warning_reason","")
            _waw_style = {
                "Access":  "background:#1e8449;color:#fff",
                "Watch":   "background:#b7770d;color:#fff",
                "Reserve": "background:#922b21;color:#fff",
            }.get(_wd.get("aware",""), "background:#888;color:#fff")
            H.append(
                '<div style="margin:0.3mm 0;padding:0.8mm 2.5mm;border-radius:2mm;'
                'background:#fef9e7;border:1pt solid #b7770d;page-break-inside:avoid">'
                '<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<b style="font-size:10.5pt;color:#7d6608">{_wname}</b>'
                '<span style="padding:0.2mm 2mm;border-radius:2mm;font-size:8pt;'
                f'font-weight:bold;{_waw_style}">{_waw}</span>'
                '</div>'
            )
            # Reason-specific detail
            if _wreason == "renal_adjustment":
                _rn = _esc(_wd.get("renal_note","-"))
                _rl = _wd.get("renal_limit","-")
                H.append(
                    '<div style="font-size:9pt;color:#7d6608;margin-top:0.5mm">'
                    f'{_T["renal_adj"]} {_rl} ml/min</div>'
                    f'<div style="font-size:8.5pt;color:#555;margin-top:0.3mm">{_rn}</div>'
                )
            elif _wreason == "intermediate_culture":
                H.append(
                    '<div style="font-size:9pt;color:#7d6608;margin-top:0.5mm">'
                    '⚠ Intermediate (I) in culture result — use only if no better option</div>'
                )
            elif _wreason == "esbl_bli_uti_only":
                _esbl_txt = (_wd.get("esbl_note_en") if _EN and _wd.get("esbl_note_en")
                             else _wd.get("esbl_note","ESBL organism — BLI combo for uncomplicated UTI only"))
                _en = _esc(_esbl_txt)
                H.append(
                    f'<div style="font-size:9pt;color:#7d6608;margin-top:0.5mm">{_en}</div>'
                )
            else:
                _rn = _esc(_wd.get("renal_note","") or _wd.get("note",""))
                if _rn:
                    H.append(
                        f'<div style="font-size:9pt;color:#555;margin-top:0.5mm">{_rn}</div>'
                    )
            H.append('</div>')

    # ── Interactions (compact) ─────────────────────────────────────────
    if interactions:
        H.append(f'<div class="sec-ttl" style="margin-top:0.6mm">{_T["interactions"]}</div>'
                 '<div class="alert al-warn">'
                 + '<br>'.join(f'<span style="font-size:9pt">{_esc(ia)}</span>'
                               for ia in interactions[:4])
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
            H.append(f'<div class="alert al-info" style="font-size:8pt;margin-top:0.5mm">📋 {_esc(d["notes"][:160])}</div>')
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
            "ABU_NO_TREAT":  ("al-warn",   "ABU — Do NOT Treat (IDSA 2019)"),
            "ABU_TREAT":     ("al-danger", "ABU — TREAT (High-risk)"),
            "MW_REJECT":     ("al-danger", "Specimen REJECTED — Repeat"),
            "MW_ADEQUATE":   ("al-info",   "Murray-Washington: Adequate"),
            "SIRS_HIGH":     ("al-danger", "SIRS ≥3 — Sepsis Probable"),
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
        H.append('<div class="sec-ttl">Pathogenicity Assessment</div>')
        H.append('<div class="alert al-info" style="font-size:9pt">Run Pathogenicity Assessment in the app to see score</div>')
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
    except Exception:
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
                except Exception:
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
                            except Exception:
                                continue
            except Exception:
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
        except Exception:
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
        except Exception:
            return str(text)

    def rbox(draw, box, bg, bd, radius=14, width=3):
        draw.rounded_rectangle(
            [box[0], box[1], box[2], box[3]],
            radius=radius * S, fill=bg, outline=bd, width=width * S
        )

    def text_wrap(draw, x, y, text, font, fill, max_w, gap=4):
        text = _fix_arabic(text)   # reshape Arabic before wrapping
        words = text.split()
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip()
            if tw(draw, trial, font) <= max_w:
                cur = trial
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        lh = fh(font) + gap * S
        for line in lines:
            draw.text((x, y), line, fill=fill, font=font)
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
                           fi, name_color, x2 - x1 - 26*S, gap=5)

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
    p_lines.append(f"Sex / Age:     {'Male' if sex == 'Male' else 'Female'}, {age} yrs")
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
    if is_preg and age >= 18:
        alerts.append("Pregnancy: verify fetal safety")

    ay = 72*S + 12*S + fh(F_SUBTITL) + 8*S
    alert_max_w = AB[2] - AB[0] - 22*S
    for al in alerts[:6]:
        if ay + fh(F_SMALL) + 4*S > AB[3] - 6*S:
            break
        ay = text_wrap(draw, AB[0]+12*S, ay, f"• {al}",
                       F_SMALL, AB_TXT, alert_max_w, gap=4)
        ay += 2*S

    # ── 5. ROW 2: Specimen | Microscopic Exam | First-Line ────────────────────
    R2_Y1 = 210*S
    R2_Y2 = 310*S
    r2w   = (W - 2*P - 2*G) // 3

    # Specimen box — no title, direct fields
    # Specimen label — add collection method for Urine
    _spec_label = specimen
    if "urine" in specimen.lower():
        _spec_label = f"{specimen} / Mid-Stream"
    spec_items = [
        f"Specimen:      {_spec_label}",
        "Method:        Culture & Sensitivity",
        f"Condition:     {culture_condition}",
    ]
    if microbiologist:
        spec_items.append(f"Microbiologist: Dr/ {microbiologist}")
    micro_items = [
        f"Pus Cells: {pus_cells if pus_cells else chr(8212)} /HPF",
        f"RBCs:      {rbcs if rbcs else chr(8212)} /HPF",
    ]
    fl_items = first_line[:4] or ["—"]

    r2_data = [
        ("",                   spec_items,  SPEC_BD,  SPEC_BG,  ""),
        ("MICROSCOPIC EXAM",   micro_items, MICRO_BD, MICRO_BG, "🔬"),
        ("FIRST-LINE OPTIONS", fl_items,    FL_BD,    FL_BG,    "📋"),
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
                           F_SMALL, DARK, bx2-bx1-24*S, gap=4)

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
                       F_SMALL, DARK, fx2-fx1-18*S, gap=3)

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
                       F_SMALL, DARK, fx2-fx1-18*S, gap=3)
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
          f"Age      : {age} years",
          f"Gender   : {sex}",
          f"Weight   : {weight} kg",
          f"Renal    : {'IMPAIRED' if is_renal else 'Normal'}"]
    if is_renal:
        L.append(f"CrCl     : {cl_cr:.1f} ml/min ({get_renal_severity(cl_cr)})")
    L.append(f"Hepatic  : {'IMPAIRED' if is_hepatic else 'Normal'}")
    if sex == "Female" and age >= 18:
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
            "child": [], "organism": [], "other": [],
        }
        for item in banned:
            grouped.setdefault(item["category"], []).append(item)
        labels = [
            ("resistant", "[A] RESISTANT IN CULTURE"),
            ("renal",     "[B] CONTRAINDICATED — RENAL IMPAIRMENT"),
            ("pregnancy", "[C] CONTRAINDICATED — PREGNANCY"),
            ("child",     "[D] NOT SUITABLE FOR AGE"),
            ("organism",  f"[E] INEFFECTIVE FOR {organism}"),
            ("other",     "[F] OTHER CONTRAINDICATIONS"),
        ]
        for cat, heading in labels:
            if grouped.get(cat):
                L += [f"\n{heading}", sep2]
                for b in grouped[cat]:
                    L.append(f"- {b['name']} — {b['reason_short']}")
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





# =========================================================
# واجهة التطبيق الرئيسية
# =========================================================
if not st.session_state.authenticated:
    email_input = show_login_page()
    if email_input:
        if check_subscription(email_input):
            st.session_state.authenticated = True
            st.session_state.last_activity = time.time()
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()
    st.stop()

handle_session_timeout()
render_top_bar()

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
        with st.spinner("🔍 جاري تحليل صورة التقرير..."):
            try:
                payload = extract_all_data_cached(file_bytes)
                st.session_state.ocr_data           = payload
                st.session_state.last_file_hash     = file_hash
                st.session_state.sir_map_edited     = dict(payload["sir_map"])
                # الاسم يُدخل يدوياً — لا نغير ما أدخله المستخدم عند تحميل صورة جديدة
                st.session_state.patient_name_ocr   = ""
                # patient_name_final محفوظ من الجلسة السابقة (لا نمسحه)
            except Exception as e:
                st.error(f"تعذر تحليل الصورة: {e}")
                st.stop()

    payload        = st.session_state.ocr_data
    patient        = payload["patient"]
    drugs_from_ocr = payload["drugs"]
    raw_text       = payload["raw_text"]

    if not st.session_state.sir_map_edited and payload["sir_map"]:
        st.session_state.sir_map_edited = dict(payload["sir_map"])

    st.image(file_bytes, caption="Preview", use_container_width=True)

    with st.expander("📝 النص المستخرج من التقرير (OCR)", expanded=False):
        st.text_area("Extracted Text", raw_text, height=220, label_visibility="collapsed")

    col1, col2 = st.columns([1.05, 1.55], gap="large")

    # ─── العمود الأيسر ────────────────────────────────────────────────────────
    with col1:
        st.subheader("👤 Patient & Culture")

        # اسم المريض — إدخال يدوي فقط
        patient_name = st.text_input(
            "👤 اسم المريض / Patient Name",
            value=st.session_state.get("patient_name_final", ""),
            placeholder="أدخل اسم المريض",
            help="يظهر في التقرير وصورة الملخص.",
            key=f"pname_{file_hash[:8]}"
        )
        st.session_state.patient_name_final = patient_name.strip()

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

        organism_type = st.selectbox(
            "🦠 Organism",
            filtered_organisms,
            index=best_default_index(filtered_organisms, patient.get("Organism")),
            help=f"بكتيريا شائعة في عينة {culture_type}",
        )

        # ── حقول المزرعة والمجهر ──────────────────────────────────────────────
        st.divider()
        st.subheader("🔬 Culture & Microscopic Details")

        colony_count = st.text_input(
            "Colony Count (CFU/mL)",
            value=st.session_state.colony_count,
            placeholder="≥ 10^5 CFU/mL",
            key="colony_count_input"
        )
        st.session_state.colony_count = colony_count

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

        age = st.number_input("Age (years)", min_value=0, max_value=120,
                               value=safe_int(patient.get("Age"), 25))
        default_sex = patient.get("Sex") if patient.get("Sex") in ["Female", "Male"] else "Male"
        sex    = st.selectbox("Gender", ["Female", "Male"],
                              index=0 if default_sex == "Female" else 1)
        weight = st.number_input("Weight (kg)", min_value=5, max_value=300, value=70)

        st.divider()

        is_renal = st.checkbox("🚩 Renal Impairment")
        cl_cr    = 100.0
        if is_renal:
            s_cr  = st.number_input("Serum Creatinine (mg/dL)",
                                    min_value=0.1, max_value=20.0, value=1.0, step=0.1)
            cl_cr = calc_creatinine_clearance(age, weight, s_cr, sex)
            st.metric("CrCl (Cockcroft-Gault)", f"{cl_cr:.1f} ml/min",
                      delta=get_renal_severity(cl_cr),
                      delta_color="normal" if cl_cr >= 60 else ("off" if cl_cr >= 30 else "inverse"))

        is_hepatic = st.checkbox("🚩 Hepatic Impairment")
        is_preg    = False
        if sex == "Female" and 18 <= age <= 55:
            is_preg = st.checkbox("🤰 Patient is Pregnant")

        current_meds = st.multiselect("💊 Current Medications", COMMON_MEDS)

        # ─── New clinical/lab fields ──────────────────────────────────────────
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


    # ─── العمود الأيمن ────────────────────────────────────────────────────────
    with col2:
        st.subheader("💊 Antibiotic Analysis")

        # ══════════════════════════════════════════════════════
        # AST Input Panel — OCR + Manual Entry موحّد
        # ══════════════════════════════════════════════════════
        ocr_sir_map = payload["sir_map"]
        sir_options = ["S", "I", "R"]

        st.markdown("**📊 نتائج المزرعة — S / I / R**")
        st.caption("✅ من OCR تلقائياً — عدّل أي قيمة خطأ أو أضف مضاد فاته الـ OCR")

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

        # ── الأدوية المضافة يدوياً (فاتها OCR كلياً) ─────────────────
        manual_prev = [d for d in st.session_state.sir_map_edited.keys()
                       if d not in ocr_drugs]

        manual_extra = st.multiselect(
            "➕ أضف مضادات يدوياً (فاتها OCR كلياً)",
            options=[d for d in all_known if d not in ocr_drugs and d not in ocr_detected_no_sir],
            default=manual_prev,
            key=f"manual_drugs_{file_hash[:8]}",
            help="اختر الأدوية التي ظهرت في التقرير لكن OCR لم يكتشفها على الإطلاق",
        )

        # ── بناء القائمة الكاملة: OCR + Manual ───────────────────────
        all_drugs_to_show = ocr_drugs + [d for d in manual_extra if d not in ocr_drugs]

        # ── عرض SIR dropdown لكل دواء ─────────────────────────────────
        edited_sir: Dict[str, str] = {}

        # ── Deleted drugs (persisted per file) ───────────────────────────
        _del_key = f"deleted_drugs_{file_hash[:8]}"
        if _del_key not in st.session_state:
            st.session_state[_del_key] = set()

        if all_drugs_to_show:
            # OCR drugs أولاً
            if ocr_drugs:
                st.markdown("<small style='color:#555'>🔍 من OCR — اضغط ❌ لحذف مضاد:</small>",
                            unsafe_allow_html=True)
                for i in range(0, len(ocr_drugs), 3):
                    row_drugs = ocr_drugs[i: i + 3]
                    row_cols  = st.columns(3)
                    for col, drug in zip(row_cols, row_drugs):
                        if drug in st.session_state[_del_key]:
                            if col.button(f"↩️ {drug}", key=f"restore_{drug}_{file_hash[:8]}",
                                          help="استعادة المضاد"):
                                st.session_state[_del_key].discard(drug)
                                st.rerun()
                            continue
                        cur = st.session_state.sir_map_edited.get(drug, ocr_sir_map[drug])
                        if cur not in sir_options:
                            cur = "S"
                        label_icons = {"S": "🟢", "I": "🟡", "R": "🔴"}
                        _c1, _c2, _c3 = col.columns([4, 3, 1])
                        _c1.markdown(f"<small>{label_icons.get(cur,'')} **{drug}**</small>",
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

            # Manual drugs
            manual_new = [d for d in manual_extra if d not in ocr_drugs]
            if manual_new:
                st.markdown("<small style='color:#1a6b3a'>➕ مُضافة يدوياً:</small>",
                            unsafe_allow_html=True)
                for i in range(0, len(manual_new), 3):
                    row_drugs = manual_new[i: i + 3]
                    row_cols  = st.columns(3)
                    for col, drug in zip(row_cols, row_drugs):
                        if drug in st.session_state[_del_key]:
                            if col.button(f"↩️ {drug}", key=f"restore_m_{drug}_{file_hash[:8]}",
                                          help="استعادة المضاد"):
                                st.session_state[_del_key].discard(drug)
                                st.rerun()
                            continue
                        cur = st.session_state.sir_map_edited.get(drug, "S")
                        if cur not in sir_options:
                            cur = "S"
                        label_icons = {"S": "🟢", "I": "🟡", "R": "🔴"}
                        _c1, _c2, _c3 = col.columns([4, 3, 1])
                        _c1.markdown(f"<small>{label_icons.get(cur,'')} **{drug}**</small>",
                                     unsafe_allow_html=True)
                        new_val = _c2.selectbox(
                            "##",
                            options=sir_options,
                            index=sir_options.index(cur),
                            key=f"sir_manual_{drug}_{file_hash[:8]}",
                            label_visibility="collapsed"
                        )
                        if _c3.button("❌", key=f"del_m_{drug}_{file_hash[:8]}",
                                      help=f"حذف {drug}"):
                            st.session_state[_del_key].add(drug)
                            st.rerun()
                        edited_sir[drug] = new_val

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
            if qc_issues:
                with st.expander(f"🔬 AST Quality Control — {len(qc_issues)} Issue(s)", expanded=True):
                    st.caption("تحقق تلقائي من منطقية نتائج المزرعة وفق EUCAST Expert Rules")
                    for issue in qc_issues:
                        icon = "❌" if issue["severity"] == "error" else "⚠️"
                        if issue["severity"] == "error":
                            st.error(f"{icon} **[{issue['id']}]** {issue['message']}  \n✏️ {issue['fix']}")
                        else:
                            st.warning(f"{icon} **[{issue['id']}]** {issue['message']}  \n✏️ {issue['fix']}")

        # ── Smart Antibiotic Ranking ──────────────────────────────────────
        if allowed:
            ranked = rank_sensitive_antibiotics(
                allowed, culture_type, organism_type, sir_map,
                phenotypes if 'phenotypes' in dir() else []
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
                for item in warned:
                    sir_tag = (f" [{sir_map[item['name']]}]"
                               if sir_map and item['name'] in sir_map else "")
                    if item.get("warning_reason") == "intermediate_culture":
                        st.warning(
                            f"**{item['name']}{sir_tag}** — Intermediate (I) on culture, "
                            "use only after clinical review."
                        )
                    elif item.get("warning_reason") == "esbl_bli_uti_only":
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

            # بناء قوائم الصورة
            reserve_names = uniq_keep_order([
                item['name'] for item in (allowed + warned)
                if item.get("aware") == "Reserve"
            ])
            # ترتيب: Access أولاً ثم Watch (بدون Reserve)
            AWARE_ORDER = {"Access": 0, "Watch": 1, "Reserve": 2, None: 3}
            preferred_sorted = sorted(
                [item for item in allowed if item.get("aware") != "Reserve"],
                key=lambda x: AWARE_ORDER.get(x.get("aware"), 3)
            )
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
            first_line_l   = org_profile.get("first_line", [])

            notes: List[str] = []
            if is_renal:
                notes.append(f"Renal impairment: CrCl {cl_cr:.1f} ml/min — dose adjustment required.")
            if is_preg:
                notes.append("Pregnancy: use with caution; consult specialist.")
            if age < 18:
                notes.append("Pediatric age: verify age-specific suitability.")
            if banned:
                notes.append(f"{len(banned)} contraindicated / ineffective antibiotics.")
            if warned:
                notes.append(f"{len(warned)} antibiotics need caution or dose adjustment.")
            notes.append("Treatment guided by severity and local resistance patterns.")
            notes.append("De-escalate based on culture & sensitivity.")

            # Ensure syndrome_info is always defined for engines
            _syndrome_info_safe = syndrome_info if 'syndrome_info' in dir() and syndrome_info else None
            syndrome_info = _syndrome_info_safe  # noqa

            # ════════════════════════════════════════════════════════════
            # CLINICAL ENGINES UI — v4.0
            # ════════════════════════════════════════════════════════════
            st.divider()

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

            # Hash all inputs that affect the report
            _patho_score = (st.session_state.get("patho_result") or {}).get("score",0)
            _rpt_input_hash = hashlib.md5(
                f"{_pt}|{age}|{sex}|{weight}|{cl_cr}|{is_renal}|{is_preg}|{is_hepatic}"
                f"|{organism_type}|{culture_type}|{colony_count}|{date_in}"
                f"|{pus_cells_text}|{rbcs_text}|{str(sorted(sir_map.items()))}"
                f"|{str(len(allowed))}|{str(len(warned))}|{str(len(banned))}"
                f"|{show_commercial}|{_lab}|{_city}|{_patho_score}".encode()
            ).hexdigest()[:16]

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
                # Hash-based cache: only regenerate when inputs actually change
                _img_input_hash = hashlib.md5(
                    f"{patient_name}|{age}|{sex}|{cl_cr}|{is_renal}|{is_preg}"
                    f"|{organism_type}|{culture_type}|{colony_count}|{date_in}"
                    f"|{pus_cells_text}|{rbcs_text}|{str(sorted(sir_map.items()))}"
                    f"|{str(len(allowed))}|{str(len(warned))}|{str(len(banned))}"
                    f"|{mdr_result.get('classification','')}|{str(len(phenotypes))}"
                    f"|{st.session_state.get('lab_name','')}|{st.session_state.get('lab_city','')}"
                    .encode()
                ).hexdigest()[:16]

                if (st.session_state.get("_img_hash") != _img_input_hash
                        or not st.session_state.get("_img_bytes")):
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
                            phenotypes=phenotypes if "phenotypes" in dir() else [],
                            referring_physician=st.session_state.get("referring_physician",""),
                            culture_condition=st.session_state.get("culture_condition","Aerobic"),
                            microbiologist=st.session_state.get("microbiologist",""),
                        )
                        st.session_state._img_bytes = _new_img
                        st.session_state._img_hash  = _img_input_hash
                    except Exception as _img_err:
                        st.error(f"خطأ في توليد الصورة: {_img_err}")

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

st.divider()
st.markdown("""
<div style="text-align:center;color:gray;font-size:0.9rem;">
  <strong>Developed by Dr / Hussein Ali | Orange Lab</strong><br>
  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | BNF 2025 | Egypt National Guidelines
</div>
""", unsafe_allow_html=True)
