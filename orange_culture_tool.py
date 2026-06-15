# © 2025 Dr. Hussein Ali — Orange Lab, 6 October City, Egypt
# Orange Culture Tool — All Rights Reserved
# Unauthorized copying or distribution is prohibited.

import json
import re
import time
import hashlib
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Tuple, Any

import cv2
import numpy as np
import pytesseract
import streamlit as st

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
SESSION_TIMEOUT = 30 * 60  # 30 minutes

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
    "Valproic acid (مضادات الصرع)"
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
def normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())

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

def build_alias_index(abx_guidelines: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    index = {}
    for abx_name, info in abx_guidelines.items():
        variants = {abx_name, *info.get("aliases", [])}
        for variant in variants:
            index[normalize_key(variant)] = abx_name
    return index

# =========================================================
# صفحة تسجيل الدخول
# =========================================================
def get_subscription_days_left(email: str) -> int | None:
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
    st.rerun()

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
# قواعد البيانات السريرية — مفصولة في ملفات مستقلة
#       1) abx_guidelines.py        -> ABX_GUIDELINES
#       2) organism_profile.py      -> ORGANISM_PROFILE
#       3) specimen_organism_map.py -> SPECIMEN_ORGANISM_MAP
# =========================================================
from abx_guidelines import ABX_GUIDELINES
from organism_profile import ORGANISM_PROFILE
from specimen_organism_map import SPECIMEN_ORGANISM_MAP

BACTERIA_TYPES = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES = ["Urine", "Blood", "Sputum", "Wound Swab", "Pus", "Stool", "CSF"]
ABX_ALIAS_INDEX = build_alias_index(ABX_GUIDELINES)

# =========================================================
# OCR ومعالجة الصور
# =========================================================
def preprocess_image(file_bytes: bytes) -> tuple[np.ndarray, np.ndarray]:
    arr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("تعذر قراءة الصورة. تأكد أن الملف صورة سليمة.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # تحسين الجودة
    gray = cv2.resize(gray, None, fx=1.7, fy=1.7, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)

    # Adaptive threshold أفضل مع صور التقارير
    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 11
    )

    # Morphology خفيف لتحسين الحروف
    kernel = np.ones((1, 1), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)

    return img, thresh

def detect_age(text: str) -> str:
    patterns = [
        r"(\d+)\s*[Yy]ears?",
        r"Age[:\s]+(\d+)",
        r"(\d+)\s*[Yy]\b"
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return "25"

def detect_sex(text_lower: str) -> str:
    if "female" in text_lower or "sex: f" in text_lower or "gender: female" in text_lower:
        return "Female"
    return "Male"

def detect_specimen(text_lower: str) -> str:
    for specimen in SPECIMEN_TYPES:
        if specimen.lower() in text_lower:
            return specimen
    return "Urine"

def detect_organism(text_lower: str) -> str:
    organism_counts = {}
    for organism in BACTERIA_TYPES:
        count = text_lower.count(organism.lower())
        if count > 0:
            organism_counts[organism] = count
    if organism_counts:
        return max(organism_counts, key=organism_counts.get)
    return "E. coli"

def classify_sir_from_line(line: str) -> str | None:
    ll = line.lower().strip()

    if re.search(r"\b(s|sensitive|susceptible|sens)\b", ll):
        return "S"
    if re.search(r"\b(r|resistant|resist)\b", ll):
        return "R"
    if re.search(r"\b(i|intermediate|inter)\b", ll):
        return "I"
    return None

def match_antibiotic_from_text(snippet: str) -> str | None:
    snippet_norm = normalize_key(snippet)

    # direct fast lookup
    for alias_norm, abx_name in ABX_ALIAS_INDEX.items():
        if alias_norm and alias_norm in snippet_norm:
            return abx_name

    # fuzzy fallback
    best_match = None
    best_score = 0.0

    for abx_name, info in ABX_GUIDELINES.items():
        for variant in [abx_name] + info.get("aliases", []):
            score = fuzzy_match(variant, snippet)
            if score > best_score:
                best_score = score
                best_match = abx_name

    return best_match if best_score >= 75 else None

def extract_detected_drugs(full_text: str) -> List[str]:
    text_lower = full_text.lower()
    detected = set()

    words = re.findall(r"[A-Za-z0-9\-\+\/\.]+", text_lower)

    for abx_name, info in ABX_GUIDELINES.items():
        variants = [abx_name] + info.get("aliases", [])
        found = False
        for variant in variants:
            variant_words = variant.lower().split()
            for word in words:
                if any(fuzzy_match(word, vw) >= 82 for vw in variant_words):
                    found = True
                    break
            if found:
                break
        if found:
            detected.add(abx_name)

    return sorted(detected)

@st.cache_data(show_spinner=False)
def extract_all_data_cached(file_bytes: bytes) -> Dict[str, Any]:
    try:
        _, thresh = preprocess_image(file_bytes)
        full_text = pytesseract.image_to_string(thresh, config="--psm 6")
    except Exception as e:
        raise RuntimeError(f"OCR failed: {e}")

    text_lower = full_text.lower()

    detected_age = detect_age(full_text)
    detected_sex = detect_sex(text_lower)
    detected_specimen = detect_specimen(text_lower)
    detected_organism = detect_organism(text_lower)

    sir_map = {}
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

    detected_drugs = extract_detected_drugs(full_text)

    return {
        "patient": {
            "Age": detected_age,
            "Sex": detected_sex,
            "Specimen": detected_specimen,
            "Organism": detected_organism,
        },
        "drugs": detected_drugs,
        "sir_map": sir_map,
        "raw_text": full_text,
    }

# =========================================================
# التحليل السريري
# =========================================================
def is_intrinsically_avoided(organism_type: str, drug_name: str, drug_info: Dict[str, Any]) -> bool:
    organism_avoid = ORGANISM_PROFILE.get(organism_type, {}).get("avoid", [])
    d_low = drug_name.lower()
    d_class = drug_info.get("class", "").lower()

    for avoid_item in organism_avoid:
        av_low = avoid_item.lower().strip()

        # direct match
        if av_low in d_low or d_low in av_low:
            return True

        # class map
        mapped_classes = ORGANISM_AVOID_CLASS_MAP.get(av_low)
        if mapped_classes and any(cls in d_class for cls in mapped_classes):
            return True

    return False

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
    allowed = []
    warned = []
    banned = []
    preg_warn_items = []
    interactions_alerts = []

    for drug in final_drugs:
        if drug not in ABX_GUIDELINES:
            continue

        info = ABX_GUIDELINES[drug]
        d_low = drug.lower()
        cls = info.get("class", "").lower()

        # مقاوم بالمزرعة
        if sir_map.get(drug) == "R":
            banned.append({
                "name": drug,
                "category": "resistant",
                "reason_short": "مقاوم (R) في نتيجة المزرعة.",
                "reason_detail": (
                    f"المزرعة أثبتت أن {drug} لا يثبط نمو الجرثومة.\n"
                    "MIC أعلى من الحد العلاجي المتوقع → خطر فشل علاجي مرتفع."
                ),
            })
            continue

        # تعارضات دوائية
        for med in current_meds:
            if med in info.get("interacts_with", []):
                interactions_alerts.append(f"⚡ تعارض: {drug} مع {med}")

        # تحذير كبدي
        if is_hepatic and info.get("hepatic_caution"):
            interactions_alerts.append(f"🏥 تحذير كبدي: {drug} — يحتاج متابعة أو تعديل حسب الحالة.")

        # intrinsic resistance
        if is_intrinsically_avoided(organism_type, drug, info):
            banned.append({
                "name": drug,
                "category": "organism",
                "reason_short": f"غير فعال لـ {organism_type} طبيعياً.",
                "reason_detail": (
                    f"{drug} لديه مقاومة طبيعية أو عدم فعالية متوقعة ضد {organism_type}.\n"
                    "استخدامه قد يؤدي إلى فشل علاجي."
                ),
            })
            continue

        # MRSA special logic
        if organism_type == "MRSA":
            if any(x in info.get("class", "") for x in ["Penicillin", "Cephalosporin"]):
                banned.append({
                    "name": drug,
                    "category": "organism",
                    "reason_short": "بيتا-لاكتام — لا يعمل على MRSA.",
                    "reason_detail": (
                        "MRSA يحمل آلية مقاومة mecA / PBP2a، لذلك معظم البيتا-لاكتام غير فعالة."
                    ),
                })
                continue

        # pregnancy banned
        if is_preg and info.get("preg_status") == "Banned":
            banned.append({
                "name": drug,
                "category": "pregnancy",
                "reason_short": info.get("preg_note", "ممنوع في الحمل").splitlines()[0],
                "reason_detail": info.get("preg_note", "ممنوع في الحمل"),
            })
            continue

        # pregnancy warning
        if is_preg and info.get("preg_status") == "Warn":
            preg_warn_items.append({"name": drug, **info})

        # children
        if age < 18 and not info.get("child_safe", True):
            if "fluoroquinolone" in cls:
                banned.append({
                    "name": drug,
                    "category": "child",
                    "reason_short": "غير مناسب < 18 سنة.",
                    "reason_detail": CHILD_BAN_REASONS["fluoroquinolone"],
                })
                continue
            elif "tetracycline" in cls and age < 8:
                banned.append({
                    "name": drug,
                    "category": "child",
                    "reason_short": "غير مناسب < 8 سنوات.",
                    "reason_detail": CHILD_BAN_REASONS["tetracycline"],
                })
                continue
            else:
                banned.append({
                    "name": drug,
                    "category": "child",
                    "reason_short": "غير مفضل للأطفال.",
                    "reason_detail": "يحتاج تقييم متخصص أو لا يُنصح به روتينياً لهذه الفئة العمرية.",
                })
                continue

        # renal absolute ban
        if is_renal and "nitrofurantoin" in d_low and cl_cr < 30:
            banned.append({
                "name": drug,
                "category": "renal",
                "reason_short": f"ممنوع — CrCl {cl_cr:.1f} < 30 ml/min",
                "reason_detail": (
                    f"CrCl = {cl_cr:.1f} مل/د — أقل من الحد المطلوب.\n"
                    "لن يحقق تركيزًا بوليًا علاجيًا، وقد يتراكم مسببًا سُمية."
                ),
            })
            continue

        # renal dose adjustment
        renal_limit = info.get("renal_limit", 0)
        if is_renal and renal_limit > 0 and cl_cr <= renal_limit:
            warned.append({"name": drug, **info})
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
        spec_ctx = op.get("specimen_context", {}).get(specimen, "")
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
            spec_note = item.get("specimen_notes", {}).get(specimen, "")
            if spec_note:
                lines.append(f"Note      : {item.get('note', '')}")
                lines.append(f"{specimen}   : {spec_note}")
            else:
                lines.append(f"Note      : {item.get('note', '')}")
            if is_renal:
                lines.append(f"Renal     : {item.get('renal_note', '-')}")
            if is_preg and item.get("preg_status") == "Warn":
                lines.append(f"Pregnancy : {item.get('preg_note', '').splitlines()[0]}")
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
            for ln in item.get("preg_note", "").splitlines():
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
                    lines.extend([f"  {ln}" for ln in b["reason_detail"].splitlines()])
                lines.append("")

        if grouped["pregnancy"]:
            lines.append("\n[C] CONTRAINDICATED — PREGNANCY")
            lines.append(sep2)
            for b in grouped["pregnancy"]:
                lines.append(f"- {b['name']} — {b['reason_short']}")
                lines.extend([f"  {ln}" for ln in b["reason_detail"].splitlines()])
                lines.append("")

        if grouped["child"]:
            lines.append("\n[D] NOT SUITABLE FOR AGE")
            lines.append(sep2)
            for b in grouped["child"]:
                lines.append(f"- {b['name']} — {b['reason_short']}")
                lines.extend([f"  {ln}" for ln in b["reason_detail"].splitlines()])
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
    lines.append("Developed by: Dr. Hussein Ali | Orange Lab")
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
            st.rerun()
    st.stop()

handle_session_timeout()
render_top_bar()

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
            index=SPECIMEN_TYPES.index(patient["Specimen"])
            if patient["Specimen"] in SPECIMEN_TYPES else 0
        )

        filtered_organisms = [
            org for org in SPECIMEN_ORGANISM_MAP.get(culture_type, BACTERIA_TYPES)
            if org in ORGANISM_PROFILE
        ]

        ocr_org = patient["Organism"]
        default_idx = filtered_organisms.index(ocr_org) if ocr_org in filtered_organisms else 0

        organism_type = st.selectbox(
            "🦠 Organism",
            filtered_organisms,
            index=default_idx,
            help=f"بكتيريا شائعة في عينة {culture_type}"
        )

        if organism_type in ORGANISM_PROFILE:
            op = ORGANISM_PROFILE[organism_type]
            with st.expander("📌 Organism Guidance", expanded=True):
                st.info(op.get("note", ""))
                spec_ctx = op.get("specimen_context", {}).get(culture_type, "")
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
            "Age (years)",
            min_value=0,
            max_value=120,
            value=safe_int(patient["Age"], 25)
        )

        sex = st.selectbox(
            "Gender",
            ["Female", "Male"],
            index=0 if patient["Sex"] == "Female" else 1
        )

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
                    for line in item.get("preg_note", "").splitlines():
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
            with st.expander("🟡 Dose Adjustment Required", expanded=True):
                for item in warned:
                    sir_tag = f" [{sir_map.get(item['name'], '')}]" if sir_map else ""
                    st.warning(f"**{item['name']}{sir_tag}** — {item.get('renal_note', '')}")

        if allowed:
            st.success(f"🟢 {len(allowed)} Recommended Option(s)")
            for item in allowed:
                sir_badge = f" [{sir_map.get(item['name'], '?')}]" if sir_map else ""
                preg_flag = " 🤰" if (is_preg and item.get("preg_status") == "Warn") else ""

                with st.expander(
                    f"{item['name']}{sir_badge}{preg_flag} — {AWARE_COLORS.get(item['aware'], item['aware'])}",
                    expanded=False
                ):
                    c1, c2 = st.columns(2)
                    c1.write(f"**Class:** {item.get('class', '-')}")
                    c2.write(f"**Route:** {get_route_label(item)}")
                    st.write(f"**Note:** {item.get('note', '-')}")
                    spec_note = item.get("specimen_notes", {}).get(culture_type, "")
                    if spec_note:
                        st.info(f"**{culture_type} Note:** {spec_note}")
                    if is_renal:
                        st.caption(f"Renal: {item.get('renal_note', '-')}")
                    if is_preg and item.get("preg_status") == "Warn":
                        preg_first = item.get("preg_note", "").splitlines()[0] if item.get("preg_note") else ""
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

st.divider()
st.markdown("""
<div style="text-align:center;color:gray;font-size:0.9rem;">
  <strong>Developed by: Dr. Hussein Ali | Orange Lab</strong><br>
  EUCAST 2026 | CLSI M100 2026 | IDSA AMR 2025 | BNF 2025 | Egypt National Guidelines
</div>
""", unsafe_allow_html=True)
