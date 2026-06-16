# © 2025 Dr / Hussein Ali — Orange Lab, 6 October City, Egypt
# Orange Culture Tool — All Rights Reserved
# Unauthorized copying or distribution is prohibited.

import json
import re
import time
import hashlib
from datetime import datetime
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
# صفحة التطبيق
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
    .muted-text {
        color: #9aa0a6;
        font-size: 0.92rem;
    }
    .orange-badge {
        display:inline-block;
        background:#ff8c00;
        color:white;
        padding:0.25rem 0.7rem;
        border-radius:999px;
        font-size:0.8rem;
        font-weight:600;
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# الثوابت العامة
# =========================================================
SESSION_TIMEOUT = 30 * 60
SIR_LABELS = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}
BACTERIA_TYPES = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES = list(SPECIMEN_ORDER or DEFAULT_SPECIMENS)

AWARE_COLORS = {
    "Access": "🟢 Access",
    "Watch": "🟡 Watch",
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
    "cephalosporins": ["cephalosporin"],
    "tetracyclines": ["tetracycline"],
    "aminoglycosides": ["aminoglycoside"],
    "carbapenems": ["carbapenem"],
    "beta-lactams (alone)": ["penicillin", "cephalosporin", "carbapenem"],
    "beta-lactams": ["penicillin", "cephalosporin", "carbapenem"],
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
# جلسة التطبيق
# =========================================================
def init_session_state() -> None:
    defaults = {
        "authenticated": False,
        "email": "",
        "days_left": None,
        "last_activity": None,
        "logout_reason": "",
        "ocr_data": None,
        "last_file_hash": "",
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
    issues.extend(validate_abx_guidelines(known_organisms=list(ORGANISM_PROFILE.keys()), known_specimens=SPECIMEN_TYPES))
    issues.extend(validate_organism_profile(known_antibiotics=list(ABX_GUIDELINES.keys())))
    issues.extend(validate_specimen_organism_map(known_organisms=list(ORGANISM_PROFILE.keys())))

    deduped: List[str] = []
    seen = set()
    for issue in issues:
        if issue not in seen:
            deduped.append(issue)
            seen.add(issue)
    return deduped

def normalize_ocr_text(text: str) -> str:
    cleaned = text or ""
    replacements = {
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
        "|": " ",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def best_default_index(options: List[str], preferred: Optional[str]) -> int:
    if preferred and preferred in options:
        return options.index(preferred)
    return 0

# =========================================================
# صفحة تسجيل الدخول
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
            "📞 01016872801\n\n"
            "✉️ Hussein.ali77121@gmail.com\n\n"
            "---\n"
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
# OCR ومعالجة الصور
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
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    kernel = np.ones((1, 1), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
    return img, thresh

def run_ocr(thresh: Any) -> str:
    ensure_ocr_dependencies()
    configs = ["--psm 6", "--psm 11", "--psm 4"]
    outputs = []
    for cfg in configs:
        try:
            txt = pytesseract.image_to_string(thresh, config=cfg)
            txt = normalize_ocr_text(txt)
            if txt:
                outputs.append(txt)
        except Exception:
            continue
    if not outputs:
        raise RuntimeError("OCR failed: no text extracted")

    return max(outputs, key=lambda x: len(re.sub(r"\s+", "", x)))

def detect_age(text: str) -> Optional[int]:
    patterns = [r"(\d+)\s*[Yy]ears?", r"Age[:\s]+(\d+)", r"(\d+)\s*[Yy]\b"]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            value = safe_int(match.group(1), -1)
            if 0 <= value <= 120:
                return value
    return None

def detect_sex(text_lower: str) -> Optional[str]:
    if any(token in text_lower for token in ["female", "sex: f", "gender: female"]):
        return "Female"
    if any(token in text_lower for token in ["male", "sex: m", "gender: male"]):
        return "Male"
    return None

def detect_specimen(text_lower: str) -> Optional[str]:
    specimen_hits = []
    for specimen in SPECIMEN_TYPES:
        if specimen.lower() in text_lower:
            specimen_hits.append(specimen)
    return specimen_hits[0] if specimen_hits else None

def detect_organism(text_lower: str) -> Optional[str]:
    organism_counts: Dict[str, int] = {}
    for organism in BACTERIA_TYPES:
        count = text_lower.count(organism.lower())
        if count > 0:
            organism_counts[organism] = count
    if organism_counts:
        return max(organism_counts, key=organism_counts.get)
    return None

def classify_sir_from_line(line: str) -> Optional[str]:
    ll = line.lower().strip()
    tail_match = re.search(r"\b([sir])\b\s*$", ll)
    if tail_match:
        return tail_match.group(1).upper()
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
    detected = set()
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
            "Age": detect_age(full_text),
            "Sex": detect_sex(text_lower),
            "Specimen": detect_specimen(text_lower),
            "Organism": detect_organism(text_lower),
        },
        "drugs": extract_detected_drugs(full_text),
        "sir_map": sir_map,
        "raw_text": full_text,
    }

# =========================================================
# التحليل السريري
# =========================================================
def is_intrinsically_avoided(organism_type: str, drug_name: str, drug_info: Dict[str, Any]) -> bool:
    organism_avoid = (ORGANISM_PROFILE.get(organism_type) or {}).get("avoid", [])
    d_low = drug_name.lower()
    d_class = drug_info.get("class", "").lower()

    for avoid_item in organism_avoid:
        av_low = avoid_item.lower().strip()

        if av_low in d_low or d_low in av_low:
            return True

        mapped_classes = ORGANISM_AVOID_CLASS_MAP.get(av_low)
        if mapped_classes and any(cls in d_class for cls in mapped_classes):
            return True

    return False

def build_banned_item(name: str, category: str, reason_short: str, reason_detail: str) -> Dict[str, str]:
    return {
        "name": name,
        "category": category,
        "reason_short": reason_short,
        "reason_detail": reason_detail,
    }

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
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
    allowed: List[Dict[str, Any]] = []
    warned: List[Dict[str, Any]] = []
    banned: List[Dict[str, Any]] = []
    preg_warn_items: List[Dict[str, Any]] = []
    interactions_alerts: List[str] = []

    for drug in final_drugs:
        if drug not in ABX_GUIDELINES:
            continue

        info = ABX_GUIDELINES[drug]
        d_low = drug.lower()
        cls = info.get("class", "").lower()
        culture_result = sir_map.get(drug)

        if culture_result == "R":
            banned.append(build_banned_item(
                drug,
                "resistant",
                "مقاوم (R) في نتيجة المزرعة.",
                f"المزرعة أثبتت أن {drug} لا يثبط نمو الجرثومة. MIC أعلى من الحد العلاجي المتوقع → خطر فشل علاجي مرتفع.",
            ))
            continue

        for med in current_meds:
            if med in info.get("interacts_with", []):
                interactions_alerts.append(f"⚡ تعارض: {drug} مع {med}")

        if is_hepatic and info.get("hepatic_caution"):
            interactions_alerts.append(f"🏥 تحذير كبدي: {drug} — يحتاج متابعة أو تعديل حسب الحالة.")

        if is_intrinsically_avoided(organism_type, drug, info):
            banned.append(build_banned_item(
                drug,
                "organism",
                f"غير فعال لـ {organism_type} طبيعياً.",
                f"{drug} لديه مقاومة طبيعية أو عدم فعالية متوقعة ضد {organism_type}. استخدامه قد يؤدي إلى فشل علاجي.",
            ))
            continue

                        if organism_type == "MRSA" and any(x in info.get("class", "") for x in ["Penicillin", "Cephalosporin", "Carbapenem"]):
            banned.append(build_banned_item(
                drug,
                "organism",
                "بيتا-لاكتام — لا يعمل على MRSA.",
                "MRSA يحمل آلية مقاومة mecA / PBP2a، لذلك البيتا-لاكتام—including carbapenems—غير فعالة سريرياً في هذا السياق.",
            ))
            continue

        if is_preg and info.get("preg_status") == "Banned":
            preg_note = info.get("preg_note") or "ممنوع في الحمل"
            banned.append(build_banned_item(
                drug,
                "pregnancy",
                preg_note.splitlines()[0] if preg_note.splitlines() else "ممنوع في الحمل",
                preg_note,
            ))
            continue

        if is_preg and info.get("preg_status") == "Warn":
            preg_warn_items.append({"name": drug, **info})

        if age < 18 and not info.get("child_safe", True):
            if "fluoroquinolone" in cls:
                banned.append(build_banned_item(drug, "child", "غير مناسب < 18 سنة.", CHILD_BAN_REASONS["fluoroquinolone"]))
                continue
            if "tetracycline" in cls and age < 8:
                banned.append(build_banned_item(drug, "child", "غير مناسب < 8 سنوات.", CHILD_BAN_REASONS["tetracycline"]))
                continue
            banned.append(build_banned_item(
                drug,
                "child",
                "غير مفضل للأطفال.",
                "يحتاج تقييم متخصص أو لا يُنصح به روتينياً لهذه الفئة العمرية.",
            ))
            continue

        if is_renal and "nitrofurantoin" in d_low and cl_cr < 30:
            banned.append(build_banned_item(
                drug,
                "renal",
                f"ممنوع — CrCl {cl_cr:.1f} < 30 ml/min",
                f"CrCl = {cl_cr:.1f} مل/د — أقل من الحد المطلوب. لن يحقق تركيزًا بوليًا علاجيًا، وقد يتراكم مسببًا سُمية.",
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
    warned = sorted(warned, key=lambda x: x.get("priority", 999))
    preg_warn_items = sorted(preg_warn_items, key=lambda x: x.get("priority", 999))
    return allowed, warned, banned, preg_warn_items, sorted(set(interactions_alerts))

# =========================================================
# التقرير النصي
# =========================================================
def generate_report(
    age: int,
    sex: str,
    weight: float,
    cl_cr: float,
    is_renal: bool,
    is_preg: bool,
    is_hepatic: bool,
    allowed: List[Dict[str, Any]],
    warned: List[Dict[str, Any]],
    banned: List[Dict[str, Any]],
    preg_warn_items: List[Dict[str, Any]],
    organism: str,
    specimen: str,
    interactions: List[str],
    sir_map: Dict[str, str],
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    sep = "=" * 60
    sep2 = "-" * 60
    lines = []

    lines.append(sep)
    lines.append("ORANGE LAB — CLINICAL DECISION REPORT")
    lines.append(sep)
    lines.append(f"Date: {now}")
    lines.append(sep)

    lines.append("\nPATIENT DETAILS")
    lines.append(sep2)
    lines.append(f"Age      : {age} years")
    lines.append(f"Gender   : {sex}")
    lines.append(f"Weight   : {weight} kg")
    lines.append(f"Renal    : {'IMPAIRED' if is_renal else 'Normal'}")
    if is_renal:
        lines.append(f"CrCl     : {cl_cr:.1f} ml/min ({get_renal_severity(cl_cr)})")
    lines.append(f"Hepatic  : {'IMPAIRED' if is_hepatic else 'Normal'}")
    if sex == "Female":
        lines.append(f"Pregnant : {'Yes' if is_preg else 'No'}")

    lines.append("\nCULTURE")
    lines.append(sep2)
    lines.append(f"Specimen : {specimen}")
    lines.append(f"Organism : {organism}")

    if organism in ORGANISM_PROFILE:
        op = ORGANISM_PROFILE[organism]
        if op.get("note"):
            lines.append(f"Note     : {op['note']}")
        spec_ctx = (op.get("specimen_context") or {}).get(specimen, "")
        if spec_ctx:
            lines.append(f"Context  : {spec_ctx}")
        if op.get("first_line"):
            lines.append(f"First-line : {', '.join(op['first_line'])}")
        if op.get("avoid"):
            lines.append(f"Avoid      : {', '.join(op['avoid'])}")

    if sir_map:
        lines.append("\nSENSITIVITY RESULTS")
        lines.append(sep2)
        for drug, result in sorted(sir_map.items()):
            label = {"S": "Sensitive", "R": "Resistant", "I": "Intermediate"}.get(result, result)
            lines.append(f"{drug:<40} {label}")

    if interactions:
        lines.append("\nINTERACTIONS / WARNINGS")
        lines.append(sep2)
        for item in sorted(set(interactions)):
            lines.append(f"- {item}")

    lines.append("\nRECOMMENDED ANTIBIOTICS")
    lines.append(sep)
    if allowed:
        for item in allowed:
            sir_tag = f" [Culture: {sir_map.get(item['name'], '?')}]" if sir_map else ""
            preg_tag = " [Pregnancy: caution]" if (is_preg and item.get("preg_status") == "Warn") else ""
            lines.append(f"\n{item['name']}{sir_tag}{preg_tag}")
            lines.append(sep2)
            lines.append(f"WHO AWaRe : {item.get('aware', '-')}")
            lines.append(f"Class     : {item.get('class', '-')}")
            lines.append(f"Route     : {'Oral/PO-friendly' if item.get('high_po') else 'IV/IM only'}")
            spec_note = (item.get("specimen_notes") or {}).get(specimen, "")
            if spec_note:
                lines.append(f"Note      : {item.get('note', '')}")
                lines.append(f"{specimen}   : {spec_note}")
            else:
                lines.append(f"Note      : {item.get('note', '')}")
            if is_renal:
                lines.append(f"Renal     : {item.get('renal_note', '-')}")
            if is_preg and item.get("preg_status") == "Warn":
                preg_note = item.get("preg_note") or ""
                preg_first = preg_note.splitlines()[0] if preg_note.splitlines() else ""
                if preg_first:
                    lines.append(f"Pregnancy : {preg_first}")
    else:
        lines.append("No recommended options after applying all restrictions.")

    if warned:
        lines.append("\nDOSE ADJUSTMENT REQUIRED")
        lines.append(sep)
        lines.append(f"Patient CrCl = {cl_cr:.1f} ml/min\n")
        for item in warned:
            sir_tag = f" [Culture: {sir_map.get(item['name'], '?')}]" if sir_map else ""
            lines.append(f"{item['name']}{sir_tag}")
            lines.append(sep2)
            lines.append(f"WHO AWaRe : {item.get('aware', '-')}")
            lines.append(f"Renal note: {item.get('renal_note', '-')}")
            lines.append(f"Limit CrCl: <= {item.get('renal_limit', '-') } ml/min\n")

    if is_preg and preg_warn_items:
        lines.append("\nPREGNANCY — USE WITH CAUTION")
        lines.append(sep)
        for item in preg_warn_items:
            lines.append(f"{item['name']}")
            lines.append(sep2)
            for ln in (item.get("preg_note") or "").splitlines():
                lines.append(ln)
            lines.append("")

    if banned:
        lines.append("\nCONTRAINDICATED / INEFFECTIVE")
        lines.append(sep)

        grouped = {
            "resistant": [],
            "renal": [],
            "pregnancy": [],
            "child": [],
            "organism": [],
            "other": [],
        }
        for item in banned:
            grouped.setdefault(item["category"], []).append(item)

        if grouped["resistant"]:
            lines.append("\n[A] RESISTANT IN CULTURE")
            lines.append(sep2)
            for b in grouped["resistant"]:
                lines.append(f"- {b['name']} — {b['reason_detail']}")

        if grouped["renal"]:
            lines.append("\n[B] CONTRAINDICATED — RENAL IMPAIRMENT")
            lines.append(sep2)
            for b in grouped["renal"]:
                lines.append(f"- {b['name']} — {b['reason_short']}")
                detail_key = b["name"].lower().replace(" ", "")
                rendered = False
                for k, v in RENAL_BAN_REASONS.items():
                    if k in detail_key:
                        lines.extend([f"  {ln}" for ln in v.splitlines()])
                        rendered = True
                        break
                if not rendered:
                    lines.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                lines.append("")

        if grouped["pregnancy"]:
            lines.append("\n[C] CONTRAINDICATED — PREGNANCY")
            lines.append(sep2)
            for b in grouped["pregnancy"]:
                lines.append(f"- {b['name']} — {b['reason_short']}")
                lines.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                lines.append("")

        if grouped["child"]:
            lines.append("\n[D] NOT SUITABLE FOR AGE")
            lines.append(sep2)
            for b in grouped["child"]:
                lines.append(f"- {b['name']} — {b['reason_short']}")
                lines.extend([f"  {ln}" for ln in (b.get("reason_detail") or "").splitlines()])
                lines.append("")

        if grouped["organism"]:
            lines.append(f"\n[E] INEFFECTIVE FOR {organism}")
            lines.append(sep2)
            for b in grouped["organism"]:
                lines.append(f"- {b['name']} — {b['reason_detail']}")

        if grouped["other"]:
            lines.append("\n[F] OTHER CONTRAINDICATIONS")
            lines.append(sep2)
            for b in grouped["other"]:
                lines.append(f"- {b['name']} — {b['reason_detail']}")

    lines.append("\nDISCLAIMER")
    lines.append(sep)
    lines.append("هذا التقرير أداة مساعدة للقرار الطبي وليس بديلاً عن التقييم السريري.")
    lines.append("القرار النهائي للوصف العلاجي يعود للطبيب المعالج.")
    lines.append(sep)
    lines.append("Guidelines: EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | Egypt National")
    lines.append("Route info: BNF 2025 | FDA Labels | WHO AWaRe 2025")
    lines.append("WHO AWaRe : 🟢 Access | 🟡 Watch | 🔴 Reserve")
    lines.append(sep)
    lines.append("Developed by Dr / Hussein Ali | Orange Lab")
    lines.append(sep)

    return "\n".join(lines)

# =========================================================
# واجهة التطبيق
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
    file_hash = make_file_hash(file_bytes)

    if st.session_state.ocr_data is None or st.session_state.last_file_hash != file_hash:
        with st.spinner("🔍 جاري تحليل صورة التقرير..."):
            try:
                payload = extract_all_data_cached(file_bytes)
                st.session_state.ocr_data = payload
                st.session_state.last_file_hash = file_hash
            except Exception as e:
                st.error(f"تعذر تحليل الصورة: {e}")
                st.stop()

    payload = st.session_state.ocr_data
    patient = payload["patient"]
    drugs_from_ocr = payload["drugs"]
    sir_map = payload["sir_map"]
    raw_text = payload["raw_text"]

    st.image(file_bytes, caption="Preview", use_container_width=True)

    with st.expander("📝 النص المستخرج من التقرير (OCR)", expanded=False):
        st.text_area("Extracted Text", raw_text, height=220, label_visibility="collapsed")

    col1, col2 = st.columns([1.05, 1.55], gap="large")

    with col1:
        st.subheader("👤 Patient & Culture")

        culture_type = st.selectbox(
            "🧫 Specimen",
            SPECIMEN_TYPES,
            index=best_default_index(SPECIMEN_TYPES, patient.get("Specimen"))
        )

        filtered_organisms = [org for org in get_organisms_for_specimen(culture_type) if org in ORGANISM_PROFILE]
        if not filtered_organisms:
            filtered_organisms = BACTERIA_TYPES

        ocr_org = patient.get("Organism")
        organism_type = st.selectbox(
            "🦠 Organism",
            filtered_organisms,
            index=best_default_index(filtered_organisms, ocr_org),
            help=f"بكتيريا شائعة في عينة {culture_type}",
        )

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

        age = st.number_input("Age (years)", min_value=0, max_value=120, value=safe_int(patient.get("Age"), 25))
        default_sex = patient.get("Sex") if patient.get("Sex") in ["Female", "Male"] else "Male"
        sex = st.selectbox("Gender", ["Female", "Male"], index=0 if default_sex == "Female" else 1)

        weight = st.number_input(
            "Weight (kg)",
            min_value=5,
            max_value=300,
            value=70
        )

        st.divider()

        is_renal = st.checkbox("🚩 Renal Impairment")
        cl_cr = 100.0
        s_cr = 1.0

        if is_renal:
            s_cr = st.number_input(
                "Serum Creatinine (mg/dL)",
                min_value=0.1,
                max_value=20.0,
                value=1.0,
                step=0.1
            )
            cl_cr = calc_creatinine_clearance(age, weight, s_cr, sex)
            severity = get_renal_severity(cl_cr)

            st.metric(
                "CrCl (Cockcroft-Gault)",
                f"{cl_cr:.1f} ml/min",
                delta=severity,
                delta_color="normal" if cl_cr >= 60 else ("off" if cl_cr >= 30 else "inverse")
            )

        is_hepatic = st.checkbox("🚩 Hepatic Impairment")

        is_preg = False
        if sex == "Female" and 12 <= age <= 55:
            is_preg = st.checkbox("🤰 Patient is Pregnant")

        current_meds = st.multiselect("💊 Current Medications", COMMON_MEDS)

    with col2:
        st.subheader("💊 Antibiotic Analysis")

        if sir_map:
            st.info("📊 S / I / R detected: " + " | ".join(
                f"{drug}: **{result}**" for drug, result in sorted(sir_map.items())
            ))

        final_drugs = st.multiselect(
            "✅ Confirm / Edit Antibiotics",
            options=sorted(ABX_GUIDELINES.keys()),
            default=[d for d in drugs_from_ocr if d in ABX_GUIDELINES]
        )

        allowed, warned, banned, preg_warn_items, interactions_alerts = analyze_antibiotics(
            final_drugs=final_drugs,
            organism_type=organism_type,
            culture_type=culture_type,
            age=age,
            sex=sex,
            is_renal=is_renal,
            cl_cr=cl_cr,
            is_preg=is_preg,
            is_hepatic=is_hepatic,
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
                cat_label_map = {
                    "resistant": "مقاوم في المزرعة",
                    "renal": "قصور كلوي",
                    "pregnancy": "ممنوع في الحمل",
                    "child": "غير مناسب للعمر",
                    "organism": "غير فعال للجرثومة",
                    "other": "موانع أخرى",
                }
                for item in banned:
                    cat_label = cat_label_map.get(item["category"], "")
                    st.error(f"💊 {item['name']}  [{cat_label}]\n{item['reason_short']}")

        if warned:
            with st.expander("🟡 Warnings / Dose Adjustment Required", expanded=True):
                for item in warned:
                    sir_tag = f" [{sir_map.get(item['name'], '')}]" if sir_map else ""
                    if item.get("warning_reason") == "intermediate_culture":
                        st.warning(f"**{item['name']}{sir_tag}** — Intermediate (I) on culture, use only after clinical review.")
                    else:
                        st.warning(f"**{item['name']}{sir_tag}** — {item.get('renal_note', '')}")

        if allowed:
            st.success(f"🟢 {len(allowed)} Recommended Option(s)")
            for item in allowed:
                sir_badge = f" [{sir_map.get(item['name'], '?')}]" if sir_map else ""
                preg_flag = " 🤰" if (is_preg and item.get("preg_status") == "Warn") else ""
                
                aware_val = item.get('aware', 'Unknown')
                color_val = AWARE_COLORS.get(aware_val, aware_val)

                with st.expander(
                    f"{item['name']}{sir_badge}{preg_flag} — {color_val}",
                    expanded=False
                ):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Class:** {item.get('class', '-')}")
                    c2.write(f"**Route:** {get_route_label(item)}")
                    st.write(f"**Note:** {item.get('note', '-')}")
                    spec_note = (item.get("specimen_notes") or {}).get(culture_type, "")
                    if spec_note:
                        st.info(f"**{culture_type} Note:** {spec_note}")
                    if is_renal:
                        st.caption(f"Renal: {item.get('renal_note', '-')}")
                    if is_preg and item.get("preg_status") == "Warn":
                        preg_note = item.get("preg_note") or ""
                        preg_first = preg_note.splitlines()[0] if preg_note.splitlines() else ""
                        if preg_first:
                            st.caption(f"🤰 {preg_first}")
        elif not banned and not warned:
            st.info("اختر المضادات الحساسة أو المناسبة من القائمة أعلاه.")

        if final_drugs:
            st.divider()
            report_txt = generate_report(
                age=age,
                sex=sex,
                weight=weight,
                cl_cr=cl_cr,
                is_renal=is_renal,
                is_preg=is_preg,
                is_hepatic=is_hepatic,
                allowed=allowed,
                warned=warned,
                banned=banned,
                preg_warn_items=preg_warn_items,
                organism=organism_type,
                specimen=culture_type,
                interactions=interactions_alerts,
                sir_map=sir_map,
            )

            st.download_button(
                "📄 Download Clinical Report",
                data=report_txt,
                file_name=f"Orange_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                use_container_width=True,
            )

            with st.expander("📋 Report Preview (copy-friendly)", expanded=False):
                st.text_area("Clinical Report", report_txt, height=380, label_visibility="collapsed")

st.divider()
st.markdown("""
<div style="text-align:center;color:gray;font-size:0.9rem;">
  <strong>Developed by Dr / Hussein Ali | Orange Lab</strong><br>
  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | BNF 2025 | Egypt National Guidelines
</div>
""", unsafe_allow_html=True)
