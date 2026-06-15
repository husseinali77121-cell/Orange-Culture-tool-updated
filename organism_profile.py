# © 2025 Dr. Hussein Ali — Orange Lab, 6 October City, Egypt
# Orange Culture Tool — Data Module
# Unauthorized copying or distribution is prohibited.
"""Organism profile dataset for Orange Culture Tool.

Enhancements in this revision:
- added helper lookup/validation utilities
- added clinically relevant missing profiles (VRE, Rickettsia spp.)
- exported normalization helpers for cross-module consistency checks
"""

import re
from typing import Any, Dict, Iterable, Optional

ORGANISM_PROFILE = {
    "E. coli": {
        "first_line": ["Nitrofurantoin","Fosfomycin",
                       "Trimethoprim/Sulfamethoxazole","Amoxicillin + Clavulanic acid"],
        "second_line": ["Cefuroxime","Cefuroxime sodium","Cefixime",
                        "Norfloxacin","Ciprofloxacin"],
        "third_line":  ["Ertapenem","Meropenem"],
        "avoid": [],
        "urine_note": (
            "Norfloxacin: مخصص للمسالك فقط — لا تركيز علاجي خارج البول.\n"
            "Ertapenem: يُحفظ للـ ESBL-producing E. coli فقط."
        ),
        "specimen_context": {
            "Blood":      "🔬 الأكثر شيوعاً في bacteremia الجهاز البولي والبطن.",
            "Sputum":     "⚠️ E. coli في البلغم — نادر، يشير لـ aspiration أو HAP.",
            "Wound Swab": "🔬 شائع في عدوى الجروح الجراحية والحروق.",
            "Pus":        "🔬 شائع في خراجات البطن.",
            "Stool":      "🔬 ETEC/EPEC — إسهال المسافرين.",
        },
        "note": "🔬 الأكثر شيوعاً في مزارع البول.",
    },
    "Klebsiella spp.": {
        "first_line": ["Amoxicillin + Clavulanic acid","Cefuroxime","Cefixime"],
        "second_line": ["Cefuroxime sodium","Norfloxacin","Ciprofloxacin",
                        "Piperacillin + Tazobactam","Ceftriaxone"],
        "third_line":  ["Ertapenem","Meropenem"],
        "avoid": ["Ampicillin"],
        "urine_note": (
            "Ertapenem: الخيار الأول لـ ESBL-producing Klebsiella (IDSA 2023).\n"
            "Norfloxacin: للمسالك فقط."
        ),
        "specimen_context": {
            "Blood":      "🔬 Klebsiella bacteremia — خطر خصوصاً في الكبد.",
            "Sputum":     "🔬 HAP وعدوى الجهاز التنفسي في المستشفى.",
            "Wound Swab": "🔬 عدوى الجروح الجراحية.",
            "Pus":        "🔬 خراجات الكبد والبطن.",
            "Urine":      "🔬 الثاني الأكثر شيوعاً في مزارع البول.",
        },
        "note": "🔬 تحقق من ESBL — مقاومة طبيعية لبعض البيتا-لاكتام.",
    },
    "Pseudomonas aeruginosa": {
        "first_line": ["Piperacillin + Tazobactam","Ceftazidime","Ciprofloxacin"],
        "second_line": ["Cefepime","Cefoperazone + Sulbactam",
                        "Meropenem","Imipenem/Cilastatin","Amikacin"],
        "third_line":  ["Colistin"],
        "avoid": ["Nitrofurantoin","Fosfomycin","Trimethoprim/Sulfamethoxazole",
                  "Cephalexin","Cefadroxil","Cefaclor","Norfloxacin",
                  "Cefuroxime sodium","Ertapenem"],
        "urine_note": (
            "Ertapenem: ممنوع لـ Pseudomonas — لا نشاط (EUCAST).\n"
            "Ciprofloxacin هو الفلوروكينولون الوحيد الفعال ضد Pseudomonas."
        ),
        "specimen_context": {
            "Blood":      "🔴 Pseudomonas bacteremia — mortality عالية — ICU.",
            "Sputum":     "🔴 VAP/HAP الأكثر خطورة — anti-pseudomonal إلزامي.",
            "Wound Swab": "🔴 شائع في حروق والجروح المزمنة.",
            "Urine":      "🔴 UTI المعقد — كاتيتر أو مضادات سابقة.",
        },
        "note": "🔬 جرثومة انتهازية — تحتاج anti-pseudomonal متخصص.",
    },
    "Acinetobacter baumannii": {
        "first_line": ["Ampicillin/Sulbactam","Cefoperazone + Sulbactam"],
        "second_line": ["Meropenem","Imipenem/Cilastatin","Amikacin",
                        "Trimethoprim/Sulfamethoxazole","Doxycycline"],
        "third_line":  ["Colistin"],
        "avoid": ["Ertapenem","Cephalexin","Cefuroxime","Ceftriaxone",
                  "Azithromycin","Clarithromycin","Nitrofurantoin","Fosfomycin"],
        "specimen_context": {
            "Blood":      "🔴 Acinetobacter bacteremia — ICU — MDR غالباً.",
            "Sputum":     "🔴 VAP الأكثر شيوعاً في ICU — خطر جداً.",
            "Wound Swab": "🔴 عدوى الحروق والجروح الكبيرة.",
        },
        "note": (
            "🔴 MDR — Ampicillin/Sulbactam أو Cefoperazone/Sulbactam "
            "بجرعات عالية هو الأساس (IDSA AMR 2025)."
        ),
    },
    "Staphylococcus aureus": {
        "first_line": ["Cephalexin","Cefadroxil","Amoxicillin + Clavulanic acid"],
        "second_line": ["Cefuroxime sodium","Azithromycin","Doxycycline"],
        "third_line":  [],
        "avoid": [],
        "urine_note": (
            "تحقق من MRSA — إذا MRSA: Vancomycin أو Linezolid فقط.\n"
            "S. aureus في البول → تحقق من Blood culture (hematogenous seeding)."
        ),
        "specimen_context": {
            "Blood":      "🔬 تحقق من MRSA فوراً — خطر endocarditis.",
            "Sputum":     "🔬 pneumonia بعد الإنفلونزا أو في ICU.",
            "Wound Swab": "🔬 الأكثر شيوعاً في عدوى الجروح.",
            "Pus":        "🔬 خراجات الجلد والأنسجة الرخوة.",
            "Urine":      "⚠️ S. aureus في البول — احتمال hematogenous seeding.",
        },
        "note": "🔬 تحقق من MRSA — قد يحتاج Vancomycin.",
    },
    "MRSA": {
        "first_line": ["Vancomycin","Linezolid"],
        "second_line": ["Trimethoprim/Sulfamethoxazole","Doxycycline"],
        "third_line":  [],
        "avoid": ["Cephalexin","Cefadroxil","Cefaclor","Cefuroxime","Cefuroxime sodium",
                  "Ceftriaxone","Amoxicillin + Clavulanic acid","Ampicillin/Sulbactam",
                  "Piperacillin + Tazobactam","Ertapenem"],
        "urine_note": "جميع البيتا-لاكتام لا تعمل على MRSA (mecA gene — PBP2a resistance).",
        "specimen_context": {
            "Blood":      "🔴 MRSA bacteremia — ابدأ Vancomycin فوراً.",
            "Sputum":     "🔴 MRSA pneumonia — خطر في ICU.",
            "Wound Swab": "🔴 MRSA SSTI — شائع في المجتمع (CA-MRSA).",
            "Pus":        "🔴 MRSA abscess — drainage + Vancomycin.",
            "CSF":        "🔴 MRSA meningitis — نادر لكن خطر.",
        },
        "note": "🔴 مقاوم لجميع البيتا-لاكتام — Vancomycin أو Linezolid فقط.",
    },
    "Proteus mirabilis": {
        "first_line": ["Amoxicillin + Clavulanic acid","Cefuroxime","Cefixime"],
        "second_line": ["Cefuroxime sodium","Norfloxacin","Ciprofloxacin",
                        "Trimethoprim/Sulfamethoxazole"],
        "third_line":  ["Ertapenem"],
        "avoid": ["Nitrofurantoin","Tetracyclines","Colistin"],
        "urine_note": (
            "Nitrofurantoin: مقاوم طبيعياً لـ Proteus (intrinsic) — EUCAST.\n"
            "Norfloxacin: فعال في UTI فقط."
        ),
        "specimen_context": {
            "Urine":      "🔬 شائع في UTI — يرفع الـ pH (urease).",
            "Wound Swab": "🔬 عدوى الجروح المزمنة والقدم السكري.",
            "Blood":      "⚠️ Proteus bacteremia — مصدره البولي غالباً.",
        },
        "note": "🔬 مقاوم طبيعياً لـ Nitrofurantoin — لا تستخدمه أبداً.",
    },
    "Enterococcus faecalis": {
        "first_line": ["Amoxicillin + Clavulanic acid","Fosfomycin","Nitrofurantoin"],
        "second_line": ["Ampicillin/Sulbactam","Vancomycin","Linezolid"],
        "third_line":  [],
        "avoid": ["Cephalosporins (كل الجيل)","Trimethoprim/Sulfamethoxazole",
                  "Cefuroxime sodium","Ertapenem","Norfloxacin"],
        "urine_note": (
            "Ertapenem وCefuroxime sodium: لا نشاط ضد Enterococcus (EUCAST).\n"
            "جميع السيفالوسبورين مقاومة طبيعياً لـ Enterococcus."
        ),
        "specimen_context": {
            "Urine":      "🔬 شائع في UTI خصوصاً الكاتيتر.",
            "Blood":      "⚠️ Enterococcus bacteremia — خطر endocarditis.",
            "Wound Swab": "⚠️ عدوى البطن والجروح الجراحية.",
        },
        "note": "🔬 مقاوم طبيعياً للسيفالوسبورين — Amoxicillin هو الأساس.",
    },
    "Salmonella spp.": {
        "first_line": ["Ceftriaxone","Azithromycin","Ciprofloxacin"],
        "second_line": ["Trimethoprim/Sulfamethoxazole","Cefixime"],
        "third_line":  [],
        "avoid": ["Nitrofurantoin","Fosfomycin","Cephalexin","Cefadroxil",
                  "Cefaclor","Cefuroxime","Metronidazole","Doxycycline"],
        "urine_note": "",
        "specimen_context": {
            "Stool": "🔬 Salmonella gastroenteritis — العلاج للحالات الشديدة فقط.",
            "Blood": "🔬 Typhoid fever — Ceftriaxone أو Azithromycin.",
        },
        "note": "🔬 العلاج مخصص للحالات الشديدة أو الحمى التيفودية فقط.",
    },
    "Shigella spp.": {
        "first_line": ["Azithromycin","Ciprofloxacin","Ceftriaxone"],
        "second_line": ["Trimethoprim/Sulfamethoxazole"],
        "third_line":  [],
        "avoid": ["Nitrofurantoin","Fosfomycin","Amoxicillin + Clavulanic acid",
                  "Metronidazole"],
        "urine_note": "",
        "specimen_context": {
            "Stool": "🔬 Shigellosis — العلاج يقلل الأعراض ويمنع الانتشار.",
            "Blood": "🔬 نادراً ما يصل للدم إلا في الحالات الشديدة.",
        },
        "note": "🔬 تعالج الحالات الوخيمة — مقاومة عالية لـ TMP/SMX في مصر.",
    },
    "Campylobacter jejuni": {
        "first_line": ["Azithromycin"],
        "second_line": ["Ciprofloxacin"],
        "third_line":  [],
        "avoid": ["Trimethoprim/Sulfamethoxazole","Nitrofurantoin","Fosfomycin"],
        "urine_note": "",
        "specimen_context": {
            "Stool": "🔬 أشهر أسباب الإسهال البكتيري — غالباً محدود ذاتياً.",
            "Blood": "🔬 Bacteremia نادر في نقص المناعة.",
        },
        "note": "🔬 معظم الحالات لا تحتاج مضادات — Azithromycin عند الحاجة.",
    },
    "Streptococcus pneumoniae": {
        "first_line": ["Amoxicillin + Clavulanic acid","Ceftriaxone","Levofloxacin"],
        "second_line": ["Azithromycin","Clarithromycin","Cefuroxime"],
        "third_line":  ["Vancomycin","Linezolid"],
        "avoid": [],
        "urine_note": "",
        "specimen_context": {
            "Sputum": "🔬 السبب الأول لـ CAP — تحقق من مقاومة Penicillin.",
            "Blood":  "🔬 Pneumococcal bacteremia — خطر في المسنين.",
            "CSF":    "🔬 السبب الأول لـ bacterial meningitis في البالغين.",
        },
        "note": "🔬 السبب الأول لـ CAP والـ meningitis. تحقق من MIC للـ Penicillin.",
    },
    "H. influenzae": {
        "first_line": ["Amoxicillin + Clavulanic acid","Cefuroxime","Ceftriaxone"],
        "second_line": ["Azithromycin","Levofloxacin","Trimethoprim/Sulfamethoxazole"],
        "third_line":  [],
        "avoid": ["Ampicillin (alone)"],
        "urine_note": "",
        "specimen_context": {
            "Sputum": "🔬 شائع في COPD exacerbation و CAP.",
            "Blood":  "⚠️ H. influenzae bacteremia — نادر بعد التطعيم.",
            "CSF":    "⚠️ H. influenzae meningitis — نادر جداً الآن.",
        },
        "note": "🔬 30% ينتجون beta-lactamase — Amoxicillin/Clavulanate مفضل.",
    },
    "Legionella pneumophila": {
        "first_line": ["Levofloxacin","Azithromycin"],
        "second_line": ["Doxycycline","Clarithromycin"],
        "third_line":  [],
        "avoid": ["Beta-lactams (alone)","Aminoglycosides","Cephalosporins (alone)"],
        "urine_note": "",
        "specimen_context": {
            "Sputum": "🔬 Legionella — CAP الشديد، خاصةً في الفنادق أو مكيفات الهواء.",
            "Blood":  "⚠️ Bacteremia نادر — التشخيص بـ Urine Antigen أو PCR.",
        },
        "note": "🔬 Levofloxacin هو الخيار الأول. لا يُعزل بالزراعة العادية — يحتاج وسط BCYE.",
    },
    "Mycoplasma spp.": {
        "first_line": ["Azithromycin","Doxycycline"],
        "second_line": ["Levofloxacin","Clarithromycin"],
        "third_line":  [],
        "avoid": ["Beta-lactams","Cephalosporins","Vancomycin","Aminoglycosides"],
        "urine_note": "",
        "specimen_context": {
            "Sputum": "🔬 Atypical pneumonia — Walking pneumonia — خاصةً في الشباب.",
        },
        "note": "🔬 لا جدار خلوي — كل البيتا-لاكتام غير فعالة. يُشخص بـ PCR أو Serology.",
    },
    "Anaerobes (لاهوائيات)": {
        "first_line": ["Metronidazole","Amoxicillin + Clavulanic acid"],
        "second_line": ["Piperacillin + Tazobactam","Meropenem",
                        "Imipenem/Cilastatin","Ampicillin/Sulbactam"],
        "third_line":  [],
        "avoid": ["Aminoglycosides","Nitrofurantoin"],
        "urine_note": "",
        "specimen_context": {
            "Pus":        "🔬 الخراجات داخل البطن — Metronidazole ضروري.",
            "Wound Swab": "🔬 العدوى الجراحية بعد عمليات الأمعاء.",
            "Blood":      "🔬 Bacteremia اللاهوائيات — مصدره البطن غالباً.",
        },
        "note": "🔬 Metronidazole هو الخيار الأول لكل اللاهوائيات.",
    },
    "Stenotrophomonas maltophilia": {
        "first_line": ["Trimethoprim/Sulfamethoxazole"],
        "second_line": ["Levofloxacin","Doxycycline"],
        "third_line":  [],
        "avoid": ["Carbapenems","Ertapenem","Meropenem","Imipenem/Cilastatin",
                  "Aminoglycosides","Ceftriaxone","Cefepime"],
        "urine_note": "",
        "specimen_context": {
            "Sputum": "🔴 شائع في VAP/HAP في ICU — خاصةً بعد علاج طويل بالكاربابينيم.",
            "Blood":  "🔴 Stenotrophomonas bacteremia — نادر لكن خطر في المناعة الضعيفة.",
        },
        "note": "🔴 مقاومة طبيعية للكاربابينيم! TMP/SMX هو الخيار الأول. ينتقى بعد Meropenem.",
    },
}
# Additional clinically relevant profiles referenced by the antibiotic module.
ORGANISM_PROFILE.update({
    "VRE": {
        "first_line": ["Linezolid", "Vancomycin"],
        "second_line": [],
        "third_line": [],
        "avoid": [
            "Cephalosporins (كل الجيل)",
            "Carbapenems",
            "Ertapenem",
            "Amoxicillin + Clavulanic acid",
            "Ampicillin/Sulbactam",
        ],
        "urine_note": "Vancomycin-resistant Enterococcus يحتاج مراجعة الحساسية المحلية؛ Linezolid خيار مهم في العدوى الجهازية.",
        "specimen_context": {
            "Blood": "🔴 VRE bacteremia — يحتاج علاج موجّه ومتابعة متخصصة.",
            "Urine": "⚠️ VRE قد يظهر في UTI المعقد أو المرضى المنومين لفترات طويلة.",
            "Wound Swab": "⚠️ قد يظهر في الجروح المزمنة والمستشفيات.",
        },
        "note": "🔴 VRE يعني مقاومة للفانكومايسين؛ يجب الاعتماد على علاج موجّه ونتيجة الحساسية.",
    },
    "Rickettsia spp.": {
        "first_line": ["Doxycycline"],
        "second_line": [],
        "third_line": [],
        "avoid": ["Beta-lactams", "Cephalosporins (كل الجيل)", "Aminoglycosides"],
        "urine_note": "ليس مسببًا شائعًا في مزارع البول أو المزارع الروتينية.",
        "specimen_context": {
            "Blood": "⚠️ لا تُشخّص عادةً بالمزرعة الروتينية؛ التشخيص غالباً سريري/سيرولوجي/PCR.",
        },
        "note": "⚠️ Rickettsia ليست جرثومة مزرعية روتينية في هذا السياق، لكن أضيفت للحفاظ على اتساق البيانات العلاجية.",
    },
})

# Guarantee a complete schema across all organism records.
for _payload in ORGANISM_PROFILE.values():
    _payload.setdefault("first_line", [])
    _payload.setdefault("second_line", [])
    _payload.setdefault("third_line", [])
    _payload.setdefault("avoid", [])
    _payload.setdefault("urine_note", "")
    _payload.setdefault("specimen_context", {})
    _payload.setdefault("note", "")

GENERIC_DRUG_CLASS_TERMS = {
    "cephalosporins (كل الجيل)",
    "cephalosporins",
    "beta-lactams",
    "beta-lactams (alone)",
    "aminoglycosides",
    "carbapenems",
    "tetracyclines",
}


def normalize_organism_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def get_organism_profile(name: str) -> Optional[Dict[str, Any]]:
    direct = ORGANISM_PROFILE.get(name)
    if direct:
        return direct
    normalized = normalize_organism_key(name)
    for organism_name, payload in ORGANISM_PROFILE.items():
        if normalize_organism_key(organism_name) == normalized:
            return payload
    return None


def validate_organism_profile(known_antibiotics: Optional[Iterable[str]] = None) -> list[str]:
    issues: list[str] = []
    known_abx = set(known_antibiotics or [])

    for organism_name, payload in ORGANISM_PROFILE.items():
        required = {"first_line", "second_line", "third_line", "avoid", "urine_note", "specimen_context", "note"}
        missing = sorted(required - set(payload.keys()))
        if missing:
            issues.append(f"{organism_name}: missing keys -> {', '.join(missing)}")

        if known_abx:
            for bucket_name in ("first_line", "second_line", "third_line"):
                for abx_name in payload.get(bucket_name, []):
                    if abx_name not in known_abx:
                        issues.append(f"{organism_name}: {bucket_name} antibiotic missing in ABX_GUIDELINES -> {abx_name}")
            for avoid_name in payload.get("avoid", []):
                low = avoid_name.lower().strip()
                if avoid_name not in known_abx and low not in GENERIC_DRUG_CLASS_TERMS:
                    issues.append(f"{organism_name}: avoid item not found in ABX_GUIDELINES -> {avoid_name}")

    return issues


__all__ = [
    "GENERIC_DRUG_CLASS_TERMS",
    "ORGANISM_PROFILE",
    "get_organism_profile",
    "normalize_organism_key",
    "validate_organism_profile",
]
