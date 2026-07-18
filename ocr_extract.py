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

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from abx_guidelines import (
    ABX_ALIAS_INDEX,
    ABX_GUIDELINES,
    DEFAULT_SPECIMENS,
    normalize_abx_key,
)
from clinical_engines import fuzzy_match, safe_int
from organism_profile import ORGANISM_PROFILE
from specimen_organism_map import SPECIMEN_ORDER

logger = logging.getLogger(__name__)

# Derived exactly as the monolith derived them, from the same single source of
# truth, so the OCR layer can never drift out of step with the organism list or
# the specimen list the rest of the app offers.
BACTERIA_TYPES = list(ORGANISM_PROFILE.keys())
SPECIMEN_TYPES = list(SPECIMEN_ORDER or DEFAULT_SPECIMENS)

# Optional heavy deps. The app can run (registry, antibiogram, manual AST entry)
# without OCR installed, so importing this module must never be fatal.
try:
    import cv2
    import numpy as np
    import pytesseract
    from PIL import Image, ImageOps  # ImageOps.exif_transpose fixes phone rotation
    OCR_AVAILABLE = True
    OCR_IMPORT_ERROR = ""
except Exception as _imp_err:       # noqa: BLE001
    cv2 = None
    np = None
    pytesseract = None
    Image = ImageOps = None
    OCR_AVAILABLE = False
    OCR_IMPORT_ERROR = str(_imp_err)
    logger.warning("OCR dependencies unavailable: %s", _imp_err)

# Optional HEIC/HEIF decoder. iPhones and recent Android phones save photos as
# HEIC by default; OpenCV cannot decode it. If pillow-heif is installed it
# registers a Pillow plugin so Image.open() handles HEIC transparently. Its
# absence is not fatal — HEIC simply falls back to the OpenCV path and, if that
# also fails, the user gets a clear "couldn't read the image" message rather
# than a silent failure.
try:
    from pillow_heif import register_heif_opener  # type: ignore
    register_heif_opener()
    HEIF_AVAILABLE = True
except Exception:                    # noqa: BLE001
    HEIF_AVAILABLE = False


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

# The alias index sorted longest-first. Every matcher below wants this, and each
# of them used to rebuild it with `sorted(ABX_ALIAS_INDEX.items(), ...)` on EVERY
# CALL — and match_antibiotic_from_text() is called once per line of OCR text.
# On a 260-line psm-11 dump that is 260 sorts of the whole index to answer 260
# questions whose answer never changes. Built once, here.
_ALIAS_SORTED: Optional[List[Tuple[str, str]]] = None
_ALIAS_LONG: Optional[List[Tuple[str, str]]] = None


def _alias_sorted() -> List[Tuple[str, str]]:
    global _ALIAS_SORTED
    if _ALIAS_SORTED is None:
        _ALIAS_SORTED = sorted(ABX_ALIAS_INDEX.items(),
                               key=lambda kv: len(kv[0]), reverse=True)
    return _ALIAS_SORTED


def _alias_long() -> List[Tuple[str, str]]:
    """Aliases long enough to be worth a substring scan (>= 5 chars)."""
    global _ALIAS_LONG
    if _ALIAS_LONG is None:
        _ALIAS_LONG = [(k, v) for k, v in _alias_sorted() if k and len(k) >= 5]
    return _ALIAS_LONG


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

_LAPLACIAN_K = None  # lazily built once np is known to be present


def _decode_to_gray(file_bytes: bytes):
    """Decode any uploaded image to an upright grayscale ndarray.

    Two decoders, in order:

      1. PIL (+ pillow-heif when installed). This is FIRST because it is the one
         that can read the formats phones actually produce — HEIC/HEIF and WEBP —
         which OpenCV cannot, and because ImageOps.exif_transpose() applies the
         EXIF Orientation tag. Phone cameras store the sensor image sideways and
         record "rotate 90°" in EXIF; a decoder that ignores it hands OCR a
         rotated page and every line comes back as gibberish. (cv2.imdecode does
         honour EXIF, but it can't open HEIC, so PIL leads and cv2 backs it up.)

      2. cv2.imdecode straight to grayscale — the fallback for anything PIL
         cannot handle, still cheaper than decoding colour and discarding it.

    Raises ValueError only when BOTH fail, so the caller can show one clear
    message instead of the file silently doing nothing.
    """
    gray = None

    if Image is not None:
        try:
            im = Image.open(io.BytesIO(file_bytes))
            im = ImageOps.exif_transpose(im)      # honour phone rotation
            im = im.convert("L")                  # grayscale
            gray = np.asarray(im)
        except Exception as exc:
            logger.info("PIL decode failed (%s) — trying OpenCV.", exc)

    if gray is None and cv2 is not None:
        arr = np.frombuffer(file_bytes, np.uint8)
        # imdecode reads EXIF orientation itself; do NOT pass IGNORE_ORIENTATION.
        gray = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)

    if gray is None:
        raise ValueError(
            "تعذّرت قراءة الصورة. لو الصورة من آيفون (صيغة HEIC) جرّب تصدّرها كـ "
            "JPG، أو ارفع لقطة شاشة للتقرير."
        )
    return gray


def _estimate_noise_sigma(gray) -> float:
    """Fast Gaussian-noise estimate (Immerkær 1996) on a centre crop.

    One Laplacian convolution over a 600×600 window near the centre — about a
    millisecond even on a phone photo — used only to DECIDE how hard to denoise.
    We measure before blurring so the estimate reflects the real sensor noise.
    """
    global _LAPLACIAN_K
    if _LAPLACIAN_K is None:
        _LAPLACIAN_K = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    h, w = gray.shape[:2]
    y0, x0 = max(0, h // 2 - 300), max(0, w // 2 - 300)
    patch = gray[y0:y0 + 600, x0:x0 + 600].astype(np.float32)
    if patch.size < 1024:
        patch = gray.astype(np.float32)
    H, W = patch.shape
    s = float(np.abs(cv2.filter2D(patch, -1, _LAPLACIAN_K)).sum())
    return s * 1.2533141 / (6.0 * max(W - 2, 1) * max(H - 2, 1))  # sqrt(pi/2)/6


def preprocess_image(file_bytes: bytes) -> Tuple[Any, Any]:
    """Decode + clean an uploaded report image for OCR.

    Returns (None, thresh). The first slot is kept only so existing callers
    (`_, thresh = preprocess_image(...)`) keep working — nothing ever consumed
    the colour image.
    """
    ensure_ocr_dependencies()
    gray = _decode_to_gray(file_bytes)

    # Bound the working resolution. Mobile photos are large (10–12 MP); a flat
    # 1.7× OCR upscale would push them past 30 MP, making denoise/threshold
    # extremely slow — a Cloud timeout that looks like a hang. So upscale small
    # scans (helps OCR) but downscale large phone photos to a capped long side.
    _h, _w = gray.shape[:2]
    _long  = max(_h, _w)
    _MAX_SIDE = 2600
    _scale = 1.7 if (_long * 1.7 <= _MAX_SIDE) else (_MAX_SIDE / float(_long))

    # Noise estimate on the ORIGINAL pixels (before any blur), used to pick the
    # denoiser. fastNlMeansDenoising is excellent but costs ~3–4 s on a 2600 px
    # image on Streamlit Cloud's shared core, and it was running on EVERY upload
    # including clean flatbed scans that gain nothing from it — dead time that
    # reads to a phone user as a stuck upload. Now: skip it when the image is
    # already clean, use a cheap median for light noise, and reserve the
    # expensive NL-means for genuinely noisy photos where it changes the OCR.
    try:
        _sigma = _estimate_noise_sigma(gray)
    except Exception as _ne:
        logger.debug("noise estimate failed (%s) — assuming noisy.", _ne)
        _sigma = 99.0

    if abs(_scale - 1.0) > 0.02:
        _interp = cv2.INTER_CUBIC if _scale > 1 else cv2.INTER_AREA
        gray = cv2.resize(gray, None, fx=_scale, fy=_scale, interpolation=_interp)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    if _sigma >= 4.5:
        gray = cv2.fastNlMeansDenoising(gray, None, 10, 7, 15)
        logger.info("preprocess: sigma=%.1f → NL-means denoise", _sigma)
    elif _sigma >= 2.0:
        gray = cv2.medianBlur(gray, 3)
        logger.info("preprocess: sigma=%.1f → median denoise", _sigma)
    else:
        logger.info("preprocess: sigma=%.1f → no denoise (clean image)", _sigma)

    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11,
    )
    return None, thresh

def _ocr_score(txt: str) -> Tuple[int, int, int]:
    """Rank an OCR candidate by how much usable microbiology it yields — CHEAPLY.

    Ordered by (S/I/R rows resolved, distinct antibiotics seen, character count).

    Replacing `max(outputs, key=len)` was right — length is not quality, and on a
    grainy phone photo the longest output is normally the psm-11 pass emitting
    garbage, so "longest wins" scored it highest exactly when it was worst.
    Scoring it by calling the real extractor was NOT right, and it hung the app:

        extract_detected_drugs() runs match_antibiotic_from_text() per line, and
        that falls through to fuzzy_match() — a SequenceMatcher — against every
        alias of every drug. This function then did the SAME per-line fuzzy scan
        a second time in its own loop. run_ocr() called all of that once per
        candidate. On a 260-line noisy dump that is tens of thousands of
        SequenceMatcher calls per pass, times four passes, on Streamlit Cloud's
        shared core: the spinner never returns, the socket drops, and the upload
        looks rejected.

    A selector between candidates does not need to be right about which drug is
    on a line — only about which candidate has MORE drugs on it. Exact
    normalized substring, one pass over the text, no fuzzy matching. The precise
    (expensive) extraction still runs — once, on the winner, where it belongs.
    """
    norm = re.sub(r"[^a-z0-9]", "", txt.lower())
    seen = set()
    for alias_norm, abx_name in _alias_long():
        if abx_name not in seen and alias_norm in norm:
            seen.add(abx_name)
    sir = sum(1 for line in txt.splitlines() if classify_sir_from_line(line))
    return (sir, len(seen), len(re.sub(r"\s+", "", txt)))


def _auto_rotate_by_osd(thresh: Any) -> Any:
    """Return `thresh` rotated upright when Tesseract's OSD is confident it is not.

    A phone held upside-down or sideways yields a page whose EXIF is already
    correct (nothing to transpose) but whose CONTENT is rotated — and psm-6/4
    read rotated lines as noise, so the whole panel comes back empty for a photo
    that is otherwise perfect. image_to_osd asks Tesseract which way is up; if it
    reports a non-zero rotation with reasonable confidence we rotate once and
    hand the upright image back. Cheap, and only invoked when the normal passes
    have already failed (see run_ocr), so it costs nothing on the common path.
    """
    try:
        osd = pytesseract.image_to_osd(thresh)
    except Exception as exc:                      # OSD needs the tesseract osd data
        logger.info("OSD unavailable (%s) — skipping auto-rotate.", exc)
        return thresh
    m_rot = re.search(r"Rotate:\s*(\d+)", osd)
    m_conf = re.search(r"Orientation confidence:\s*([\d.]+)", osd)
    rot  = int(m_rot.group(1)) if m_rot else 0
    conf = float(m_conf.group(1)) if m_conf else 0.0
    if rot in (90, 180, 270) and conf >= 1.0:
        # "Rotate: N" is the clockwise angle needed to make the text upright.
        code = {90: cv2.ROTATE_90_CLOCKWISE,
                180: cv2.ROTATE_180,
                270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rot]
        logger.info("OSD: rotating %d° (confidence %.1f) to correct orientation.",
                    rot, conf)
        return cv2.rotate(thresh, code)
    return thresh


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

    def _best_over_attempts(image) -> Tuple[Optional[str], Tuple[int, int, int], int]:
        _best: Optional[str] = None
        _best_score: Tuple[int, int, int] = (-1, -1, -1)
        _tried = 0
        for lang, cfg in attempts:
            try:
                txt = normalize_ocr_text(
                    pytesseract.image_to_string(image, lang=lang, config=cfg))
            except Exception as exc:
                logger.debug("OCR attempt failed (lang=%s cfg=%s): %s", lang, cfg, exc)
                continue
            if not txt:
                continue
            _tried += 1
            score = _ocr_score(txt)
            if score > _best_score:
                _best_score, _best = score, txt
            if score[0] >= 5:      # a readable panel — no need to keep grinding
                break
        return _best, _best_score, _tried

    best, best_score, tried = _best_over_attempts(thresh)

    # Orientation rescue. If the best pass found essentially no structured panel
    # (no S/I/R rows and at most one drug), the most likely culprit on a phone
    # upload is a rotated page — a photo taken upside-down or in landscape. Ask
    # OSD which way is up, rotate once, and retry. Guarded by the weak-result
    # test so it never runs when the first pass already succeeded.
    if best_score[0] == 0 and best_score[1] <= 1:
        rotated = _auto_rotate_by_osd(thresh)
        if rotated is not thresh:
            r_best, r_score, r_tried = _best_over_attempts(rotated)
            tried += r_tried
            if r_score > best_score:
                logger.info("OCR: orientation-corrected pass won (%s > %s).",
                            r_score, best_score)
                best, best_score = r_best, r_score

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
    for alias_norm, abx_name in _alias_sorted():
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
    for alias_norm, abx_name in _alias_sorted():
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
    for alias_norm, abx_name in _alias_sorted():
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
