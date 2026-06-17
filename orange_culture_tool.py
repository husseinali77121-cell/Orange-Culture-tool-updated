# © 2025 Dr / Hussein Ali — Orange Lab, 6 October City, Egypt
# Orange Culture Tool — All Rights Reserved
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
    SPECIMEN_ORGANISM_MAP,
    get_organisms_for_specimen,
    validate_specimen_organism_map,
)

# =========================================================
# إعداد الصفحة
# =========================================================
st.set_page_config(
    page_title="Orange Culture Tool",
    layout="wide",
    page_icon="🛡️"
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
SIR_LABELS = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
BACTERIA_TYPES = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES = list(SPECIMEN_ORDER or DEFAULT_SPECIMENS)

AWARE_COLORS = {
    "Access":  "🟢 Access",
    "Watch":   "🟡 Watch",
    "Reserve": "🔴 Reserve",
}

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
        raw = st.secrets.get("subscribers_json") or st.secrets.get("subscribers", "{}")
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
        "report_text":        "",
        # إعدادات التقرير الجديدة – نصوص بدلاً من أرقام
        "colony_count":       "≥ 10^5 CFU/mL",
        "date_in":            date.today(),
        "pus_cells_text":     "",   # نص حر مثل "4 - 6"
        "rbcs_text":          "",   # نص حر مثل "2 - 4"
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()

# ... (باقي الدوال المساعدة كما هي دون تغيير،
#      تم حذف التكرار لتوفير المساحة ولكنها موجودة في الكود الكامل)
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
    seen: set = set()
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
    seen: set = set()
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

def detect_patient_name(text: str) -> Optional[str]:
    if not text:
        return None
    patterns = [
        r"(?:Patient\s*Name|Name)\s*[:\-]\s*([A-Za-z\u0600-\u06FF\s]{3,60})",
        r"(?:اسم\s*المريض|الاسم)\s*[:\-]\s*([\u0600-\u06FFA-Za-z\s]{3,60})",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            candidate = clean_patient_name(m.group(1))
            if candidate:
                return candidate
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.search(r"[\u0600-\u06FF]", line):
            cleaned = clean_patient_name(line)
            words = cleaned.split()
            if 2 <= len(words) <= 4 and len(cleaned) <= 40:
                return cleaned
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r"[A-Za-z ]{4,40}", line):
            cleaned = clean_patient_name(line)
            words = cleaned.split()
            if 2 <= len(words) <= 4:
                return cleaned
    return None

# =========================================================
# تسجيل الدخول والاشتراك (بدون تغيير)
# =========================================================
def get_subscription_days_left(email: str) -> Optional[int]:
    email = (email or "").strip().lower()
    if email not in SUBSCRIBERS:
        return None
    expiry_str = SUBSCRIBERS[email]
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        return (expiry_date - today).days
    except Exception:
        return None

def show_login_page():
    if st.session_state.get("logout_reason"):
        st.warning(st.session_state.pop("logout_reason"))

    st.markdown("""
    <div style='text-align:center; padding: 3rem 0 1rem 0'>
        <span style='font-size:3rem'>🍊</span>
        <h2 style='margin:0.3rem 0 0.1rem 0'>Orange Culture Tool</h2>
        <p style='color:gray; margin:0'>AI-Assisted Antibiotic Decision Support — Egyptian Market</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("#### 🔐 تسجيل الدخول")
        email = st.text_input(
            "📧 البريد الإلكتروني",
            placeholder="example@hospital.com",
            label_visibility="collapsed"
        )
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
    st.session_state.email = email
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
                st.info(
                    f"✅ اشتراك **{st.session_state.email}** سارٍ — متبقي **{days}** يومًا."
                )
    with right:
        if st.button("تسجيل خروج", use_container_width=True):
            logout("تم تسجيل الخروج بنجاح.")

# =========================================================
# OCR ومعالجة الصور (بدون تغيير)
# =========================================================
def preprocess_image(file_bytes: bytes) -> Tuple[Any, Any]:
    ensure_ocr_dependencies()
    arr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
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
    patterns = [
        r"(\d+)\s*[Yy]ears?", r"Age[:\s]+(\d+)",
        r"(\d+)\s*[Yy]\b", r"العمر[:\s]+(\d+)"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = safe_int(match.group(1), -1)
            if 0 <= value <= 120:
                return value
    return None

def detect_sex(text_lower: str) -> Optional[str]:
    if any(t in text_lower for t in ["female", "sex: f", "gender: female", "أنثى", "انثى"]):
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
    ll = line.lower().strip()
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
    detected: set = set()
    for line in full_text.splitlines():
        line = line.strip()
        if not line:
            continue
        matched = match_antibiotic_from_text(line)
        if matched:
            detected.add(matched)
    return sorted(detected)

@st.cache_data(show_spinner=False)
def extract_all_data_cached(file_bytes: bytes) -> Dict[str, Any]:
    _, thresh = preprocess_image(file_bytes)
    full_text = run_ocr(thresh)
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
            "Name":     detect_patient_name(full_text),
            "Age":      detect_age(full_text),
            "Sex":      detect_sex(text_lower),
            "Specimen": detect_specimen(text_lower),
            "Organism": detect_organism(text_lower),
        },
        "drugs":    extract_detected_drugs(full_text),
        "sir_map":  sir_map,
        "raw_text": full_text,
    }

# =========================================================
# التحليل السريري (بدون تغيير)
# =========================================================
def is_intrinsically_avoided(organism_type: str, drug_name: str, drug_info: Dict[str, Any]) -> bool:
    organism_avoid = (ORGANISM_PROFILE.get(organism_type) or {}).get("avoid", [])
    d_low  = drug_name.lower()
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
    allowed: List[Dict] = []
    warned:  List[Dict] = []
    banned:  List[Dict] = []
    preg_warn_items: List[Dict] = []
    interactions_alerts: List[str] = []

    for drug in final_drugs:
        if drug not in ABX_GUIDELINES:
            continue
        info = ABX_GUIDELINES[drug]
        d_low = drug.lower()
        cls   = info.get("class", "").lower()
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

        if organism_type == "MRSA" and any(x in info.get("class","") for x in ["Penicillin","Cephalosporin"]):
            banned.append(build_banned_item(
                drug, "organism", "بيتا-لاكتام — لا يعمل على MRSA.",
                "MRSA يحمل mecA / PBP2a مما يجعل البيتا-لاكتام غير فعالة.",
            ))
            continue

        if is_preg and info.get("preg_status") == "Banned":
            preg_note = info.get("preg_note") or "ممنوع في الحمل"
            banned.append(build_banned_item(
                drug, "pregnancy",
                preg_note.splitlines()[0] if preg_note.splitlines() else "ممنوع في الحمل",
                preg_note,
            ))
            continue

        if is_preg and info.get("preg_status") == "Warn":
            preg_warn_items.append({"name": drug, **info})

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

        if is_renal and "nitrofurantoin" in d_low and cl_cr < 30:
            banned.append(build_banned_item(
                drug, "renal",
                f"ممنوع — CrCl {cl_cr:.1f} < 30 ml/min",
                f"CrCl = {cl_cr:.1f} مل/د — أقل من الحد المطلوب.",
            ))
            continue

        renal_limit = info.get("renal_limit", 0)
        if is_renal and renal_limit > 0 and cl_cr <= renal_limit:
            warned.append({"name": drug, **info, "warning_reason": "renal_adjustment"})
            continue

        if culture_result == "I":
            warned.append({"name": drug, **info, "warning_reason": "intermediate_culture"})
            continue

        allowed.append({"name": drug, **info})

    allowed = sorted(allowed, key=lambda x: x.get("priority", 999))
    warned  = sorted(warned,  key=lambda x: x.get("priority", 999))
    preg_warn_items = sorted(preg_warn_items, key=lambda x: x.get("priority", 999))
    return allowed, warned, banned, preg_warn_items, sorted(set(interactions_alerts))

# =========================================================
# صورة Clinical Decision Tree — مع التعديلات الجديدة
# =========================================================
def _get_font(size: int = 14, bold: bool = False) -> Any:
    if not PIL_AVAILABLE:
        return None
    paths = [
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{'Bold' if bold else 'Regular'}.ttf",
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{'-Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationMono-{'Bold' if bold else 'Regular'}.ttf",
    ]
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

def _draw_rbox(draw: Any, box: tuple, bg: tuple, bd: tuple,
               radius: int = 14, width: int = 3) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=bg, outline=bd, width=width)

def _draw_text_wrap(draw: Any, x: float, y: float, text: str,
                    font: Any, fill: tuple, max_w: float,
                    line_gap: int = 5) -> float:
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        try:
            tw = draw.textlength(trial, font=font)
        except Exception:
            tw = len(trial) * 8
        if tw <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    lh = (font.size if hasattr(font, "size") else 14) + line_gap
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        y += lh
    return y

def _draw_section_box(
    draw: Any,
    box: tuple,
    title: str,
    title_color: tuple,
    subtitle: str,
    items: List[str],
    item_color: tuple,
    bg: tuple,
    bd: tuple,
    font_title: Any,
    font_sub: Any,
    font_item: Any,
) -> None:
    x1, y1, x2, y2 = box
    _draw_rbox(draw, box, bg, bd, radius=16, width=3)

    draw.text((x1 + 14, y1 + 12), title, fill=title_color, font=font_title)
    cy = y1 + 12 + (font_title.size if hasattr(font_title, "size") else 16) + 6

    if subtitle:
        draw.text((x1 + 14, cy), subtitle, fill=(110, 115, 125), font=font_sub)
        cy += (font_sub.size if hasattr(font_sub, "size") else 13) + 4

    draw.line([(x1 + 10, cy), (x2 - 10, cy)], fill=bd, width=1)
    cy += 8

    item_h = (font_item.size if hasattr(font_item, "size") else 13) + 7
    for item in items:
        if cy + item_h > y2 - 8:
            draw.text((x1 + 14, cy), "...", fill=(150, 150, 150), font=font_item)
            break
        cy = _draw_text_wrap(
            draw, x1 + 14, cy, f"• {item}",
            font_item, item_color, x2 - x1 - 26, line_gap=5
        )


def generate_decision_tree_image(
    patient_name: str,
    age: int,
    sex: str,
    weight: float,
    cl_cr: float,
    is_renal: bool,
    is_preg: bool,
    organism: str,
    specimen: str,
    first_line: List[str],
    avoid: List[str],
    preferred: List[str],
    use_caution: List[str],
    contraindicated: List[str],
    reserve: List[str],
    notes: List[str],
    colony_count: str = "",
    date_in: str = "",
    pus_cells: str = "",   # أصبح نصًا
    rbcs: str = "",        # أصبح نصًا
) -> bytes:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow غير متاح — أضف Pillow لـ requirements.txt")

    W, H   = 1264, 843
    PAD    = 16
    GAP    = 10
    BG     = (248, 250, 252)
    WHITE  = (255, 255, 255)
    DARK   = (28,  32,  40)
    GRAY   = (95, 100, 112)

    NAVY       = (4,   26,  63)
    PURPLE_BD  = (120, 75, 178);  PURPLE_BG  = (247, 243, 254)
    GREEN_BD   = (45, 138,  68);  GREEN_BG   = (236, 252, 240);  GREEN_TXT  = (20,  95,  40)
    AMBER_BD   = (195,140,  30);  AMBER_BG   = (255, 250, 228);  AMBER_TXT  = (120,  80,   0)
    RED_BD     = (183, 52,  52);  RED_BG     = (255, 237, 234);  RED_TXT    = (148,  30,  30)
    BLUE_BD    = (35,  90, 172);  BLUE_BG    = (234, 244, 255);  BLUE_TXT   = (15,   55, 145)
    ALERT_BD   = (205,115,  50);  ALERT_BG   = (255, 248, 232);  ALERT_TXT  = (130,  60,   5)
    SPEC_BD    = (35,  90, 172);  SPEC_BG    = (234, 244, 255)
    INF_BD     = (30, 130,  65);  INF_BG     = (234, 252, 238)
    FL_BD      = (190,138,  28);  FL_BG      = (255, 250, 225)
    FOOT_BD    = (185,192,200);   FOOT_BG    = (247, 249, 251)

    F_HEADER  = _get_font(20, True)
    F_TITLE   = _get_font(15, True)
    F_SUBTITL = _get_font(12, True)
    F_TEXT    = _get_font(12)
    F_SMALL   = _get_font(10)
    F_ORG     = _get_font(26, True)
    F_SUMNUM  = _get_font(20, True)

    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # HEADER
    _draw_rbox(draw, (PAD, 6, W - PAD, 62), NAVY, NAVY, radius=12, width=1)
    htxt = "🔬  ORANGE LAB – CLINICAL DECISION TREE"
    try:
        hw = draw.textlength(htxt, font=F_HEADER)
    except Exception:
        hw = len(htxt) * 11
    draw.text(((W - hw) // 2, 16), htxt, fill=WHITE, font=F_HEADER)

    # CENTER CULTURE BOX
    CB_X1, CB_X2 = 368, 870
    CB_Y1, CB_Y2 = 72, 192
    _draw_rbox(draw, (CB_X1, CB_Y1, CB_X2, CB_Y2), WHITE, NAVY, radius=14, width=2)
    ctype_txt = "URINE CULTURE RESULT" if "urine" in specimen.lower() else f"{specimen.upper()} CULTURE RESULT"
    try:
        ctw = draw.textlength(ctype_txt, font=F_SUBTITL)
    except Exception:
        ctw = len(ctype_txt) * 8
    draw.text(((CB_X1 + CB_X2 - ctw) // 2, CB_Y1 + 14), ctype_txt, fill=DARK, font=F_SUBTITL)

    try:
        ow = draw.textlength(organism, font=F_ORG)
    except Exception:
        ow = len(organism) * 15
    draw.text(((CB_X1 + CB_X2 - ow) // 2, CB_Y1 + 42), organism, fill=NAVY, font=F_ORG)

    if colony_count:
        cc_text = f"Colony Count: {colony_count}"
        try:
            cclw = draw.textlength(cc_text, font=F_TEXT)
        except Exception:
            cclw = len(cc_text) * 7
        y_cc = CB_Y1 + 42 + (F_ORG.size if hasattr(F_ORG, "size") else 30) + 8
        draw.text(((CB_X1 + CB_X2 - cclw) // 2, y_cc), cc_text, fill=DARK, font=F_TEXT)

    # PATIENT DETAILS
    PB = (PAD, 72, 358, 192)
    _draw_rbox(draw, PB, PURPLE_BG, PURPLE_BD, radius=14, width=3)
    draw.text((PAD + 14, 84), "PATIENT DETAILS", fill=PURPLE_BD, font=F_TITLE)
    p_lines = []
    if patient_name:
        p_lines.append(f"Name: {patient_name}")
    p_lines += [
        f"{'Male' if sex == 'Male' else 'Female'}, {age} years",
        f"Weight: {weight} kg",
        f"Renal: {'IMPAIRED' if is_renal else 'Normal'}",
    ]
    if is_renal:
        p_lines.append(f"CrCl: {cl_cr:.1f} ml/min ({get_renal_severity(cl_cr)})")
    if sex == "Female":
        p_lines.append(f"Pregnancy: {'Yes' if is_preg else 'No'}")
    if age < 18:
        p_lines.append("Verify age-specific antibiotic suitability.")
    py = 106
    for ln in p_lines[:7]:
        draw.text((PAD + 14, py), f"• {ln}", fill=DARK, font=F_TEXT)
        py += F_TEXT.size + 5 if hasattr(F_TEXT, "size") else 17

    # ALERT BOX
    AB = (885, 72, W - PAD, 192)
    _draw_rbox(draw, AB, ALERT_BG, ALERT_BD, radius=14, width=3)
    draw.text((AB[0] + 14, 84), "⚠  IMPORTANT ALERT", fill=ALERT_TXT, font=F_TITLE)
    alerts: List[str] = []
    org_l = organism.lower()
    if "klebsiella" in org_l:
        alerts += ["Consider ESBL screening", "Natural resistance to some beta-lactams"]
    elif "e. coli" in org_l or "coli" in org_l:
        alerts += ["Most common UTI pathogen", "Verify with culture sensitivity"]
    if is_renal:
        alerts.append(f"Renal adjustment needed (CrCl {cl_cr:.0f} ml/min)")
    if is_preg:
        alerts.append("Pregnancy: verify fetal safety")
    if age < 18:
        alerts.append("Pediatric: check age-specific suitability")
    if not alerts:
        alerts = ["Verify sensitivity results.", "Consult local resistance patterns."]
    ay = 106
    for al in alerts[:5]:
        ay = _draw_text_wrap(draw, AB[0] + 14, ay, f"• {al}", F_TEXT, DARK, AB[2] - AB[0] - 28, line_gap=4)
        ay += 2

    # ROW 2: 3 boxes (Specimen + Date, Microscopic, First-line)
    R2_Y1, R2_Y2 = 205, 300
    r2w = (W - 2 * PAD - 2 * GAP) // 3

    spec_items = [specimen]
    if date_in:
        spec_items.append(f"Date In: {date_in}")

    # Microscopic examination – نصوص حرة
    micro_items = []
    if pus_cells:
        micro_items.append(f"Pus cells: {pus_cells}/HPF")
    else:
        micro_items.append("Pus cells: —/HPF")
    if rbcs:
        micro_items.append(f"RBC cells: {rbcs}/HPF")
    else:
        micro_items.append("RBC cells: —/HPF")

    fl_items = first_line[:4] or ["—"]

    r2_data = [
        ("SPECIMEN",          spec_items, SPEC_BD, SPEC_BG, "🧪"),
        ("MICROSCOPIC EXAM",  micro_items, INF_BD,  INF_BG,  "🔬"),
        ("FIRST-LINE OPTIONS", fl_items,   FL_BD,   FL_BG,   "📋"),
    ]

    for i, (title, items, bd, bg, icon) in enumerate(r2_data):
        bx1 = PAD + i * (r2w + GAP)
        bx2 = bx1 + r2w
        _draw_rbox(draw, (bx1, R2_Y1, bx2, R2_Y2), bg, bd, radius=12, width=2)
        draw.text((bx1 + 12, R2_Y1 + 9), f"{icon} {title}", fill=bd, font=F_SUBTITL)
        iy = R2_Y1 + 32
        for it in items[:4]:
            iy = _draw_text_wrap(draw, bx1 + 14, iy, f"• {it}", F_SMALL, DARK, bx2 - bx1 - 24, line_gap=4)

    # FOUR MAIN COLUMNS
    COL_Y1 = 312
    COL_Y2 = H - 115
    cw     = (W - 2 * PAD - 3 * GAP) // 4

    columns = [
        ("✅ PREFERRED (SAFE)",    "Preferred oral options",   preferred,       GREEN_BD,  GREEN_BG,  GREEN_TXT),
        ("⚠️  USE WITH CAUTION",  "Use with caution",          use_caution,     AMBER_BD,  AMBER_BG,  AMBER_TXT),
        ("🚫 AVOID / CONTRAINDICT.", "Due to other factors",   contraindicated,  RED_BD,   RED_BG,    RED_TXT),
        ("🛡️  RESERVE (SEVERE)",  "ESBL / Severe cases only", reserve,          BLUE_BD,  BLUE_BG,   BLUE_TXT),
    ]

    for i, (title, subtitle, items, bd, bg, tc) in enumerate(columns):
        bx1 = PAD + i * (cw + GAP)
        bx2 = bx1 + cw
        _draw_section_box(
            draw, (bx1, COL_Y1, bx2, COL_Y2),
            title, tc, subtitle, items or ["—"], DARK,
            bg, bd, F_TITLE, F_SMALL, F_TEXT,
        )

    # FOOTER
    FY1 = H - 107
    FY2 = H - 8
    fw  = (W - 2 * PAD - 2 * GAP) // 3

    fx1 = PAD;         fx2 = fx1 + fw
    _draw_rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1 + 12, FY1 + 10), "WHO AWaRe CLASSIFICATION", fill=DARK, font=F_SUBTITL)
    wy = FY1 + 32
    for label, color in [("ACCESS", GREEN_TXT), ("WATCH", AMBER_TXT), ("RESERVE", RED_TXT)]:
        draw.text((fx1 + 12, wy), label, fill=color, font=F_TEXT)
        try:
            lw = draw.textlength(label, font=F_TEXT) + 16
        except Exception:
            lw = 70
        draw.rounded_rectangle(
            (fx1 + 12 - 4, wy - 2, fx1 + 12 + lw, wy + (F_TEXT.size if hasattr(F_TEXT, "size") else 12) + 2),
            radius=5, outline=color, width=1
        )
        wy += (F_TEXT.size if hasattr(F_TEXT, "size") else 12) + 6
    draw.text((fx1 + 12, FY2 - 16), "First/second | Caution | Last resort", fill=GRAY, font=F_SMALL)

    fx1 = PAD + fw + GAP;  fx2 = fx1 + fw
    _draw_rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1 + 12, FY1 + 10), "📊  SUMMARY", fill=DARK, font=F_SUBTITL)
    sum_items = [
        (f"~{len(preferred)}",       "Recommended", GREEN_TXT),
        (f"~{len(use_caution)}",     "Caution",     AMBER_TXT),
        (f"~{len(contraindicated)}", "Avoided",     RED_TXT),
        (f"~{len(reserve)}",         "Reserve",     BLUE_TXT),
    ]
    sw = (fx2 - fx1 - 20) // 4
    for j, (num, lbl, clr) in enumerate(sum_items):
        sx = fx1 + 14 + j * sw
        draw.text((sx, FY1 + 32), num, fill=clr, font=F_SUMNUM)
        draw.text((sx, FY1 + 62), lbl, fill=GRAY, font=F_SMALL)

    fx1 = PAD + 2 * (fw + GAP);  fx2 = W - PAD
    _draw_rbox(draw, (fx1, FY1, fx2, FY2), FOOT_BG, FOOT_BD, radius=12, width=2)
    draw.text((fx1 + 12, FY1 + 10), "📋  NOTES", fill=DARK, font=F_SUBTITL)
    ny = FY1 + 32
    for note in (notes or [])[:4]:
        ny = _draw_text_wrap(draw, fx1 + 12, ny, f"• {note}", F_SMALL, DARK, fx2 - fx1 - 22, line_gap=4)

    draw.text(
        (PAD, H - 6),
        "Developed by Dr / Hussein Ali | Orange Lab  |  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | Egypt National Guidelines",
        fill=GRAY, font=F_SMALL
    )

    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()

# =========================================================
# التقرير النصي (بدون تغيير عن السابق)
# =========================================================
def generate_report(
    patient_name: str,
    age: int,
    sex: str,
    weight: float,
    cl_cr: float,
    is_renal: bool,
    is_preg: bool,
    is_hepatic: bool,
    allowed: List[Dict],
    warned: List[Dict],
    banned: List[Dict],
    preg_warn_items: List[Dict],
    organism: str,
    specimen: str,
    interactions: List[str],
    sir_map: Dict[str, str],
) -> str:
    now  = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep  = "=" * 60
    sep2 = "-" * 60
    lines: List[str] = []

    lines += [sep, "ORANGE LAB — CLINICAL DECISION REPORT", sep,
              f"Date     : {now}"]
    if patient_name:
        lines.append(f"Patient  : {patient_name}")
    lines.append(sep)

    lines += ["\nPATIENT DETAILS", sep2]
    lines.append("Note     : راجع اسم المريض — قد يحتاج تصحيحًا يدويًا إذا جاء من OCR.")
    lines += [
        f"Age      : {age} years",
        f"Gender   : {sex}",
        f"Weight   : {weight} kg",
        f"Renal    : {'IMPAIRED' if is_renal else 'Normal'}",
    ]
    if is_renal:
        lines.append(f"CrCl     : {cl_cr:.1f} ml/min ({get_renal_severity(cl_cr)})")
    lines.append(f"Hepatic  : {'IMPAIRED' if is_hepatic else 'Normal'}")
    if sex == "Female":
        lines.append(f"Pregnant : {'Yes' if is_preg else 'No'}")

    lines += ["\nCULTURE", sep2,
              f"Specimen : {specimen}",
              f"Organism : {organism}"]

    if organism in ORGANISM_PROFILE:
        op = ORGANISM_PROFILE[organism]
        if op.get("note"):
            lines.append(f"Note       : {op['note']}")
        spec_ctx = (op.get("specimen_context") or {}).get(specimen, "")
        if spec_ctx:
            lines.append(f"Context    : {spec_ctx}")
        if op.get("first_line"):
            lines.append(f"First-line : {', '.join(op['first_line'])}")
        if op.get("avoid"):
            lines.append(f"Avoid      : {', '.join(op['avoid'])}")

    if sir_map:
        lines += ["\nSENSITIVITY RESULTS", sep2]
        for drug, result in sorted(sir_map.items()):
            label = {"S": "Sensitive", "R": "Resistant", "I": "Intermediate"}.get(result, result)
            lines.append(f"{drug:<40} {label}")

    if interactions:
        lines += ["\nINTERACTIONS / WARNINGS", sep2]
        for item in sorted(set(interactions)):
            lines.append(f"- {item}")

    lines += ["\nRECOMMENDED ANTIBIOTICS", sep]
    if allowed:
        for item in allowed:
            sir_tag  = f" [Culture: {sir_map[item['name']]}]" if sir_map and item['name'] in sir_map else ""
            preg_tag = " [Pregnancy: caution]" if (is_preg and item.get("preg_status") == "Warn") else ""
            lines += [f"\n{item['name']}{sir_tag}{preg_tag}", sep2,
                      f"WHO AWaRe : {item.get('aware','-')}",
                      f"Class     : {item.get('class','-')}",
                      f"Route     : {'Oral/PO-friendly' if item.get('high_po') else 'IV/IM only'}"]
            spec_note = (item.get("specimen_notes") or {}).get(specimen, "")
            if spec_note:
                lines += [f"Note      : {item.get('note','')}", f"{specimen}   : {spec_note}"]
            else:
                lines.append(f"Note      : {item.get('note','')}")
            if is_renal:
                lines.append(f"Renal     : {item.get('renal_note','-')}")
            if is_preg and item.get("preg_status") == "Warn":
                pn = (item.get("preg_note") or "").splitlines()
                if pn:
                    lines.append(f"Pregnancy : {pn[0]}")
    else:
        lines.append("No recommended options after applying all restrictions.")

    if warned:
        lines += ["\nDOSE ADJUSTMENT / USE WITH CAUTION", sep]
        if is_renal:
            lines.append(f"Patient CrCl = {cl_cr:.1f} ml/min\n")
        for item in warned:
            sir_tag = f" [Culture: {sir_map[item['name']]}]" if sir_map and item['name'] in sir_map else ""
            lines += [f"{item['name']}{sir_tag}", sep2,
                      f"WHO AWaRe : {item.get('aware','-')}"]
            if item.get("warning_reason") == "intermediate_culture":
                lines.append("Reason    : Intermediate (I) on culture result")
            else:
                lines += [f"Renal note: {item.get('renal_note','-')}",
                          f"Limit CrCl: <= {item.get('renal_limit','-')} ml/min"]
            lines.append("")

    if is_preg and preg_warn_items:
        lines += ["\nPREGNANCY — USE WITH CAUTION", sep]
        for item in preg_warn_items:
            lines += [item['name'], sep2]
            lines.extend((item.get("preg_note") or "").splitlines())
            lines.append("")

    if banned:
        lines += ["\nCONTRAINDICATED / INEFFECTIVE", sep]
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
                lines += [f"\n{heading}", sep2]
                for b in grouped[cat]:
                    lines.append(f"- {b['name']} — {b['reason_short']}")
                    if cat == "renal":
                        dk = b["name"].lower().replace(" ", "")
                        rendered = False
                        for k, v in RENAL_BAN_REASONS.items():
                            if k in dk:
                                lines.extend([f"  {ln}" for ln in v.splitlines()])
                                rendered = True
                                break
                        if not rendered:
                            lines.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                    else:
                        lines.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                    lines.append("")

    lines += [
        "\nDISCLAIMER", sep,
        "هذا التقرير أداة مساعدة للقرار الطبي وليس بديلاً عن التقييم السريري.",
        "القرار النهائي للوصف العلاجي يعود للطبيب المعالج.",
        sep,
        "Guidelines: EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | Egypt National",
        "Route info: BNF 2025 | FDA Labels | WHO AWaRe 2025",
        "WHO AWaRe : Access | Watch | Reserve",
        sep,
        "Developed by Dr / Hussein Ali | Orange Lab",
        sep,
    ]
    return "\n".join(lines)

# =========================================================
# واجهة التطبيق الرئيسية (مع حقول النص الجديدة)
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

st.title("🛡️ Orange Culture Tool")
st.caption("AI-Assisted Antibiotic Decision Support — Egyptian Market Edition")

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
                st.session_state.report_text        = ""
                st.session_state.patient_name_ocr   = payload["patient"].get("Name") or ""
                st.session_state.patient_name_final = payload["patient"].get("Name") or ""
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

        ocr_name = (st.session_state.get("patient_name_ocr") or "").strip()
        if ocr_name:
            st.info(f"📖 الاسم من OCR: **{ocr_name}**")
        else:
            st.caption("لم يُتعرف على اسم المريض تلقائياً — أدخله يدوياً.")

        nc1, nc2 = st.columns([5, 1])
        with nc1:
            patient_name = st.text_input(
                "👤 Patient Name (اسم المريض)",
                value=st.session_state.get("patient_name_final", ""),
                placeholder="أدخل أو صحّح اسم المريض",
                help="يظهر في التقرير وصورة الملخص. صحّح إذا كان OCR أخطأ.",
                key=f"pname_{file_hash[:8]}"
            )
        with nc2:
            st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
            if st.button("↺ OCR", use_container_width=True, key=f"ocr_name_{file_hash[:8]}"):
                st.session_state.patient_name_final = ocr_name
                st.rerun()
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

        # --- Colony count, Date In, Microscopic exam (نصوص حرة) ---
        st.divider()
        st.subheader("🔬 Culture & Microscopic Details")

        colony_count = st.text_input(
            "Colony Count (CFU/mL)",
            value=st.session_state.colony_count,
            placeholder="≥ 10^5 CFU/mL",
            help="أدخل تعداد المستعمرات",
            key="colony_count_input"
        )
        st.session_state.colony_count = colony_count

        date_in = st.date_input(
            "Date In (تاريخ استلام العينة)",
            value=st.session_state.date_in,
            key="date_in_input"
        )
        st.session_state.date_in = date_in

        col_pus, col_rbc = st.columns(2)
        with col_pus:
            pus_cells_text = st.text_input(
                "Pus Cells (/HPF)",
                value=st.session_state.pus_cells_text,
                placeholder="مثال: 4 - 6",
                key="pus_cells_text"
            )
            st.session_state.pus_cells_text = pus_cells_text
        with col_rbc:
            rbcs_text = st.text_input(
                "RBC Cells (/HPF)",
                value=st.session_state.rbcs_text,
                placeholder="مثال: 2 - 4",
                key="rbcs_text"
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

        age = st.number_input(
            "Age (years)", min_value=0, max_value=120,
            value=safe_int(patient.get("Age"), 25)
        )
        default_sex = patient.get("Sex") if patient.get("Sex") in ["Female","Male"] else "Male"
        sex = st.selectbox("Gender", ["Female","Male"],
                           index=0 if default_sex == "Female" else 1)
        weight = st.number_input("Weight (kg)", min_value=5, max_value=300, value=70)

        st.divider()

        is_renal = st.checkbox("🚩 Renal Impairment")
        cl_cr    = 100.0
        if is_renal:
            s_cr = st.number_input(
                "Serum Creatinine (mg/dL)",
                min_value=0.1, max_value=20.0, value=1.0, step=0.1
            )
            cl_cr    = calc_creatinine_clearance(age, weight, s_cr, sex)
            severity = get_renal_severity(cl_cr)
            st.metric(
                "CrCl (Cockcroft-Gault)", f"{cl_cr:.1f} ml/min",
                delta=severity,
                delta_color="normal" if cl_cr >= 60 else ("off" if cl_cr >= 30 else "inverse")
            )

        is_hepatic = st.checkbox("🚩 Hepatic Impairment")

        is_preg = False
        if sex == "Female" and 12 <= age <= 55:
            is_preg = st.checkbox("🤰 Patient is Pregnant")

        current_meds = st.multiselect("💊 Current Medications", COMMON_MEDS)

    # ─── العمود الأيمن ────────────────────────────────────────────────────────
    with col2:
        st.subheader("💊 Antibiotic Analysis")

        ocr_sir_map = payload["sir_map"]
        if ocr_sir_map:
            st.markdown("**📊 نتائج المزرعة — S / I / R** *(عدّل أي قيمة خطأ)*")
            st.caption("تعديلاتك تُطبَّق مباشرة على التحليل والتقرير والصورة")

            sir_options  = ["S", "I", "R"]
            edited_sir: Dict[str, str] = {}
            drug_list    = sorted(ocr_sir_map.keys())
            for i in range(0, len(drug_list), 3):
                row_drugs = drug_list[i: i + 3]
                row_cols  = st.columns(3)
                for col, drug in zip(row_cols, row_drugs):
                    cur = st.session_state.sir_map_edited.get(drug, ocr_sir_map[drug])
                    if cur not in sir_options:
                        cur = "S"
                    new_val = col.selectbox(
                        drug, options=sir_options,
                        index=sir_options.index(cur),
                        key=f"sir_{drug}_{file_hash[:8]}"
                    )
                    edited_sir[drug] = new_val
            st.session_state.sir_map_edited = edited_sir

        sir_map = dict(st.session_state.sir_map_edited)

        final_drugs = st.multiselect(
            "✅ Confirm / Edit Antibiotics",
            options=sorted(ABX_GUIDELINES.keys()),
            default=[d for d in drugs_from_ocr if d in ABX_GUIDELINES]
        )

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
                    else:
                        st.warning(
                            f"**{item['name']}{sir_tag}** — {item.get('renal_note','')}"
                        )

        if allowed:
            st.success(f"🟢 {len(allowed)} Recommended Option(s)")
            for item in allowed:
                sir_badge = (f" [{sir_map[item['name']]}]"
                             if sir_map and item['name'] in sir_map else "")
                preg_flag = " 🤰" if (is_preg and item.get("preg_status") == "Warn") else ""
                aware_val = item.get("aware", "Unknown")
                color_val = AWARE_COLORS.get(aware_val, aware_val)
                with st.expander(
                    f"{item['name']}{sir_badge}{preg_flag} — {color_val}",
                    expanded=False
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

            reserve_names = uniq_keep_order([
                item['name'] for item in (allowed + warned)
                if item.get("aware") == "Reserve"
            ])
            preferred_names = [
                item['name'] for item in allowed
                if item.get("aware") != "Reserve"
            ]
            warned_names = [
                item['name'] for item in warned
                if item['name'] not in reserve_names
            ]
            preg_caution_names = [item['name'] for item in preg_warn_items]
            use_caution_names = uniq_keep_order(warned_names + preg_caution_names)

            banned_names = uniq_keep_order([item['name'] for item in banned])

            org_profile   = ORGANISM_PROFILE.get(organism_type, {})
            first_line_l  = org_profile.get("first_line", [])
            avoid_l       = org_profile.get("avoid", [])

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

            # ── تقرير نصي غير قابل للتعديل ──────────────────────────────────
            st.markdown("### 📋 التقرير السريري")
            st.caption("النص النهائي — حمل الملف للتعديل الخارجي")

            auto_report = generate_report(
                patient_name=st.session_state.patient_name_final or "غير محدد",
                age=age, sex=sex, weight=weight,
                cl_cr=cl_cr, is_renal=is_renal,
                is_preg=is_preg, is_hepatic=is_hepatic,
                allowed=allowed, warned=warned, banned=banned,
                preg_warn_items=preg_warn_items,
                organism=organism_type, specimen=culture_type,
                interactions=interactions_alerts, sir_map=sir_map,
            )
            st.text_area(
                "نص التقرير (للقراءة فقط)",
                value=auto_report,
                height=400,
                disabled=True,
                label_visibility="collapsed"
            )
            st.download_button(
                "📥 تنزيل التقرير (TXT)",
                data=auto_report,
                file_name=f"Orange_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

            # ── صورة الملخص ──────────────────────────────────────────────────
            st.divider()
            st.markdown("### 🖼️ صورة ملخص الحالة")
            st.caption("جاهزة للطباعة وتسليمها للطبيب — بتصميم Orange Lab")

            if PIL_AVAILABLE:
                with st.spinner("🎨 جاري رسم الصورة..."):
                    try:
                        img_bytes = generate_decision_tree_image(
                            patient_name=st.session_state.patient_name_final or "غير محدد",
                            age=age, sex=sex, weight=weight,
                            cl_cr=cl_cr, is_renal=is_renal, is_preg=is_preg,
                            organism=organism_type, specimen=culture_type,
                            first_line=first_line_l,
                            avoid=avoid_l,
                            preferred=preferred_names,
                            use_caution=use_caution_names,
                            contraindicated=banned_names,
                            reserve=reserve_names,
                            notes=notes,
                            colony_count=st.session_state.colony_count,
                            date_in=str(st.session_state.date_in),
                            pus_cells=st.session_state.pus_cells_text,   # نص
                            rbcs=st.session_state.rbcs_text,             # نص
                        )
                        img_ok = True
                    except Exception as e:
                        st.error(f"فشل توليد الصورة: {e}")
                        img_ok  = False
                        img_bytes = None

                if img_ok and img_bytes:
                    st.image(
                        img_bytes,
                        caption="Orange Lab — Clinical Decision Tree",
                        use_container_width=True
                    )
                    st.download_button(
                        "📥 تنزيل الصورة الملخصة (PNG)",
                        data=img_bytes,
                        file_name=f"Orange_Summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png",
                        mime="image/png",
                        use_container_width=True,
                    )
            else:
                st.warning("⚠️ أضف `Pillow` لـ requirements.txt لتفعيل صورة الملخص.")

st.divider()
st.markdown("""
<div style="text-align:center;color:gray;font-size:0.9rem;">
  <strong>Developed by Dr / Hussein Ali | Orange Lab</strong><br>
  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | BNF 2025 | Egypt National Guidelines
</div>
""", unsafe_allow_html=True)
