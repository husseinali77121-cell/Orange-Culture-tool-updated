# ============================
# FILE: abx_guidelines-5.py
# ============================
# © 2025 Dr. Hussein Ali — Orange Lab, 6 October City, Egypt
# Orange Culture Tool — Data Module
# Unauthorized copying or distribution is prohibited.
"""Clinical antibiotic guideline dataset for Orange Culture Tool.

Enhancements in this revision:
- Added Cefazolin, Cefoxitin, Tobramycin, Gatifloxacin, Moxifloxacin
- Updated specimen_notes for urine and pus cultures
- Full schema validation and alias index
"""

import re
from typing import Any, Dict, Iterable, Optional

ABX_GUIDELINES = {
    # ── Beta-lactam / Penicillins ──────────────────────────────────────
    "Amoxicillin + Clavulanic acid": {
        "priority": 1, "class": "Beta-lactamase Inhibitor Combination",
        "note": "✅ خيار قياسي للعدوى البسيطة والمتوسطة (مثل Augmentin/Curam). Bioavailability فموي ~90%.",
        "renal_limit": 30, "renal_note": "CrCl 10-30: 500/125mg q12h (تجنّب 875mg). CrCl <10: 500/125mg q24h. BNF 2025.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["augmentin","curam","amoxiclav","co-amoxiclav"],
        "organisms": ["E. coli","Klebsiella spp.","Staphylococcus aureus",
                      "Proteus mirabilis","Streptococcus pneumoniae","H. influenzae"],
        "specimen_notes": {
            "Blood":      "✅ فعال في bacteremia الموجبات والسالبات البسيطة.",
            "Sputum":     "✅ خيار أول لـ CAP وexacerbation COPD.",
            "Wound Swab": "✅ فعال للعدوى الجلدية المختلطة.",
            "Pus":        "✅ جيد للخراجات والعدوى المختلطة.",
            "Urine":      "✅ خيار أول للمسالك غير المعقدة.",
        },
    },
    "Ampicillin/Sulbactam": {
        "priority": 2, "class": "Penicillin + Beta-lactamase Inhibitor (IV)",
        "note": "💉 IV فقط. فعال للموجبات والسالبات. أساس علاج Acinetobacter بجرعات عالية (IDSA AMR 2025).",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["unictam","sigmaclav","unasyn"],
        "organisms": ["E. coli","Klebsiella spp.","Staphylococcus aureus",
                      "Proteus mirabilis","Enterococcus faecalis","Acinetobacter baumannii"],
        "specimen_notes": {
            "Blood":      "💉 فعال في bacteremia المختلطة.",
            "Sputum":     "💉 HAP/VAP خصوصاً Acinetobacter بجرعات عالية.",
            "Wound Swab": "💉 العدوى الجراحية والمختلطة.",
            "Pus":        "💉 الخراجات داخل البطن.",
        },
    },
    "Piperacillin + Tazobactam": {
        "priority": 4, "class": "Anti-pseudomonal Penicillin + Inhibitor (IV)",
        "note": "🛑 (مثل Tazocin) IV فقط. واسع الطيف جداً — يُحفظ للحالات الشديدة (IDSA AMR 2025).",
        "renal_limit": 20, "renal_note": "CrCl 20-40: 3.375g q6h. CrCl <20: 2.25g q6h. HD: 2.25g q8h + dose بعد dialysis. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["tazocin","pip-tazo","piptaz"],
        "organisms": ["Pseudomonas aeruginosa","E. coli","Klebsiella spp.",
                      "Enterococcus faecalis","Proteus mirabilis","Acinetobacter baumannii"],
        "specimen_notes": {
            "Blood":      "🛑 sepsis شديد مع اشتباه Pseudomonas.",
            "Sputum":     "🛑 VAP/HAP مع اشتباه Pseudomonas.",
            "Wound Swab": "🛑 العدوى الجراحية الشديدة.",
            "Pus":        "🛑 الخراجات داخل البطن الشديدة.",
        },
    },
    # ── Cephalosporins ─────────────────────────────────────────────────
    "Cephalexin": {
        "priority": 1, "class": "1st Gen Cephalosporin (Oral)",
        "note": "✅ (مثل Ceporex) Oral. Bioavailability ~90%. آمن للالتهابات البسيطة والجلد.",
        "renal_limit": 30, "renal_note": "CrCl 10-30: q8-12h | CrCl <10: q12-24h. BNF 2025.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["ceporex","keflex"],
        "organisms": ["Staphylococcus aureus","Streptococcus pneumoniae","E. coli","Proteus mirabilis"],
        "specimen_notes": {
            "Wound Swab": "✅ خيار ممتاز للعدوى الجلدية البسيطة (cellulitis/impetigo).",
            "Urine":      "✅ مناسب للمسالك البسيطة.",
        },
    },
    "Cefadroxil": {
        "priority": 1, "class": "1st Gen Cephalosporin (Oral)",
        "note": "✅ (مثل Duricef) Oral. Bioavailability ~90%. فعال لالتهابات الحلق والجلد.",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["duricef"],
        "organisms": ["Staphylococcus aureus","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Wound Swab": "✅ جيد للعدوى الجلدية والأنسجة الرخوة.",
            "Sputum":     "✅ التهاب الحلق البكتيري (Strep pharyngitis).",
        },
    },
    "Cefaclor": {
        "priority": 2, "class": "2nd Gen Cephalosporin (Oral)",
        "note": "✅ (مثل Ceclor) Oral. Bioavailability ~95%. فعال للأذن الوسطى والمسالك.",
        "renal_limit": 10, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Watch", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["ceclor"],
        "organisms": ["E. coli","H. influenzae","Staphylococcus aureus",
                      "Streptococcus pneumoniae","Klebsiella spp."],
        "specimen_notes": {
            "Sputum": "✅ التهابات الجهاز التنفسي العلوي والأذن الوسطى.",
            "Urine":  "✅ مناسب للمسالك البولية البسيطة.",
        },
    },
    "Cefuroxime": {
        "priority": 2, "class": "2nd Gen Cephalosporin (Oral)",
        "note": "✅ (مثل Zinnat) Oral. Bioavailability ~52%. واسع المدى للجهاز التنفسي والمسالك.",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Watch", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["zinnat","ceftin"],
        "organisms": ["E. coli","Klebsiella spp.","H. influenzae",
                      "Staphylococcus aureus","Streptococcus pneumoniae","Proteus mirabilis"],
        "specimen_notes": {
            "Sputum":     "✅ CAP وعدوى الجهاز التنفسي.",
            "Wound Swab": "✅ عدوى الأنسجة الرخوة المتوسطة.",
            "Urine":      "✅ مناسب للمسالك.",
            "Blood":      "⚠️ لا يُفضل في bacteremia الشديدة — استبدل بـ Zinacef IV.",
        },
    },
    "Cefuroxime sodium": {
        "priority": 2, "class": "2nd Gen Cephalosporin (IV)",
        "note": "💉 (مثل Zinacef) IV فقط — نفس Cefuroxime لكن للحالات التي تحتاج حقن.",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["zinacef","cefuroxime iv","cefuroxime sodium"],
        "organisms": ["E. coli","Klebsiella spp.","H. influenzae",
                      "Staphylococcus aureus","Streptococcus pneumoniae","Proteus mirabilis"],
        "specimen_notes": {
            "Blood":      "💉 bacteremia المتوسطة الشدة.",
            "Sputum":     "💉 CAP الذي يحتاج دخول مستشفى.",
            "Wound Swab": "💉 العدوى الجراحية المتوسطة.",
            "Urine":      "💉 pyelonephritis يحتاج IV.",
        },
    },
    "Ceftriaxone": {
        "priority": 3, "class": "3rd Gen Cephalosporin (IV/IM)",
        "note": "⚠️ (مثل Rocephin) IV/IM فقط — bioavailability فموي = صفر. لا يُستخدم في الحالات البسيطة.",
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً — يُطرح كبدياً أساساً.",
        "hepatic_caution": True, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["rocephin","cefaxone","triaxone"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis","Staphylococcus aureus",
                      "Streptococcus pneumoniae","H. influenzae",
                      "Salmonella spp.","Shigella spp."],
        "specimen_notes": {
            "Blood":      "💉 خيار ممتاز في bacteremia والـ sepsis.",
            "CSF":        "💉 خيار أول في meningitis البكتيري.",
            "Sputum":     "💉 CAP الشديد الذي يحتاج دخول مستشفى.",
            "Urine":      "⚠️ يُحفظ للـ pyelonephritis الشديد فقط.",
            "Stool":      "💉 Typhoid fever والحالات الشديدة من Salmonella/Shigella.",
        },
    },
    "Cefixime": {
        "priority": 2, "class": "3rd Gen Cephalosporin (Oral)",
        "note": "✅ (مثل Suprax) Oral. Bioavailability ~40-50%. خيار فموي قوي للمسالك.",
        "renal_limit": 20, "renal_note": "⚖️ خفض الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Watch", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["suprax","oroken"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis",
                      "H. influenzae","Streptococcus pneumoniae","Salmonella spp."],
        "specimen_notes": {
            "Urine":  "✅ خيار فموي قوي للمسالك والـ pyelonephritis الخفيف.",
            "Sputum": "✅ عدوى الجهاز التنفسي الخفيفة.",
            "Stool":  "✅ Step-down بعد Ceftriaxone في Salmonella.",
        },
    },
    "Cefotaxime": {
        "priority": 3, "class": "3rd Gen Cephalosporin (IV)",
        "note": "💉 (مثل Cefotax) IV فقط — bioavailability فموي = صفر. يستخدم في العدوى الشديدة.",
        "renal_limit": 20, "renal_note": "CrCl 20-40: 3.375g q6h. CrCl <20: 2.25g q6h. HD: 2.25g q8h + dose بعد dialysis. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["cefotax","claforan"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis",
                      "Streptococcus pneumoniae","H. influenzae"],
        "specimen_notes": {
            "Blood":  "💉 bacteremia والـ sepsis.",
            "CSF":    "💉 meningitis — بديل Ceftriaxone.",
            "Sputum": "💉 CAP الشديد.",
        },
    },
    "Ceftazidime": {
        "priority": 4, "class": "3rd Gen Cephalosporin Anti-pseudomonal (IV)",
        "note": "🛑 (مثل Fortum) IV فقط — متخصص في Pseudomonas. Bioavailability فموي = صفر.",
        "renal_limit": 50, "renal_note": "CrCl 31-50: 1g q12h. CrCl 16-30: 1g q24h. CrCl 6-15: 500mg q24h. CrCl <5: 500mg q48h. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["fortum","ceptaz"],
        "organisms": ["Pseudomonas aeruginosa","E. coli","Klebsiella spp.","Proteus mirabilis"],
        "specimen_notes": {
            "Blood":  "🛑 Pseudomonas bacteremia.",
            "Sputum": "🛑 VAP/HAP مع Pseudomonas.",
            "Urine":  "🛑 UTI معقد مع Pseudomonas.",
        },
    },
    "Cefoperazone": {
        "priority": 4, "class": "3rd Gen Cephalosporin (IV)",
        "note": "💉 (مثل Cefobid) IV فقط — يُطرح صفراوياً. آمن في القصور الكلوي.",
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً — يُطرح عبر الصفراء بالكامل.",
        "hepatic_caution": True, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True,
        "interacts_with": ["Warfarin (مضادات التخثر)"],
        "aliases": ["cefobid"],
        "organisms": ["Pseudomonas aeruginosa","E. coli","Klebsiella spp.",
                      "Proteus mirabilis","Staphylococcus aureus"],
        "specimen_notes": {
            "Blood": "💉 bacteremia في مرضى القصور الكلوي (يُطرح كبدياً).",
            "Pus":   "💉 عدوى البطن والمرارة.",
        },
    },
    "Cefoperazone + Sulbactam": {
        "priority": 4, "class": "3rd Gen Cephalosporin + Beta-lactamase Inhibitor (IV)",
        "note": (
            "🛑 (مثل Sulperazone/Bakperazone) IV فقط. مزيج قوي ضد MDR gram-negatives "
            "بما فيها Acinetobacter baumannii. بديل مهم لـ Meropenem في بروتوكولات MDR المصرية."
        ),
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً — يُطرح صفراوياً أساساً.",
        "hepatic_caution": True, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True,
        "interacts_with": ["Warfarin (مضادات التخثر)"],
        "aliases": ["sulperazone","bakperazone","cefop-sulbactam","cefoperazone sulbactam"],
        "organisms": ["Acinetobacter baumannii","Pseudomonas aeruginosa","Klebsiella spp.",
                      "E. coli","Proteus mirabilis","Staphylococcus aureus"],
        "specimen_notes": {
            "Blood":      "🛑 MDR Acinetobacter/Pseudomonas bacteremia.",
            "Sputum":     "🛑 VAP/HAP بـ MDR Acinetobacter — بروتوكول ICU مصري شائع.",
            "Wound Swab": "🛑 العدوى الجراحية الشديدة ومضاعفات الحروق.",
            "Pus":        "🛑 الخراجات والعدوى داخل البطن عند فشل الخطوط الأولى.",
            "Urine":      "⚠️ بديل عند تعذر الكاربابينيم في MDR UTI.",
        },
    },
    "Cefepime": {
        "priority": 5, "class": "4th Gen Cephalosporin (IV)",
        "note": "🛑 (مثل Maxipime) IV فقط — للحالات الحرجة. Bioavailability فموي = صفر.",
        "renal_limit": 50, "renal_note": "CrCl 30-60: 1-2g q12h. CrCl 11-29: 500mg-1g q12h. CrCl <11: 250-500mg q24h. ⚠️ خطر encephalopathy عند تراكم الدواء — راقب الأعراض العصبية.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["maxipime"],
        "organisms": ["Pseudomonas aeruginosa","E. coli","Klebsiella spp.",
                      "Proteus mirabilis","Staphylococcus aureus",
                      "Enterococcus faecalis","Acinetobacter baumannii"],
        "specimen_notes": {
            "Blood":  "🛑 sepsis شديد مع اشتباه Pseudomonas.",
            "Sputum": "🛑 VAP/HAP الحرجة.",
            "CSF":    "🛑 meningitis المعقد في ICU.",
        },
    },
    # ── New Cephalosporins (Cefazolin, Cefoxitin) ─────────────────────
    "Cefazolin": {
        "priority": 2, "class": "1st Gen Cephalosporin (IV)",
        "note": "💉 (مثل Ancef/Kefzol) IV فقط. يستخدم للوقاية الجراحية وعدوى الجلد والأنسجة الرخوة.",
        "renal_limit": 50,
        "renal_note": "CrCl 10-30: 500mg q12h. CrCl <10: 250mg q12h. BNF 2025.",
        "hepatic_caution": False, "aware": "Access", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["ancef","kefzol","cefazolin"],
        "organisms": ["Staphylococcus aureus","E. coli","Klebsiella spp.",
                      "Proteus mirabilis","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Urine":      "✅ مناسب لالتهابات المسالك البولية (UTI) عند تأكيد الحساسية.",
            "Pus":        "✅ فعال في العدوى الجراحية والخراجات (معظم الإصابات الجلدية).",
            "Wound Swab": "✅ خيار ممتاز للوقاية الجراحية وعدوى الجروح.",
        },
    },
    "Cefoxitin": {
        "priority": 3, "class": "2nd Gen Cephalosporin (Cephamycin) (IV)",
        "note": "💉 (مثل Mefoxin) IV فقط. يغطي اللاهوائيات، يُستخدم للعدوى داخل البطن وأمراض النساء.",
        "renal_limit": 50,
        "renal_note": "CrCl 10-30: 1g q12h. CrCl <10: 500mg q12h. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["mefoxin","cefoxitin"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis",
                      "Bacteroides fragilis","Staphylococcus aureus"],
        "specimen_notes": {
            "Urine":      "✅ مناسب لالتهابات المسالك البولية المعقدة (مع اشتباه لاهوائيات).",
            "Pus":        "✅ فعال في الخراجات والعدوى المختلطة (يغطي اللاهوائيات).",
            "Wound Swab": "✅ خيار للجروح الملوثة والعدوى المختلطة.",
        },
    },
    # ── Fluoroquinolones ───────────────────────────────────────────────
    "Ciprofloxacin": {
        "priority": 2, "class": "Fluoroquinolone",
        "note": (
            "⚠️ (مثل Ciprofar) Oral وIV. Bioavailability فموي ~70-80%. "
            "يُفضل ادخاره للمسالك المعقدة."
        ),
        "renal_limit": 30, "renal_note": "CrCl <30: خفض الجرعة 50% أو مضاعفة الفترة. HD: جرعة بعد Dialysis. BNF 2025.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Ciprofloxacin:\n"
            "  Use with Caution — لا يُعتبر خطاً أول أبداً في الحمل.\n"
            "  الأدلة الحديثة (ENTIS 2024 / BMJ 2023): خطر تشوهات خلقية\n"
            "  أقل مما كان يُعتقد — لكن لا يزال غير مستصاف.\n"
            "  يُستخدم فقط عند: انعدام البديل الأكثر أمانًا + الضرورة الطبية.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)","Warfarin (مضادات التخثر)"],
        "aliases": ["ciprofar","cipro","ciproflox"],
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Proteus mirabilis","Staphylococcus aureus",
                      "Salmonella spp.","Shigella spp.","Campylobacter jejuni"],
        "specimen_notes": {
            "Urine":      "⚠️ فعال لكن يُحفظ للمسالك المعقدة.",
            "Blood":      "⚠️ bacteremia في الحالات المتوسطة.",
            "Sputum":     "⚠️ الفلوروكينولون الوحيد الفعال ضد Pseudomonas في الصدر.",
            "Wound Swab": "⚠️ عدوى الجروح المعقدة.",
            "Stool":      "⚠️ Shigellosis والحالات الشديدة من Campylobacter.",
        },
    },
    "Levofloxacin": {
        "priority": 2, "class": "Fluoroquinolone",
        "note": (
            "⚠️ (مثل Tavanic) Oral وIV. Bioavailability فموي ~99%. "
            "أفضل respiratory quinolone متاح."
        ),
        "renal_limit": 50, "renal_note": "CrCl 20-49: 500mg q24h (loading 500mg). CrCl 10-19: 250mg q24h. HD: 250mg q48h. BNF 2025.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Levofloxacin في الحمل:\n"
            "  Fluoroquinolone — لا يُعتبر خطاً أول في الحمل.\n"
            "  الأدلة الحديثة (ENTIS 2024): خطر التشوهات أقل مما كان يُعتقد.\n"
            "  يُستخدم فقط عند انعدام البديل الأكثر أمانًا.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["tavanic","levaquin","levoflox"],
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Staphylococcus aureus","Streptococcus pneumoniae","H. influenzae",
                      "Mycoplasma spp.","Legionella pneumophila"],
        "specimen_notes": {
            "Sputum": "⚠️ خيار قوي لـ CAP (respiratory quinolone) — Mycoplasma وLegionella.",
            "Urine":  "⚠️ فعال لكن يُحفظ للحالات المعقدة.",
            "Blood":  "⚠️ bacteremia في الحالات المتوسطة.",
        },
    },
    "Ofloxacin": {
        "priority": 2, "class": "Fluoroquinolone",
        "note": "⚠️ (مثل Tarivid) Oral وIV. Bioavailability فموي ~98%.",
        "renal_limit": 50, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Ofloxacin في الحمل:\n"
            "  Fluoroquinolone — لا يُعتبر خطاً أول في الحمل.\n"
            "  الأدلة الحديثة (ENTIS 2024): خطر التشوهات أقل مما كان يُعتقد.\n"
            "  يُستخدم فقط عند انعدام البديل الأكثر أمانًا.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["tarivid","oflox"],
        "organisms": ["E. coli","Klebsiella spp.","Staphylococcus aureus","Proteus mirabilis"],
        "specimen_notes": {
            "Urine":  "⚠️ مناسب للمسالك المتوسطة.",
            "Sputum": "⚠️ عدوى الجهاز التنفسي.",
        },
    },
    "Norfloxacin": {
        "priority": 2, "class": "Fluoroquinolone",
        "note": (
            "⚠️ (مثل Noroxin) Oral فقط — متخصص في المسالك البولية. "
            "Bioavailability ~35% لكن يتركز في البول."
        ),
        "renal_limit": 30, "renal_note": "CrCl 10-30: 500/125mg q12h (تجنّب 875mg). CrCl <10: 500/125mg q24h. BNF 2025.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Norfloxacin في الحمل:\n"
            "  Fluoroquinolone — لا يُعتبر خطاً أول في الحمل.\n"
            "  الأدلة الحديثة (ENTIS 2024): خطر التشوهات أقل مما كان يُعتقد.\n"
            "  ⚠️ Bioavailability منخفضة (35%) — تركيز محدود خارج البول.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["noroxin","norflox"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis",
                      "Staphylococcus aureus","Enterococcus faecalis"],
        "specimen_notes": {
            "Urine": "⚠️ مخصص للمسالك البولية فقط — لا تركيز علاجي خارج البول.",
        },
    },
    # ── New Fluoroquinolones (Gatifloxacin, Moxifloxacin) ─────────────
    "Gatifloxacin": {
        "priority": 3, "class": "Fluoroquinolone (Oral/IV)",
        "note": "⚠️ (مثل Tequin) Oral وIV. فعال للعدوى التنفسية والجلدية، لكن استخدامه محدود بسبب QTc prolongation.",
        "renal_limit": 50, "renal_note": "CrCl <30: خفض الجرعة.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Gatifloxacin في الحمل:\n"
            "  Fluoroquinolone — لا يُعتبر خطاً أول.\n"
            "  انتبه لـ QTc prolongation."
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["tequin","gatiflox"],
        "organisms": ["E. coli","Klebsiella spp.","Staphylococcus aureus","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Urine":      "⚠️ يمكن استخدامه في المسالك المعقدة.",
            "Pus":        "⚠️ فعال في التهابات الجلد والأنسجة الرخوة (SSTI)، لكن يُفضل الفلوروكينولونات الأخرى.",
            "Wound Swab": "⚠️ خيار بديل للعدوى الجلدية.",
        },
    },
    "Moxifloxacin": {
        "priority": 3, "class": "Fluoroquinolone (Oral/IV)",
        "note": "⚠️ (مثل Avelox) Oral وIV. طيف واسع، ممتاز للجهاز التنفسي والجلد.",
        "renal_limit": 0, "renal_note": "🟢 لا يحتاج تعديل كلوي (يُطرح كبدياً).",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Moxifloxacin في الحمل:\n"
            "  Fluoroquinolone — لا يُعتبر خطاً أول.\n"
            "  بيانات محدودة."
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["avelox","moxiflox"],
        "organisms": ["Staphylococcus aureus","Streptococcus pneumoniae","H. influenzae","Mycoplasma spp."],
        "specimen_notes": {
            "Sputum":     "✅ ممتاز لـ CAP وعدوى الجهاز التنفسي.",
            "Pus":        "⚠️ خيار للعدوى الجلدية المعقدة (SSTI) عند فشل الخطوط الأولى.",
            "Wound Swab": "⚠️ بديل للعدوى الجلدية المختلطة.",
        },
    },
    # ── Urinary Antiseptics ────────────────────────────────────────────
    "Nitrofurantoin": {
        "priority": 1, "class": "Urinary Antiseptic (Oral)",
        "note": (
            "🎯 (مثل Macrofuran) Oral فقط — الخيار الأول للمسالك البسيطة. "
            "Bioavailability ~90% لكن يتركز في البول فقط."
        ),
        "renal_limit": 45, "renal_note": "🚫 ممنوع إذا CrCl < 45 مل/د (EMA/BNF 2025). عند CrCl 30-45: عدم كفاءة علاجية + تراكم سمي.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Nitrofurantoin:\n"
            "  ✅ آمن في الـ 1st و 2nd trimester لعلاج UTI (ACOG 2023).\n"
            "  ⛔ تجنّب في الـ 3rd trimester وخاصة عند الـ term (≥36 أسبوع):\n"
            "     → خطر hemolytic anemia في الجنين (G6PD deficiency).\n"
            "     → neonatal hemolysis عند الوليد.\n"
            "  البديل في الـ 3rd trim: Fosfomycin (جرعة واحدة) أو Cephalexin.\n"
            "  >>> القرار النهائي للطبيب المعالج حسب الـ trimester. <<<"
        ),
        "child_safe": True,
        "child_note": "⚠️ ممنوع <1 شهر (خطر hemolytic anemia في نقص G6PD). مقبول بعد شهر. AAP 2024.",
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["macrofuran","macrobid","nitrofur"],
        "organisms": ["E. coli","Staphylococcus aureus","Enterococcus faecalis","Klebsiella spp."],
        "specimen_notes": {
            "Urine": "🎯 مخصص للمسالك البولية البسيطة فقط — لا يُستخدم خارج البول أبداً.",
        },
    },
    "Fosfomycin": {
        "priority": 1, "class": "Phosphonic Acid (Oral)",
        "note": (
            "🎯 (مثل Monuril) Oral — جرعة واحدة للمسالك. "
            "Bioavailability ~34-58% لكن تركيزه في البول عالٍ جداً."
        ),
        "renal_limit": 40, "renal_note": "CrCl <40: تجنّب الجرعات المتكررة (IV). جرعة واحدة فموية (3g) مقبولة حتى CrCl >10. BNF 2025.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Fosfomycin:\n"
            "  EMA/BNF 2025: مقبول بجرعة واحدة (3g) لـ uncomplicated UTI في الحمل.\n"
            "  خيار مفضل على Nitrofurantoin في الـ 3rd trimester.\n"
            "  بيانات أكثر طمأنينة من الـ Fluoroquinolones.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": True,
        "child_note": "مسموح >12 سنة (oral 3g). IV: من عمر أصغر بإشراف طبي. AAP 2024 / EMA.",
        "interacts_with": [],
        "aliases": ["monuril","fosfocin"],
        "organisms": ["E. coli","Enterococcus faecalis","Staphylococcus aureus","Klebsiella spp."],
        "specimen_notes": {
            "Urine": "🎯 جرعة واحدة للـ uncomplicated UTI — مثالي.",
        },
    },
    # ── Aminoglycosides ────────────────────────────────────────────────
    "Gentamicin": {
        "priority": 4, "class": "Aminoglycoside (IV/IM)",
        "note": "💉 (مثل Garamycin) IV/IM فقط — لا bioavailability فموي. سام للكلى والأذن.",
        "renal_limit": 60, "renal_note": "Extended interval: 5-7mg/kg q24h ثم تعديل حسب levels. CrCl <60: تمديد الفترة + trough <1 mcg/mL. KDIGO 2024.",
        "hepatic_caution": False, "aware": "Access", "high_po": False,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Gentamicin:\n"
            "  سُمية للأذن الجنينية (ototoxicity) — FDA Category D.\n"
            "  يعبر المشيمة — خطر فقدان السمع الدائم للجنين."
        ),
        "child_safe": True,
        "interacts_with": ["NSAIDs (مسكنات الألم)"],
        "aliases": ["garamycin","genta"],
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Proteus mirabilis","Staphylococcus aureus"],
        "specimen_notes": {
            "Blood":      "💉 synergy مع beta-lactam في bacteremia الشديدة.",
            "Wound Swab": "💉 العدوى الجراحية الشديدة.",
            "Urine":      "💉 pyelonephritis المعقد عند عدم توفر بدائل.",
        },
    },
    "Amikacin": {
        "priority": 4, "class": "Aminoglycoside (IV/IM)",
        "note": "💉 (مثل Amikin) IV/IM فقط — لا bioavailability فموي. فعال ضد السالبات المقاومة.",
        "renal_limit": 60, "renal_note": "15-20mg/kg q24h. CrCl 40-60: q36h. CrCl 20-40: q48h. CrCl <20: monitoring-based dosing. KDIGO 2024.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Amikacin:\n"
            "  سُمية للأذن الجنينية (ototoxicity) — FDA Category D.\n"
            "  يعبر المشيمة — خطر فقدان السمع الدائم للجنين."
        ),
        "child_safe": True,
        "interacts_with": ["NSAIDs (مسكنات الألم)"],
        "aliases": ["amikin","amikacin"],
        "organisms": ["E. coli","Klebsiella spp.","Pseudomonas aeruginosa",
                      "Proteus mirabilis","Staphylococcus aureus","Acinetobacter baumannii"],
        "specimen_notes": {
            "Blood":  "💉 MDR gram-negatives bacteremia.",
            "Sputum": "💉 HAP/VAP مع MDR organisms.",
            "Urine":  "💉 UTI المعقد مع MDR organisms.",
        },
    },
    # ── New Aminoglycoside (Tobramycin) ────────────────────────────────
    "Tobramycin": {
        "priority": 4, "class": "Aminoglycoside (IV/IM)",
        "note": "💉 (مثل Nebcin) IV/IM فقط. فعال ضد Pseudomonas والسالبات الأخرى. سام للكلى والأذن.",
        "renal_limit": 60, "renal_note": "دوز حسب CrCl: 3-5mg/kg/day مقسمة. مراقبة مستويات الدم.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Tobramycin:\n"
            "  سُمية للأذن الجنينية (ototoxicity) — FDA Category D.\n"
            "  يعبر المشيمة — خطر فقدان السمع الدائم للجنين."
        ),
        "child_safe": True,
        "interacts_with": ["NSAIDs (مسكنات الألم)"],
        "aliases": ["nebcin","tobra","tobramycin"],
        "organisms": ["Pseudomonas aeruginosa","E. coli","Klebsiella spp.",
                      "Staphylococcus aureus","Proteus mirabilis"],
        "specimen_notes": {
            "Urine":      "💉 لالتهابات المسالك المعقدة مع Pseudomonas.",
            "Pus":        "💉 فعال في العدوى الشديدة بالأنسجة الرخوة والخراجات (خاصة مع Pseudomonas).",
            "Wound Swab": "💉 للعدوى الجراحية الشديدة.",
        },
    },
    # ── Macrolides ─────────────────────────────────────────────────────
    "Azithromycin": {
        "priority": 2, "class": "Macrolide (Oral/IV)",
        "note": (
            "✅ (مثل Zithrokan) Oral وIV. Bioavailability فموي ~37% "
            "لكن تركيزه النسيجي عالٍ جداً — فعال للجهاز التنفسي."
        ),
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["zithrokan","zithromax","azithro"],
        "organisms": ["Staphylococcus aureus","Streptococcus pneumoniae","H. influenzae",
                      "Mycoplasma spp.","Salmonella spp.","Shigella spp.",
                      "Campylobacter jejuni","Legionella pneumophila"],
        "specimen_notes": {
            "Sputum":     "✅ خيار ممتاز لـ CAP والـ atypicals (Mycoplasma/Legionella).",
            "Wound Swab": "✅ عدوى الجلد الخفيفة.",
            "Stool":      "✅ الخيار الأول في Campylobacter وبعض حالات Shigella.",
        },
    },
    "Clarithromycin": {
        "priority": 2, "class": "Macrolide (Oral/IV)",
        "note": "✅ (مثل Klacid) Oral وIV. Bioavailability فموي ~55%. فعال للصدر.",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Clarithromycin:\n"
            "  ارتبط بتشوهات خلقية في الدراسات الحيوانية والبشرية.\n"
            "  البديل الآمن: Azithromycin."
        ),
        "child_safe": True, "interacts_with": [],
        "aliases": ["klacid","biaxin"],
        "organisms": ["Staphylococcus aureus","Streptococcus pneumoniae",
                      "H. influenzae","Mycoplasma spp.","Legionella pneumophila"],
        "specimen_notes": {
            "Sputum": "✅ CAP والـ atypical pneumonia.",
        },
    },
    # ── Sulfonamides ───────────────────────────────────────────────────
    "Trimethoprim/Sulfamethoxazole": {
        "priority": 2, "class": "Sulfonamide (Oral/IV)",
        "note": (
            "✅ (مثل Sutrim/Bactrim) Oral وIV. Bioavailability فموي ~100%. "
            "ممتاز للمسالك والجهاز التنفسي."
        ),
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — TMP/SMX:\n"
            "  يثبط حمض الفوليك — خطر Neural Tube Defects في الـ 1st trimester.\n"
            "  يسبب kernicterus للجنين في الـ 3rd trimester."
        ),
        "child_safe": True,
        "interacts_with": ["Warfarin (مضادات التخثر)"],
        "aliases": ["septra","sutrim","bactrim","co-trimoxazole","tmp-smx"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis","Staphylococcus aureus",
                      "Stenotrophomonas maltophilia","Shigella spp.","Salmonella spp."],
        "specimen_notes": {
            "Urine":      "✅ فعال للمسالك البسيطة عند تأكيد الحساسية.",
            "Sputum":     "✅ الجهاز التنفسي — خيار أول لـ Stenotrophomonas.",
            "Wound Swab": "✅ MRSA skin infections (SSTI).",
        },
    },
    # ── Nitroimidazoles ────────────────────────────────────────────────
    "Metronidazole": {
        "priority": 1, "class": "Nitroimidazole (Oral/IV)",
        "note": (
            "✅ (مثل Flagyl) Oral وIV. Bioavailability فموي ~100%. "
            "الخيار الأول للأنيروبيك."
        ),
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً.",
        "hepatic_caution": True, "aware": "Access", "high_po": True,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Metronidazole:\n"
            "  ACOG 2021 (updated): الأدلة الحديثة دحضت مخاوف التشوهات القديمة.\n"
            "  مقبول في كل trimesters عند الضرورة الطبية.\n"
            "  يُفضل تجنبه في الـ 1st trimester عند وجود بديل آمن.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": True,
        "interacts_with": ["Warfarin (مضادات التخثر)"],
        "aliases": ["flagyl","metro","metrogyl"],
        "organisms": ["Anaerobes (لاهوائيات)"],
        "specimen_notes": {
            "Pus":        "✅ الخراجات والعدوى المختلطة (anaerobic coverage).",
            "Wound Swab": "✅ العدوى الجراحية التي تشمل اللاهوائيات.",
            "Stool":      "✅ بعض الطفيليات والعدوى اللاهوائية.",
            "Blood":      "✅ sepsis البطن مع اشتباه anaerobic.",
        },
    },
    "Tinidazole": {
        "priority": 2, "class": "Nitroimidazole (Oral)",
        "note": "✅ (مثل Fasigyn) Oral فقط. Bioavailability ~100%. بديل Metronidazole.",
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً.",
        "hepatic_caution": True, "aware": "Access", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Tinidazole:\n"
            "  ممنوع في الـ 1st trimester.\n"
            "  يُفضل تجنبه طوال الحمل — استبدل بـ Metronidazole."
        ),
        "child_safe": False,
        "interacts_with": ["Warfarin (مضادات التخثر)"],
        "aliases": ["fasigyn","tini"],
        "organisms": ["Anaerobes (لاهوائيات)"],
        "specimen_notes": {
            "Wound Swab": "✅ عدوى اللاهوائيات الخفيفة.",
        },
    },
    # ── Tetracyclines ──────────────────────────────────────────────────
    "Doxycycline": {
        "priority": 2, "class": "Tetracycline (Oral/IV)",
        "note": (
            "✅ (مثل Vibramycin) Oral وIV. Bioavailability فموي ~93%. "
            "فعال للكلاميديا والمايكوبلازما."
        ),
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً نسبياً.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "⛔ ممنوع في الحمل — Doxycycline (Tetracycline class):\n"
            "  يترسّب في عظام وأسنان الجنين → تصبغ دائم وتثبيط نمو العظام.\n"
            "  محظور خاصة بعد الأسبوع 15 (2nd و3rd trimester).\n"
            "  ACOG 2023 / BNF 2025: لا يُستخدم في الحمل إطلاقاً.\n"
            "  البديل: Amoxicillin-Clavulanate أو Cephalosporin أو Azithromycin."
        ),
        "child_safe": False,
        "child_note": "ممنوع <8 سنوات (teeth/bone). >8 سنوات: مقبول للـ atypicals وRickettsia عند الضرورة. BNF 2025.",
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["vibramycin","doxy"],
        "organisms": ["Mycoplasma spp.","Staphylococcus aureus","H. influenzae",
                      "Rickettsia spp.","Acinetobacter baumannii",
                      "Stenotrophomonas maltophilia","Legionella pneumophila"],
        "specimen_notes": {
            "Sputum":     "✅ atypical pneumonia (Mycoplasma/Legionella).",
            "Wound Swab": "✅ MRSA SSTI و Rickettsia.",
            "Blood":      "✅ Rickettsia bacteremia.",
        },
    },
    # ── Carbapenems ────────────────────────────────────────────────────
    "Imipenem/Cilastatin": {
        "priority": 5, "class": "Carbapenem (IV)",
        "note": (
            "🛑 (مثل Tienam) IV فقط — bioavailability فموي = صفر. "
            "أوسع كاربابينيم طيفاً — يغطي Pseudomonas والموجبات والسالبات واللاهوائيات. "
            "⚠️ خطر نوبات صرع عند الجرعات العالية أو القصور الكلوي. "
            "Cilastatin يمنع تكسره كلوياً."
        ),
        "renal_limit": 50,
        "renal_note": "CrCl 41-70: 500mg q8h. CrCl 21-40: 250-500mg q8h. CrCl 6-20: 250mg q6-12h. ⚠️ خطر seizures يرتفع عند تراكم الدواء. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Imipenem/Cilastatin:\n"
            "  بيانات بشرية محدودة — Category C.\n"
            "  عند الحاجة لكاربابينيم في الحمل: يُفضل Meropenem (بيانات أكثر أمانًا).\n"
            "  يُستخدم Imipenem فقط عند تعذّر Meropenem وخطورة الحالة.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": True,
        "interacts_with": ["Valproic acid (مضادات الصرع)"],
        "aliases": ["tienam","primaxin","imipenem","imipenem cilastatin"],
        "organisms": ["Pseudomonas aeruginosa","Klebsiella spp.","E. coli",
                      "Acinetobacter baumannii","Enterococcus faecalis",
                      "Staphylococcus aureus","Proteus mirabilis",
                      "Anaerobes (لاهوائيات)"],
        "specimen_notes": {
            "Blood":  "🛑 sepsis شديد — MDR organisms — يغطي طيفاً أوسع من Meropenem.",
            "Sputum": "🛑 VAP/HAP بـ MDR organisms — بديل Meropenem.",
            "Urine":  "🛑 UTI المعقد بـ CRE عند تعذر خيارات أخرى.",
            "Pus":    "🛑 عدوى البطن الشديدة المختلطة — يغطي اللاهوائيات أيضاً.",
            "CSF":    "⚠️ لا يُفضل في meningitis — خطر نوبات صرع. استخدم Meropenem.",
        },
    },
    "Ertapenem": {
        "priority": 5, "class": "Carbapenem non-anti-pseudomonal (IV/IM)",
        "note": (
            "🛑 (مثل Invanz) IV/IM — جرعة يومية واحدة. "
            "لا يغطي Pseudomonas ولا Acinetobacter. Bioavailability فموي = صفر."
        ),
        "renal_limit": 30, "renal_note": "CrCl 10-30: 500/125mg q12h (تجنّب 875mg). CrCl <10: 500/125mg q24h. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["invanz","ertapenem"],
        "organisms": ["E. coli","Klebsiella spp.","Proteus mirabilis",
                      "Staphylococcus aureus","Enterococcus faecalis",
                      "Anaerobes (لاهوائيات)"],
        "specimen_notes": {
            "Blood": "🛑 ESBL bacteremia — يفضل على Meropenem للحفاظ على الكاربابينيم.",
            "Urine": "🛑 ESBL-producing UTI المعقد فقط.",
            "Pus":   "🛑 عدوى البطن المعقدة بـ ESBL.",
        },
    },
    "Meropenem": {
        "priority": 5, "class": "Carbapenem (IV)",
        "note": (
            "🛑 (مثل Meronem) IV فقط — الملاذ الأخير للمقاومة. "
            "Bioavailability فموي = صفر. أقل خطراً للصرع من Imipenem."
        ),
        "renal_limit": 50, "renal_note": "CrCl 26-50: 1g q12h. CrCl 10-25: 500mg q12h. CrCl <10: 500mg q24h. HD: dose بعد dialysis. BNF 2025.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["meronem","merrem"],
                "organisms": ["Pseudomonas aeruginosa","Klebsiella spp.","E. coli",
                      "Enterococcus faecalis","Staphylococcus aureus",
                      "Acinetobacter baumannii"],

        "specimen_notes": {
            "Blood":  "🛑 sepsis شديد — MDR organisms — ICU.",
            "CSF":    "🛑 meningitis المعقد — MDR — أفضل من Imipenem للـ CNS.",
            "Sputum": "🛑 VAP/HAP بـ MDR organisms.",
            "Urine":  "🛑 UTI المعقد جداً بـ CRE.",
        },
    },
    # ── Glycopeptides / Oxazolidinones ─────────────────────────────────
    "Vancomycin": {
        "priority": 5, "class": "Glycopeptide (IV)",
        "note": (
            "🛑 IV فقط — خاص بـ MRSA والحالات الحرجة. "
            "Bioavailability فموي < 5% جهازياً — IV فقط للعدوى الجهازية. "
            "مراقبة الـ Trough أو AUC/MIC حتمية."
        ),
        "renal_limit": 50, "renal_note": "AUC/MIC target 400-600 mg·h/L. CrCl <50: تمديد الفترة. HD: supplement بعد dialysis. ASHP/IDSA/SIDP Consensus 2020.",
        "hepatic_caution": False, "aware": "Watch", "high_po": False,
        "preg_status": "Warn",
        "preg_note": (
            "تحذير حمل — Vancomycin:\n"
            "  يُستخدم عند الضرورة القصوى (MRSA في الحمل).\n"
            "  مراقبة وظائف الكلى والسمع للأم والجنين.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": True,
        "interacts_with": ["NSAIDs (مسكنات الألم)"],
        "aliases": ["vancocin","vanco"],
        "organisms": ["MRSA","Staphylococcus aureus","Enterococcus faecalis",
                      "Streptococcus pneumoniae"],
        "specimen_notes": {
            "Blood":      "🛑 MRSA bacteremia.",
            "CSF":        "🛑 MRSA meningitis.",
            "Sputum":     "🛑 MRSA pneumonia في ICU.",
            "Wound Swab": "🛑 MRSA wound infection.",
        },
    },
    "Linezolid": {
        "priority": 5, "class": "Oxazolidinone (Oral/IV)",
        "note": (
            "🛑 (مثل Averozolid) Oral وIV. Bioavailability فموي ~100%. "
            "للموجبات المقاومة (MRSA/VRE) فقط."
        ),
        "renal_limit": 0, "renal_note": "🟢 آمن كلوياً.",
        "hepatic_caution": False, "aware": "Reserve", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "ممنوع في الحمل — Linezolid:\n"
            "  أثبت سُمية جنينية في الحيوانات.\n"
            "  يُستخدم فقط عند انعدام البدائل."
        ),
        "child_safe": True,
        "interacts_with": ["SSRI (أدوية الاكتئاب)"],
        "aliases": ["averozolid","zyvox"],
        "organisms": ["MRSA","Staphylococcus aureus","Enterococcus faecalis",
                      "VRE","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Blood":      "🛑 VRE/MRSA bacteremia.",
            "Sputum":     "🛑 MRSA pneumonia — تركيز رئوي ممتاز.",
            "Wound Swab": "🛑 MRSA/VRE wound infection.",
            "CSF":        "🛑 اختراق ممتاز للـ CNS.",
        },
    },
    # ── Polymyxins ─────────────────────────────────────────────────────
    "Colistin": {
        "priority": 6, "class": "Polymyxin (IV)",
        "note": (
            "🔴 IV فقط — الملاذ الأخير للـ MDR gram-negatives. "
            "Bioavailability فموي = صفر."
        ),
        "renal_limit": 50, "renal_note": "CrCl <50: تعديل جرعة إلزامي. CrCl <30: خفض كبير. HD: dose بعد dialysis. إيقاف فوري عند Cr↑ >0.5 عن baseline. BNF 2025.",
        "hepatic_caution": False, "aware": "Reserve", "high_po": False,
        "preg_status": "Warn",
        "preg_note": (
            "⚠️ Use with Caution — Colistin في الحمل:\n"
            "  بيانات بشرية محدودة جداً — Category C.\n"
            "  nephrotoxicity شديد → خطر على وظائف كلى الأم والجنين.\n"
            "  يُستخدم فقط لإنقاذ الحياة في XDR gram-negatives عند غياب أي بديل.\n"
            "  BNF 2025: تجنّب ما أمكن — monitor renal function closely.\n"
            "  >>> القرار النهائي للطبيب المعالج حصراً. <<<"
        ),
        "child_safe": True,
        "interacts_with": ["NSAIDs (مسكنات الألم)"],
        "aliases": ["colistin","polymyxin e"],
        "organisms": ["Pseudomonas aeruginosa","Acinetobacter baumannii","Klebsiella spp."],
        "specimen_notes": {
            "Blood":  "🔴 MDR/XDR bacteremia — ملاذ أخير.",
            "Sputum": "🔴 VAP بـ XDR Acinetobacter/Pseudomonas.",
        },
    },
}
VALID_AWARE_VALUES = {"Access", "Watch", "Reserve"}
DEFAULT_SPECIMENS = ("Urine", "Blood", "Sputum", "Wound Swab", "Pus", "Stool", "CSF")


def normalize_abx_key(text: str) -> str:
    """Return a relaxed normalized key for antibiotic lookup."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def build_antibiotic_alias_index(data: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    index: Dict[str, str] = {}
    for official_name, payload in data.items():
        variants = [official_name, *payload.get("aliases", [])]
        for variant in variants:
            normalized = normalize_abx_key(variant)
            if normalized:
                index[normalized] = official_name
    return index


def get_antibiotic(name_or_alias: str) -> Optional[Dict[str, Any]]:
    """Get a guideline record by official name or alias."""
    normalized = normalize_abx_key(name_or_alias)
    official_name = ABX_ALIAS_INDEX.get(normalized)
    if official_name:
        return ABX_GUIDELINES.get(official_name)
    return ABX_GUIDELINES.get(name_or_alias)


def validate_abx_guidelines(
    known_organisms: Optional[Iterable[str]] = None,
    known_specimens: Optional[Iterable[str]] = None,
) -> list[str]:
    """Run lightweight validation checks and return issue strings."""
    issues: list[str] = []
    organism_set = set(known_organisms or [])
    specimen_set = set(known_specimens or DEFAULT_SPECIMENS)

    for abx_name, payload in ABX_GUIDELINES.items():
        required_keys = {
            "priority", "class", "note", "renal_limit", "renal_note",
            "hepatic_caution", "aware", "high_po", "preg_status",
            "preg_note", "child_safe", "interacts_with", "aliases",
            "organisms", "specimen_notes",
        }
        missing = sorted(required_keys - set(payload.keys()))
        if missing:
            issues.append(f"{abx_name}: missing keys -> {', '.join(missing)}")

        aware = payload.get("aware")
        if aware not in VALID_AWARE_VALUES:
            issues.append(f"{abx_name}: invalid AWaRe value -> {aware}")

        for specimen_name in payload.get("specimen_notes", {}):
            if specimen_name not in specimen_set:
                issues.append(f"{abx_name}: unknown specimen note -> {specimen_name}")

        if organism_set:
            for organism_name in payload.get("organisms", []):
                if organism_name not in organism_set:
                    issues.append(f"{abx_name}: organism not defined in organism profile -> {organism_name}")

    return issues


ABX_ALIAS_INDEX = build_antibiotic_alias_index(ABX_GUIDELINES)

__all__ = [
    "ABX_ALIAS_INDEX",
    "ABX_GUIDELINES",
    "DEFAULT_SPECIMENS",
    "VALID_AWARE_VALUES",
    "build_antibiotic_alias_index",
    "get_antibiotic",
    "normalize_abx_key",
    "validate_abx_guidelines",
]

# ── Penicillins (plain) ────────────────────────────────────────────────────
_EXTRA_ENTRIES = {
    "Ampicillin": {
        "priority": 2, "class": "Penicillin (IV/Oral)",
        "note": "⚠️ مقاومة عالية (>80%) في معظم الكائنات بدون مثبط. يُستخدم غالباً بمثبط (Ampicillin/Sulbactam).",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["ampicillin","ampicil","ampicilli"],
        "organisms": ["Enterococcus faecalis","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Urine": "⚠️ مقاومة عالية — تحقق من نتيجة المزرعة.",
            "Blood": "⚠️ يُستخدم مع Sulbactam للحالات المتوسطة.",
        },
    },
    "Amoxicillin": {
        "priority": 1, "class": "Penicillin (Oral)",
        "note": "✅ (مثل Amoxil) Oral. Bioavailability ~90%. بدون مثبط — مقاومة عالية لكثير من الكائنات.",
        "renal_limit": 30, "renal_note": "⚖️ تعديل الجرعة مطلوب.",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe", "preg_note": "",
        "child_safe": True, "interacts_with": [],
        "aliases": ["amoxil","amoxicillin","amoxycillin","amoxy"],
        "organisms": ["Streptococcus pneumoniae","Enterococcus faecalis","H. influenzae"],
        "specimen_notes": {
            "Urine":  "⚠️ مقاومة عالية — يُفضل Amoxicillin + Clavulanic acid.",
            "Sputum": "✅ CAP بسيط عند تأكيد الحساسية.",
        },
    },
    "Tetracycline": {
        "priority": 3, "class": "Tetracycline (Oral)",
        "note": "⚠️ (مثل Achromycin) Oral. Bioavailability ~77%. أقل تفضيلاً من Doxycycline.",
        "renal_limit": 0, "renal_note": "⚠️ تجنب في القصور الكلوي الشديد.",
        "hepatic_caution": True, "aware": "Watch", "high_po": True,
        "preg_status": "Banned",
        "preg_note": (
            "⛔ ممنوع في الحمل — Tetracycline (Tetracycline class):\n"
            "  يترسّب في عظام وأسنان الجنين → تصبغ دائم وتثبيط نمو العظام.\n"
            "  ACOG 2023 / BNF 2025: contraindication مطلقة في كل مراحل الحمل.\n"
            "  البديل: Amoxicillin-Clavulanate أو Cephalosporin أو Azithromycin."
        ),
        "child_safe": False,
        "interacts_with": ["Antacids (مضادات الحموضة)"],
        "aliases": ["achromycin","tetracycline","tetracyclin"],
        "organisms": ["Staphylococcus aureus","Mycoplasma spp.","H. influenzae"],
        "specimen_notes": {
            "Sputum":     "⚠️ atypical pneumonia — يُفضل Doxycycline.",
            "Wound Swab": "⚠️ SSTI — يُفضل Doxycycline.",
        },
    },
    "Cephradine": {
        "priority": 3, "class": "Cephalosporins",
        "note": (
            "✅ (مثل Velosef/Sefril) Oral. 1st-gen cephalosporin — فعال ضد Gram+ (Staph/Strep). "
            "مكافئ فموي لـ Cefazolin. للجلد والمسالك والجهاز التنفسي العلوي."
        ),
        "renal_limit": 30, "renal_note": "CrCl 20-50: 250mg q8h | CrCl <20: 250mg q12h",
        "hepatic_caution": False, "aware": "Access", "high_po": True,
        "preg_status": "Safe",
        "preg_note": "مقبول في الحمل — Category B (ACOG).",
        "child_safe": True,
        "child_note": "مسموح للأطفال > 9 أشهر. جرعة 25-50 mg/kg/day.",
        "interacts_with": [],
        "aliases": ["velosef","sefril","eskacef","cephradine","cefradine"],
        "organisms": ["Staphylococcus aureus","E. coli","Proteus mirabilis","Streptococcus pneumoniae"],
        "specimen_notes": {
            "Urine":      "✅ مناسب للمسالك البسيطة (uncomplicated cystitis).",
            "Sputum":     "⚠️ تغطية Gram- محدودة — ليس خياراً أول للالتهاب الرئوي.",
            "Wound Swab": "✅ تغطية Gram+ جيدة لعدوى الجروح الخفيفة.",
            "Pus":        "✅ عدوى الجلد والأنسجة الرخوة.",
        },
    },
}

for _k, _v in _EXTRA_ENTRIES.items():
    if _k not in ABX_GUIDELINES:
        ABX_GUIDELINES[_k] = _v

# Rebuild alias index to include new entries
ABX_ALIAS_INDEX = build_antibiotic_alias_index(ABX_GUIDELINES)
