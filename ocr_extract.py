"""Orange Lab — OCR & report-extraction layer.

Turns an uploaded lab-report image into structured data:

    payload = extract_all_data(file_bytes)
    # {"patient": {...}, "culture": {...}, "sir_map": {...},
    #  "detected_drugs": [...], "pus_cells": "...", "rbcs": "...",
    #  "condition": "...", "raw_text": "..."}

Extracted from the main Streamlit app so it can be unit-tested without a
browser, a session, or a rerun. Everything here is a pure function of its
arguments — no session_state, no widgets, no globals mutated. If a change to
this file needs Streamlit to test it, the change is in the wrong file.

Design rules that the bugs in this layer taught us, in order of how much they
cost:

  * ANCHOR every microscopy read to its own label's line. A regex that scans
    the whole report for ">N" will find the colony count, not the pus cells.
  * SCRUB media names before matching a specimen. "Blood agar" appears on
    nearly every culture report; "pus cells" on every urine one.
  * PREFER the longest, whole-word match, and break ties deterministically —
    "Urine" must not beat "Urine (Catheter)" because of dict ordering.
  * REFUSE to guess. Two drugs on one line with one S/I/R is not a puzzle to
    solve, it is a line to hand back to the user. A wrong S/I/R is worse than a
    missing one.
  * REQUIRE an anchor for units. "6 months" in a clinical history is not the
    patient's age.

Standards referenced by the callers of this module: EUCAST v16.1 (2026),
CLSI M100 Ed36 (2026), CLSI M39 5th ed.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from abx_guidelines import (
    ABX_ALIAS_INDEX,
    ABX_GUIDELINES,
    BACTERIA_TYPES,
    normalize_abx_key,
)
from clinical_engines import safe_int
from specimen_organism_map import SPECIMEN_ORDER

logger = logging.getLogger(__name__)

SPECIMEN_TYPES = SPECIMEN_ORDER

# Optional heavy deps. The app can run (registry, antibiogram, manual AST entry)
# without OCR installed, so importing this module must never be fatal.
try:
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image           # noqa: F401  (kept for callers/thumbnails)
    OCR_AVAILABLE = True
    OCR_IMPORT_ERROR = ""
except Exception as _imp_err:       # noqa: BLE001
    cv2 = None
    np = None
    pytesseract = None
    OCR_AVAILABLE = False
    OCR_IMPORT_ERROR = str(_imp_err)
    logger.warning("OCR dependencies unavailable: %s", _imp_err)


class OCRUnavailable(RuntimeError):
    """Raised when an OCR entry point is called without the deps installed.

    A typed exception, not st.error()+st.stop(): this module has no business
    knowing how the caller wants to tell the user. The app catches it and
    renders whatever it likes.
    """


def ensure_ocr_dependencies() -> None:
    """Raise OCRUnavailable unless cv2 / pytesseract / PIL are importable."""
    if not OCR_AVAILABLE:
        raise OCRUnavailable(
            "مكتبات الـ OCR غير متاحة: opencv-python-headless · pytesseract · Pillow. "
            f"({OCR_IMPORT_ERROR})"
        )


def normalize_ocr_text(text: str) -> str:
    cleaned = text or ""
    for old, new in {"\u2013": "-", "\u2014": "-", "\u00a0": " ", "|": " "}.items():
        cleaned = cleaned.replace(old, new)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _norm_index(text: str) -> Tuple[str, List[int]]:
    """Lowercase alphanumeric-only copy of `text`, plus a map back to raw offsets.

    Lets us search for NORMALIZED antibiotic aliases (which is what
    ABX_ALIAS_INDEX stores) inside RAW OCR text and still report where the hit
    was, so the paper's drug order is preserved.
    """
    chars: List[str] = []
    pos:   List[int] = []
    for i, ch in enumerate(text or ""):
        c = ch.lower()
        if c.isalnum():
            chars.append(c)
            pos.append(i)
    return "".join(chars), pos

def preprocess_image(file_bytes: bytes) -> Tuple[Any, Any]:
    """Decode + clean an uploaded report image for OCR.

    Returns (None, thresh). The first slot is kept only so existing callers
    (`_, thresh = preprocess_image(...)`) keep working — nothing ever consumed
    the colour image.
    """
    ensure_ocr_dependencies()
    arr  = np.frombuffer(file_bytes, np.uint8)
    # Decode STRAIGHT to grayscale. The old code decoded IMREAD_COLOR (3 bytes
    # per pixel) and then immediately threw the colour image away — on a 12 MP
    # phone photo that is ~36 MB allocated, converted, and discarded, inside a
    # ~1 GB Streamlit Cloud container. That is pure peak-memory cost, and peak
    # memory is exactly what kills a mobile upload with no error message.
    gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise ValueError("تعذر قراءة الصورة. تأكد أن الملف صورة سليمة.")
    # Bound the working resolution. Mobile photos are large (10–12 MP); a flat
    # 1.7× OCR upscale would push them past 30 MP, making denoise/threshold
    # extremely slow — a Cloud timeout that looks like a hang. So upscale small
    # scans (helps OCR) but downscale large phone photos to a capped long side.
    _h, _w = gray.shape[:2]
    _long  = max(_h, _w)
    _MAX_SIDE = 2600
    _scale = 1.7 if (_long * 1.7 <= _MAX_SIDE) else (_MAX_SIDE / float(_long))
    if abs(_scale - 1.0) > 0.02:
        _interp = cv2.INTER_CUBIC if _scale > 1 else cv2.INTER_AREA
        gray = cv2.resize(gray, None, fx=_scale, fy=_scale, interpolation=_interp)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11,
    )
    # The old `cv2.morphologyEx(thresh, MORPH_OPEN, np.ones((1,1)))` is gone:
    # a 1x1 structuring element is a mathematical no-op (erode by one pixel,
    # then dilate by one pixel, returns the input unchanged). It did nothing
    # but allocate and copy a full-size image on every upload.
    return None, thresh

def _ocr_score(txt: str) -> Tuple[int, int, int]:
    """Rank an OCR candidate by how much USABLE microbiology it yields.

    Ordered by (resolved S/I/R rows, antibiotics recognised, character count).
    The old selector was `max(outputs, key=len)` — i.e. "longest wins" — but
    length is not quality: on a grainy phone photo the longest output is
    normally the psm-11 pass, which emits piles of garbage tokens and scores
    highest precisely when it is worst. We rank by the two things the rest of
    the app actually consumes, and keep length only as a final tie-break.
    """
    drugs = extract_detected_drugs(txt)
    sir = 0
    for line in txt.splitlines():
        if classify_sir_from_line(line) and match_antibiotic_from_text(line):
            sir += 1
    return (sir, len(drugs), len(re.sub(r"\s+", "", txt)))


def run_ocr(thresh: Any) -> str:
    ensure_ocr_dependencies()
    # Six passes (3 psm x 2 langs) were run unconditionally, every one of them
    # a full Tesseract run over a 2600 px image on Streamlit Cloud's single
    # shared core — 15-30 s of wall clock that reads to the user as a hang.
    # 'ara+eng' still leads (it reads English too, and the Arabic fields matter
    # for age/sex), and we stop as soon as a pass returns a clearly readable
    # panel instead of grinding through the rest.
    attempts = [("ara+eng", "--psm 6"), ("eng", "--psm 6"),
                ("eng", "--psm 4"), ("ara+eng", "--psm 11")]
    best: Optional[str] = None
    best_score: Tuple[int, int, int] = (-1, -1, -1)
    tried = 0
    for lang, cfg in attempts:
        try:
            txt = normalize_ocr_text(
                pytesseract.image_to_string(thresh, lang=lang, config=cfg))
        except Exception as exc:
            logger.debug("OCR attempt failed (lang=%s cfg=%s): %s", lang, cfg, exc)
            continue
        if not txt:
            continue
        tried += 1
        score = _ocr_score(txt)
        if score > best_score:
            best_score, best = score, txt
        if score[0] >= 5:      # a readable panel — no need to keep grinding
            break
    if best is None:
        raise RuntimeError("OCR failed: no text extracted")
    logger.info("OCR: %d pass(es), chosen score=%s", tried, best_score)
    return best

# Age in months/days is only read when it is ANCHORED to an age label. A bare
# "6 months" floating in a clinical history ("recurrent UTI for 6 months")
# must never be mistaken for the patient's age.
_AGE_MO_RE = re.compile(
    r"(?:age|العمر|السن)\s*[:\-=]?\s*(\d{1,3})\s*(?:mo\b|mos\b|m\b|months?|شهر|شهور|أشهر)",
    re.IGNORECASE)
_AGE_DY_RE = re.compile(
    r"(?:age|العمر|السن)\s*[:\-=]?\s*(\d{1,3})\s*(?:d\b|days?|يوم|أيام)",
    re.IGNORECASE)


def detect_age_months(text: str) -> Optional[int]:
    """Age in MONTHS when the report states it in months or days, else None."""
    m = _AGE_DY_RE.search(text or "")
    if m:
        days = safe_int(m.group(1), -1)
        if 0 <= days <= 365:
            return int(round(days / 30.44))
    m = _AGE_MO_RE.search(text or "")
    if m:
        months = safe_int(m.group(1), -1)
        if 0 <= months <= 36:
            return months
    return None


def detect_age(text: str) -> Optional[int]:
    r"""Age in YEARS, or None.

    Returns None when the report states the age in months/days so that an
    infant is never silently read as an adult. The old pattern list contained
    `Age[:\s]+(\d+)` with no unit check, so "Age: 6 months" came back as 6 —
    six YEARS — and the UI then seeded a 21 kg weight (or 70 kg when the number
    was missing entirely), which propagates straight into CrCl and dosing.
    """
    if detect_age_months(text) is not None:
        return None
    for pattern in [r"(\d{1,3})\s*[Yy]ears?",
                    r"(?:Age|العمر|السن)\s*[:\-=]?\s*(\d{1,3})\b",
                    r"(\d{1,3})\s*[Yy]\b"]:
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

# Phrases that EMBED a specimen word but are not the specimen. "Blood agar" is
# printed on virtually every culture report and "Pus cells" on every urine and
# wound report, so the old `if specimen.lower() in text_lower` returned
# Specimen=Blood for sputum/wound/throat/stool and Specimen=Pus for urine —
# whichever of the two came first in SPECIMEN_ORDER. A wrong specimen is not
# cosmetic: it drives classify_specimen(), and through it the pathogenicity
# branch, the microscopy fields, the syndrome, and the treatment duration.
# NOTE "blood culture bottle" is deliberately NOT here: it is a specimen
# SIGNAL, not noise. Only culture media and microscopy/chemistry field names
# that happen to embed a specimen word are scrubbed.
_SPECIMEN_NOISE = [
    r"blood\s*agar", r"chocolate\s*agar", r"sheep\s*blood", r"horse\s*blood",
    r"cled\s*agar", r"nutrient\s*agar", r"macconkey", r"sabouraud",
    r"pus\s*cells?", r"red\s*blood\s*cells?", r"white\s*blood\s*cells?",
    r"blood\s*cells?", r"blood\s*film", r"blood\s*picture", r"blood\s*sugar",
    r"blood\s*urea", r"blood\s*group", r"occult\s*blood",
    r"stool\s*analysis", r"urine\s*analysis", r"urinalysis",
]
_SPECIMEN_LABEL = re.compile(
    r"(?:specimen|sample|source)\s*(?:type)?\s*[:\-=]\s*(.{0,60})", re.IGNORECASE)


def _best_specimen_in(scope: str) -> Optional[str]:
    """Whole-word, longest-name-wins specimen match inside `scope`."""
    best: Optional[str] = None
    best_key: Tuple[int, int, str] = (-1, -1, "")   # (name_len, hits, name)
    for specimen in SPECIMEN_TYPES:
        needle = specimen.lower()
        hits = len(re.findall(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", scope))
        if hits <= 0:
            continue
        key = (len(needle), hits, specimen)
        if key > best_key:
            best_key, best = key, specimen
    return best


def detect_specimen(text_lower: str) -> Optional[str]:
    """Detect the specimen named in OCR text.

    Two passes. An explicit "Specimen: ..." / "Sample: ..." field is by far the
    most reliable statement on the page, so it is read first and on its own.
    Only if there is no such field do we scan the whole report — and then only
    after scrubbing media/microscopy phrases, with whole-word matching that
    prefers the MOST SPECIFIC (longest) name and a deterministic tie-break, the
    same way detect_organism() already works.
    """
    def _scrubbed(s: str) -> str:
        for pat in _SPECIMEN_NOISE:
            s = re.sub(pat, " ", s)
        return s

    m = _SPECIMEN_LABEL.search(text_lower or "")
    if m:
        hit = _best_specimen_in(_scrubbed(m.group(1)))
        if hit:
            return hit
    return _best_specimen_in(_scrubbed(text_lower or ""))

def detect_organism(text_lower: str) -> Optional[str]:
    """Detect the organism named in OCR text.

    Uses whole-phrase boundary matching so a genus ('Staphylococcus') inside a
    species ('Staphylococcus aureus') is not double-counted, and prefers the
    MOST SPECIFIC (longest) name. Ties break by (occurrences, name) so the
    result is deterministic regardless of dict ordering.
    """
    best: Optional[str] = None
    best_key: Tuple[int, int, str] = (-1, -1, "")  # (name_len, hits, name)
    for organism in BACTERIA_TYPES:
        needle = organism.lower()
        hits = len(re.findall(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])",
                              text_lower))
        if hits <= 0:
            continue
        key = (len(needle), hits, organism)
        if key > best_key:
            best_key = key
            best = organism
    return best

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

def match_antibiotics_in_line(snippet: str) -> List[str]:
    """Every distinct antibiotic named in ONE line (longest alias wins a span).

    match_antibiotic_from_text() returns a single name, which is unsafe for the
    two-column AST layouts common on printed Egyptian reports: a row like
    "Amoxicillin  R      Ciprofloxacin  S" has one trailing S/I/R as far as
    classify_sir_from_line() is concerned, and the old code pinned it onto
    whichever drug matched first — silently attaching a result to the wrong
    antibiotic. Callers use the length of this list to decide whether the line
    can be trusted at all.
    """
    snippet_norm = normalize_abx_key(snippet)
    if not snippet_norm:
        return []
    found: List[str] = []
    for alias_norm, abx_name in sorted(ABX_ALIAS_INDEX.items(),
                                       key=lambda kv: len(kv[0]), reverse=True):
        if not alias_norm or len(alias_norm) < 4:
            continue
        if alias_norm in snippet_norm:
            if abx_name not in found:
                found.append(abx_name)
            # Blank the matched span so a shorter alias sitting INSIDE it
            # (e.g. "amoxicillin" within "amoxicillinclavulanate") cannot
            # re-fire and fake a second drug.
            snippet_norm = snippet_norm.replace(alias_norm, " " * len(alias_norm))
    return found


def extract_detected_drugs(full_text: str) -> List[str]:
    """
    Scans OCR text for ANY antibiotic name — regardless of S/I/R presence.
    Uses multiple strategies: per-line, per-word, substring matching.

    الترتيب = ترتيب ظهور المضاد في الورقة، مش أبجدي.
    الإصدار القديم كان بيجمّع الأسماء في set() ويرجّع sorted(detected)، فالقائمة
    كانت بتطلع مرتبة أبجدياً ومش مطابقة لورقة الـ AST المطبوعة. ولمّا OCR بيفشل
    في قراءة S/I/R لكذا مضاد (حالة شائعة) الأدوية دي بتظهر أبجدي وبتتضاف لآخر
    القائمة الموحّدة بنفس الترتيب الأبجدي — فالشاشة مش بتماشي الورقة والمستخدم
    يقدر يحطّ النتيجة على المضاد الغلط. بنسجّل هنا أول موضع ظهور لكل مضاد في
    نص الـ OCR ونرتّب بيه.
    """
    text_lower = full_text.lower()
    first_pos: Dict[str, int] = {}

    def _note(abx_name: Optional[str], pos: int) -> None:
        if abx_name and pos < first_pos.get(abx_name, 1 << 30):
            first_pos[abx_name] = pos

    # Strategy 1: per-line match — الموضع = بداية السطر داخل النص الكامل
    _offset = 0
    for raw_line in full_text.splitlines(keepends=True):
        line = raw_line.strip()
        if len(line) >= 3:
            _note(match_antibiotic_from_text(line), _offset)
        _offset += len(raw_line)

    # Strategy 2: direct alias scan.
    # ABX_ALIAS_INDEX keys are NORMALIZED (normalize_abx_key), but the old code
    # searched for them inside the RAW lowercase text. Any alias whose normal
    # form differs from its printed form — i.e. anything containing a space, a
    # hyphen or a slash: "amoxicillin-clavulanate",
    # "trimethoprim/sulfamethoxazole", "piperacillin-tazobactam" — could never
    # match, so this whole strategy was dead for exactly the drugs OCR is most
    # likely to mangle. We scan a normalized copy and map the hit back to its
    # offset in the raw text (raw scan kept too; a union can only help).
    norm_text, norm_pos = _norm_index(full_text)
    alias_items = sorted(ABX_ALIAS_INDEX.items(), key=lambda x: len(x[0]), reverse=True)
    for alias_norm, abx_name in alias_items:
        if len(alias_norm) >= 4:
            _p = norm_text.find(alias_norm)
            if _p >= 0:
                _note(abx_name, norm_pos[_p])
            _p_raw = text_lower.find(alias_norm)
            if _p_raw >= 0:
                _note(abx_name, _p_raw)

    # Strategy 3: check ABX_GUIDELINES keys and their own alias lists.
    for abx_name, _info in ABX_GUIDELINES.items():
        for variant in [abx_name, *(_info.get("aliases", []) or [])]:
            if len(variant) < 4:
                continue
            _p = text_lower.find(variant.lower())
            if _p >= 0:
                _note(abx_name, _p)
                continue
            _vn = re.sub(r"[^a-z0-9]", "", variant.lower())
            if len(_vn) >= 4:
                _p2 = norm_text.find(_vn)
                if _p2 >= 0:
                    _note(abx_name, norm_pos[_p2])

    # ترتيب الورقة. الاسم مجرد كسر تعادل لضمان نتيجة ثابتة لو اتساوى الموضع.
    return [name for name, _ in sorted(first_pos.items(),
                                       key=lambda kv: (kv[1], kv[0]))]

_CELL_TNTC  = r"tntc|too\s+numerous|innumerable|uncountable|numerous"
_CELL_VALUE = r"(\d{1,4}\s*[-–]\s*\d{1,4}|\d{1,4})"
_PUS_LABEL  = (r"pus\s*cells?|wbcs?|w\.b\.c|leu[ck]ocytes?|"
               r"صديد|خلايا\s*صديدية|كرات\s*صديد")
_RBC_LABEL  = (r"rbcs?|r\.b\.c|red\s*blood\s*cells?|erythrocytes?|"
               r"كريات\s*حمراء|كرات\s*دم\s*حمراء")


def _cells_on_line(text: str, label_pat: str) -> str:
    """Read a microscopy cell count from the line carrying `label_pat` — only.

    Scoping matters more than cleverness here. The old detect_pus_cells()
    scanned the WHOLE report for 'TNTC', 'Over N', '>N' and '+++' BEFORE it
    looked at the pus line, so on an ordinary urine report:

        Colony Count: > 100000 CFU/mL
        Pus cells : 4 - 6 /HPF

    it returned ">100000" — the colony count — as the pus cell value. Same for
    "Over 100,000 CFU/mL" (-> "Over 100") and for a "+++" written against
    epithelial cells (-> ">100"). That number was auto-filled into the form, fed
    to assess_pathogenicity() as florid pyuria, and printed on the report.

    Here nothing is read unless it sits on the label's own line, AFTER the
    label, so a value belonging to another field can never leak in.
    """
    for raw in (text or "").splitlines():
        line = raw.strip().lower()
        if not line:
            continue
        m_lbl = re.search(label_pat, line)
        if not m_lbl:
            continue
        tail = line[m_lbl.end():]          # cut everything before the label
        if re.search(_CELL_TNTC, tail):
            return "TNTC"
        m = re.search(r"over\s*(\d{1,4})", tail)
        if m:
            return f"Over {m.group(1)}"
        m = re.search(r"[>≥]\s*(\d{1,4})", tail)
        if m:
            return f">{m.group(1)}"
        m = re.search(_CELL_VALUE, tail)
        if m:
            return m.group(1).strip()
        if re.search(r"\+{3,}|كثير", tail):
            return ">100"
        if re.search(r"\bnil\b|\bnone\b|\babsent\b|لا\s*يوجد", tail):
            return "0"
    return ""


def detect_pus_cells(text: str) -> str:
    """Pus cells / WBCs, read from the pus/WBC line only. See _cells_on_line."""
    return _cells_on_line(text, _PUS_LABEL)


def detect_rbcs(text: str) -> str:
    """RBCs, read from the RBC/red-cell line only.

    The "second /HPF line must be the RBCs" fallback is deliberately gone: it
    guessed from layout, and a guess that silently writes a number into a
    clinical report is worse than an empty field the user fills in.
    """
    return _cells_on_line(text, _RBC_LABEL)


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


def extract_all_data(file_bytes: bytes) -> Dict[str, Any]:
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
        hits = match_antibiotics_in_line(line)
        if len(hits) == 1:
            sir_map[hits[0]] = result
        elif len(hits) > 1:
            # Two-column AST sheet. classify_sir_from_line() sees ONE trailing
            # S/I/R for a row holding TWO drugs, and the old code handed it to
            # match_antibiotic_from_text() — which returns a single name — and
            # pinned the result on it. That silently reports one drug's result
            # against another drug. We refuse to guess: the drugs still appear
            # in the "OCR found, no S/I/R" panel for the user to fill in.
            logger.info("Ambiguous AST line (%d drugs) left for manual entry: %r",
                        len(hits), line[:80])
    return {
        "patient": {
            "Name":     None,  # الاسم يُدخل يدوياً فقط
            "Age":      detect_age(full_text),
            "AgeMonths": detect_age_months(full_text),
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
