# Auto-extracted: constants & reference data — Orange Lab Microbiology CDSS
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

logger = logging.getLogger("orange_lab.data")


SIR_LABELS      = {"S": "Sensitive", "I": "Intermediate", "R": "Resistant"}

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
        except Exception as _exc:
            logger.debug("suppressed exception: %s", _exc)
            continue
    return result

COMMERCIAL_NAMES: Dict[str, str] = load_commercial_names()

def get_commercial_name(generic: str) -> str:
    return COMMERCIAL_NAMES.get(generic.lower(), "")

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
    "Monobactams":                  ["Aztreonam"],       # Pseudomonas MDR panel (Magiorakos)
}

MDR_CATEGORIES_GRAM_NEG = frozenset([
    "Aminoglycosides", "Antipseudomonal Penics", "Extended-Sp Cephalosporins",
    "Carbapenems", "Fluoroquinolones", "Folate PI", "Penicillins+BLI",
    "Polymyxins", "Cephalosporins-4th", "Cephalosporins-3rd-AP",
    "Nitrofurans", "Fosfomycins", "Tetracyclines",
])

# ─────────────────────────────────────────────────────────────────────────────
# Organism-specific MDR category panels — Magiorakos et al. 2012 defines SEPARATE
# antimicrobial-category tables for Enterobacteriaceae, P. aeruginosa and
# Acinetobacter. Using one shared gram-negative panel over-/under-counts
# categories for each. These panels select the categories that actually appear
# in the Magiorakos table for each group (limited to agents in this formulary).
# ─────────────────────────────────────────────────────────────────────────────

# Enterobacterales (Magiorakos Enterobacteriaceae table). Note: NO separate
# "antipseudomonal cephalosporin" class (that concept is Pseudomonas-specific),
# and Nitrofurantoin is NOT an MDR category agent (urinary-only). Cefepime is
# folded into the extended-spectrum cephalosporin category, not a class of its
# own, to avoid inflating the category count.
MDR_CATEGORIES_ENTEROBACTERALES = frozenset([
    "Aminoglycosides",
    "Antipseudomonal Penics",          # Piperacillin-tazobactam
    "Extended-Sp Cephalosporins",      # 3rd/4th-gen extended-spectrum (incl. Cefepime, Ceftazidime)
    "Carbapenems",
    "Fluoroquinolones",
    "Folate PI",                       # TMP-SMX
    "Penicillins+BLI",                 # Amox-clav / Ampicillin-sulbactam
    "Polymyxins",
    "Fosfomycins",
    "Tetracyclines",
])

# Pseudomonas aeruginosa (Magiorakos: 8 categories — all antipseudomonal). NO
# Ceftriaxone/Cefotaxime (not antipseudomonal), NO Ertapenem/folate/tetracyclines
# (intrinsically resistant). Monobactams (Aztreonam) included per Magiorakos.
MDR_CATEGORIES_PSEUDOMONAS = frozenset([
    "Aminoglycosides",
    "Carbapenems",                     # antipseudomonal: imipenem/meropenem (not ertapenem — intrinsic R, stripped)
    "Cephalosporins-3rd-AP",           # antipseudomonal cephalosporins: ceftazidime
    "Cephalosporins-4th",              # cefepime
    "Fluoroquinolones",                # antipseudomonal: cipro/levo
    "Antipseudomonal Penics",          # piperacillin-tazobactam
    "Polymyxins",
    "Fosfomycins",                     # phosphonic acids
    "Monobactams",                     # aztreonam
])

# Acinetobacter spp. (Magiorakos: 9 categories). Ampicillin-sulbactam is a KEY
# agent here (sulbactam has intrinsic activity). Includes extended-spectrum
# cephalosporins, folate, tetracyclines, polymyxins.
MDR_CATEGORIES_ACINETOBACTER = frozenset([
    "Aminoglycosides",
    "Carbapenems",                     # antipseudomonal: imipenem/meropenem
    "Extended-Sp Cephalosporins",      # ceftriaxone/cefotaxime/ceftazidime
    "Cephalosporins-3rd-AP",
    "Fluoroquinolones",
    "Folate PI",                       # TMP-SMX
    "Penicillins+BLI",                 # ampicillin-sulbactam (key)
    "Antipseudomonal Penics",          # piperacillin-tazobactam
    "Polymyxins",
    "Tetracyclines",                   # doxycycline/minocycline
])

# Organism → specific panel mapping (canonical substrings, lower-case).
_ENTEROBACTERALES_KEYS = (
    "escherichia", "e. coli", "e.coli", "klebsiella", "enterobacter",
    "citrobacter", "serratia", "proteus", "providencia", "morganella",
    "salmonella", "shigella", "hafnia", "raoultella", "pantoea", "yersinia",
)


def get_mdr_panel(organism: str, is_gram_pos: bool):
    """Return the Magiorakos antimicrobial-category panel for this organism.

    Gram-positives use the gram-positive panel. Gram-negatives are split into
    Enterobacterales / Pseudomonas / Acinetobacter, each with its own Magiorakos
    table; anything else falls back to the generic gram-negative panel.
    """
    if is_gram_pos:
        return MDR_CATEGORIES_GRAM_POS
    o = (organism or "").lower().strip()
    if "pseudomonas" in o:
        return MDR_CATEGORIES_PSEUDOMONAS
    if "acinetobacter" in o:
        return MDR_CATEGORIES_ACINETOBACTER
    if any(k in o for k in _ENTEROBACTERALES_KEYS):
        return MDR_CATEGORIES_ENTEROBACTERALES
    return MDR_CATEGORIES_GRAM_NEG

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

# ============================================================================
#  INTRINSIC_RESISTANCE — CANONICAL SINGLE SOURCE OF TRUTH
#  EUCAST Intrinsic Resistance & Unusual Phenotypes Tables v3.3
#  Keys are substring-matched (org_key in org_l OR org_l in org_key), so both
#  binomial and abbreviated organism forms are covered. Drug strings include
#  common formulary VARIANTS (e.g. "Cefuroxime" AND "Cefuroxime sodium") so
#  exact-string matching in _remove_intrinsic_resistance / is_intrinsically_
#  avoided never silently misses. Extra variants that match no real drug are
#  harmless. ONLY intrinsically-INACTIVE agents are listed — anti-pseudomonal
#  β-lactams (Ceftazidime/Cefepime/Cefoperazone/Pip-Tazo/Aztreonam/carbapenems)
#  are deliberately EXCLUDED and judged on their own AST result.
# ============================================================================
INTRINSIC_RESISTANCE = {
    # ── Enterobacterales — wild-type susceptible ────────────────────────────
    "escherichia coli": [],
    "e. coli":          [],

    # Klebsiella: chromosomal penicillinase (SHV/LEN/OKP) → aminopenicillins.
    # Amox-clav / cephalosporins remain active (NOT intrinsic).
    "klebsiella pneumoniae": ["Ampicillin", "Amoxicillin", "Ticarcillin"],
    "klebsiella oxytoca":    ["Ampicillin", "Amoxicillin", "Ticarcillin"],
    "klebsiella spp.":       ["Ampicillin", "Amoxicillin", "Ticarcillin"],

    # Proteus/Providencia/Morganella tribe → tetracyclines, nitrofurantoin,
    # polymyxins are ALL intrinsically inactive.
    "proteus mirabilis": ["Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
                          "Nitrofurantoin", "Colistin", "Polymyxin B"],
    "proteus spp.":      ["Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
                          "Nitrofurantoin", "Colistin", "Polymyxin B"],
    # P. vulgaris/penneri add inducible β-lactamase → aminopenicillins + 1st/2nd ceph
    "proteus vulgaris":  ["Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
                          "Nitrofurantoin", "Colistin", "Polymyxin B",
                          "Ampicillin", "Amoxicillin",
                          "Cephalexin", "Cefadroxil", "Cefazolin",
                          "Cefuroxime", "Cefuroxime sodium"],

    # Morganella: chromosomal AmpC + tribe intrinsics
    "morganella morganii": ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                            "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                            "Cephalexin", "Cefadroxil", "Cefazolin",
                            "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin",
                            "Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
                            "Nitrofurantoin", "Colistin", "Polymyxin B"],

    # Providencia: AmpC + tribe + intrinsic aminoglycoside (gentamicin/tobramycin)
    "providencia spp.": ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                         "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                         "Cephalexin", "Cefadroxil", "Cefazolin",
                         "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin",
                         "Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
                         "Nitrofurantoin", "Colistin", "Polymyxin B",
                         "Gentamicin", "Tobramycin"],

    # Serratia: chromosomal AmpC + intrinsic polymyxin/nitrofurantoin
    "serratia marcescens": ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                            "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                            "Cephalexin", "Cefadroxil", "Cefazolin",
                            "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin",
                            "Colistin", "Polymyxin B", "Nitrofurantoin", "Tigecycline"],
    "serratia spp.":       ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                            "Cephalexin", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
                            "Cefoxitin", "Colistin", "Polymyxin B", "Nitrofurantoin"],

    # Enterobacter / Hafnia: chromosomal inducible AmpC
    "enterobacter cloacae":  ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                             "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                             "Cephalexin", "Cefadroxil", "Cefazolin",
                             "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin"],
    "enterobacter aerogenes":["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                             "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                             "Cephalexin", "Cefadroxil", "Cefazolin",
                             "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin"],
    "enterobacter spp.":     ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                             "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                             "Cephalexin", "Cefadroxil", "Cefazolin",
                             "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin"],
    "hafnia alvei":          ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                             "Cephalexin", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
                             "Cefoxitin"],

    # Citrobacter freundii = AmpC; C. koseri = penicillinase only
    "citrobacter freundii":  ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
                             "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
                             "Cephalexin", "Cefadroxil", "Cefazolin",
                             "Cefuroxime", "Cefuroxime sodium", "Cefaclor", "Cefoxitin"],
    "citrobacter koseri":    ["Ampicillin", "Amoxicillin", "Ticarcillin"],
    "citrobacter spp.":      ["Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid"],

    # Salmonella / Shigella: 1st/2nd-gen cephalosporins & aminoglycosides may
    # test S in vitro but are CLINICALLY INEFFECTIVE for invasive infection
    # (EUCAST/CLSI "do not report S"). Routed to Avoid here.
    "salmonella": ["Cephalexin", "Cefadroxil", "Cefazolin", "Cefaclor",
                   "Cefuroxime", "Cefuroxime sodium",
                   "Gentamicin", "Amikacin", "Tobramycin", "Nitrofurantoin"],
    "shigella":   ["Cephalexin", "Cefadroxil", "Cefazolin", "Cefaclor",
                   "Cefuroxime", "Cefuroxime sodium",
                   "Gentamicin", "Amikacin", "Tobramycin", "Nitrofurantoin"],

    # ── Non-fermenters ──────────────────────────────────────────────────────
    # Pseudomonas aeruginosa — ONLY Ceftazidime/Cefepime/Cefoperazone/Pip-Tazo/
    # Aztreonam/anti-pseudomonal carbapenems/FQs/aminoglycosides/colistin work.
    "pseudomonas aeruginosa": [
        "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefaclor",
        "Cefuroxime", "Cefuroxime sodium", "Cefuroxime axetil", "Cefoxitin",
        "Cefotaxime", "Ceftriaxone", "Cefixime", "Cefpodoxime", "Ceftibuten",
        "Ertapenem",
        "Tetracycline", "Doxycycline", "Minocycline", "Tigecycline",
        "Chloramphenicol", "Trimethoprim", "Trimethoprim/Sulfamethoxazole",
        "Nitrofurantoin",
        "Azithromycin", "Erythromycin", "Clarithromycin",
    ],

    # Acinetobacter baumannii — NOTE: Ampicillin/Sulbactam is ACTIVE (excluded);
    # tetracyclines (doxy/minocycline) can be active (excluded).
    "acinetobacter baumannii": [
        "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefaclor",
        "Cefuroxime", "Cefuroxime sodium", "Cefoxitin",
        "Cefotaxime", "Ceftriaxone", "Ertapenem", "Aztreonam",
        "Trimethoprim", "Fosfomycin", "Nitrofurantoin", "Chloramphenicol",
    ],

    # Stenotrophomonas maltophilia — L1 MBL (all carbapenems) + aminoglycosides.
    # Active (excluded): TMP-SMX, Levofloxacin, Minocycline, Tigecycline.
    "stenotrophomonas maltophilia": [
        "Imipenem/Cilastatin", "Meropenem", "Ertapenem",
        "Gentamicin", "Amikacin", "Tobramycin",
        "Ampicillin", "Amoxicillin", "Amoxicillin + Clavulanic acid",
        "Ampicillin/Sulbactam", "Ampicillin + Sulbactam",
        "Piperacillin", "Piperacillin + Tazobactam",
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefotaxime", "Ceftriaxone", "Ceftazidime", "Cefepime",
        "Cefoperazone", "Aztreonam",
        "Ciprofloxacin", "Norfloxacin", "Ofloxacin",
        "Fosfomycin", "Nitrofurantoin",
    ],

    # ── Gram-positives ──────────────────────────────────────────────────────
    # Enterococcus — ALL cephalosporins + low-level aminoglycoside (mono) +
    # clindamycin + TMP-SMX (in-vivo ineffective) + aztreonam. E. faecalis is
    # ampicillin-SUSCEPTIBLE (ampicillin deliberately excluded).
    "enterococcus faecalis": [
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefixime", "Ceftriaxone", "Cefotaxime", "Ceftazidime",
        "Cefepime", "Cefoperazone", "Cefoperazone + Sulbactam", "Cefoxitin",
        "Gentamicin", "Amikacin", "Tobramycin",
        "Clindamycin", "Trimethoprim/Sulfamethoxazole", "Aztreonam",
    ],
    "enterococcus faecium": [
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefixime", "Ceftriaxone", "Cefotaxime", "Ceftazidime",
        "Cefepime", "Cefoperazone", "Cefoperazone + Sulbactam", "Cefoxitin",
        "Gentamicin", "Amikacin", "Tobramycin",
        "Clindamycin", "Trimethoprim/Sulfamethoxazole", "Aztreonam",
    ],
    "enterococcus spp.": [
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefixime", "Ceftriaxone", "Cefotaxime", "Ceftazidime",
        "Cefepime", "Cefoperazone", "Cefoperazone + Sulbactam", "Cefoxitin",
        "Gentamicin", "Amikacin", "Tobramycin",
        "Clindamycin", "Trimethoprim/Sulfamethoxazole", "Aztreonam",
    ],
    "vre": [
        "Cephalexin", "Cefadroxil", "Cefazolin", "Cefuroxime", "Cefuroxime sodium",
        "Cefaclor", "Cefixime", "Ceftriaxone", "Cefotaxime", "Ceftazidime",
        "Cefepime", "Cefoperazone", "Cefoperazone + Sulbactam", "Cefoxitin",
        "Gentamicin", "Amikacin", "Tobramycin",
        "Clindamycin", "Trimethoprim/Sulfamethoxazole", "Aztreonam",
        "Vancomycin",
    ],

    # Staphylococcus — Aztreonam + polymyxins intrinsic. (MRSA β-lactam failure
    # is handled by the mecA/Oxacillin-Cefoxitin logic, NOT this table.)
    "staphylococcus aureus": ["Aztreonam", "Colistin", "Polymyxin B"],
    "staphylococcus":        ["Aztreonam", "Colistin", "Polymyxin B"],

    # Streptococcus — low-level aminoglycoside (mono, synergy-only) + aztreonam
    # + polymyxins + fusidic acid.
    "streptococcus pneumoniae": ["Gentamicin", "Amikacin", "Tobramycin",
                                 "Aztreonam", "Colistin", "Polymyxin B", "Fusidic acid"],
    "streptococcus pyogenes":   ["Gentamicin", "Amikacin", "Tobramycin",
                                 "Aztreonam", "Colistin", "Polymyxin B", "Fusidic acid"],
    "streptococcus agalactiae": ["Gentamicin", "Amikacin", "Tobramycin",
                                 "Aztreonam", "Colistin", "Polymyxin B", "Fusidic acid"],

    # Listeria monocytogenes — ALL cephalosporins intrinsically inactive.
    "listeria monocytogenes": ["Cephalexin", "Cefadroxil", "Cefazolin",
                               "Cefuroxime", "Cefuroxime sodium", "Cefaclor",
                               "Cefotaxime", "Ceftriaxone", "Ceftazidime", "Cefepime",
                               "Cefoperazone", "Cefoxitin", "Aztreonam", "Fosfomycin"],
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

# ── Mechanism producer sets — CANONICAL (kept identical across modules) ──────
# Enterobacterales capable of ESBL production. "enterobacterales" (generic,
# unspeciated) is included so an ID without genus is still treated as ESBL-capable.
ESBL_PRODUCERS = frozenset([
    "escherichia coli", "e. coli", "e.coli",
    "klebsiella pneumoniae", "klebsiella spp.", "klebsiella oxytoca",
    "proteus mirabilis", "proteus spp.",
    "enterobacter cloacae", "enterobacter spp.", "enterobacter aerogenes",
    "citrobacter freundii", "citrobacter koseri", "citrobacter spp.",
    "serratia marcescens", "serratia spp.",
    "morganella morganii", "providencia spp.",
    "enterobacterales", "hafnia alvei",
])

def is_esbl_producer(organism: str) -> bool:
    """True only for organisms KNOWN to produce ESBL (Enterobacterales).
    Single gate that keeps the ESBL prediction/alert off non-Enterobacterales
    (P. aeruginosa, Acinetobacter, Stenotrophomonas, Gram-positives)."""
    org_l = (organism or "").lower().strip()
    return any(p in org_l or org_l in p for p in ESBL_PRODUCERS)

# Chromosomal inducible AmpC ("SPICE/SPACE") + P. aeruginosa + Hafnia.
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

TREATMENT_DURATION_DB: Dict[str, Any] = {
    "UTI_uncomplicated_female": {
        "label": "Uncomplicated UTI (Female)",
        "days": (3, 7), "standard": 5, "iv_days": 0, "po_days": 5,
        # Empiric drug menu removed: on a culture report it duplicates and can
        # contradict the AST-directed ranked list (e.g. quoting an agent that is
        # Resistant or was never tested). Duration is what matters here.
        "notes": "",
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

HIGH_BIOAVAILABILITY: Dict[str, int] = {
    # Keys match abx_guidelines.py drug names exactly for cross-module consistency
    "Ciprofloxacin": 95, "Levofloxacin": 99, "Moxifloxacin": 90,
    "Ofloxacin": 95, "Norfloxacin": 30,
    "Metronidazole": 99, "Linezolid": 100,
    "Trimethoprim/Sulfamethoxazole": 90, "Doxycycline": 93,
    "Minocycline": 95, "Clindamycin": 87, "Fluconazole": 90,  # Clinda/Mino: MDR/REF only
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
            ])
        ),
        # يحدد اسم الدواء (أو الأدوية) المسبب فعلياً للتناقض — حتى لا يظن المستخدم
        # أن الدواء المقاوم (مثل Cefuroxime sodium=R) هو المقصود بالرسالة
        "trigger_fn": lambda s: [
            d for d in ["Cefuroxime","Cefuroxime sodium","Cephalexin","Cefaclor",
                        "Cefadroxil","Cefixime","Cefoperazone","Cefoperazone + Sulbactam"]
            if s.get(d) == "S"
        ],
        # يحدد الـ 3rd-gen المقاوم فعلياً (Ceftriaxone و/أو Cefotaxime) بدلاً من
        # افتراض Ceftriaxone دائماً — قد يكون Cefotaxime هو المُختبَر وحده.
        "trigger_r_fn": lambda s: [
            d for d in ["Ceftriaxone","Cefotaxime"] if s.get(d) == "R"
        ],
        "severity": "warning",
        "message": "{r_drug}-R مع {drugs}-S — Inoculum Effect محتمل في ESBL.",
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

RANKING_WEIGHTS = {
    "aware_score":     {"Access": 3, "Watch": 2, "Reserve": 1, None: 0},
    "route_score":     {"oral": 2, "iv": 1},
    "specimen_match":  2,   # bonus لو الدواء له specimen_note للعينة دي
    "priority_bonus":  lambda p: max(0, 6 - p),  # priority 1 → +5, priority 5 → +1
}

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
