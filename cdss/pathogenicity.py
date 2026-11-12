"""Pathogenicity score: is this isolate a true pathogen or a contaminant/coloniser?"""
from __future__ import annotations

import re

from .organisms import org_in as _org_in
from .specimens import classify_specimen

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
        "Staphylococcus aureus", "MRSA", "Staphylococcus epidermidis",
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
        "Staphylococcus aureus", "MRSA", "Moraxella catarrhalis",
        "Acinetobacter baumannii", "Enterobacter spp.",
        "Escherichia coli", "Serratia marcescens",
        "Stenotrophomonas maltophilia", "Legionella pneumophila",
        "Mycoplasma spp.",
    ]
    URT_CONTAMINANTS_SPUTUM = [
        "Streptococcus viridans", "Neisseria spp.", "Candida spp.",
        "Candida albicans", "Staphylococcus epidermidis",
        "Corynebacterium spp.",
    ]
    TRUE_BLOOD_PATHOGENS = [
        "Staphylococcus aureus", "MRSA", "Streptococcus pneumoniae",
        "Escherichia coli", "Klebsiella pneumoniae", "Pseudomonas aeruginosa",
        "Acinetobacter baumannii", "Enterococcus faecalis", "Enterococcus spp.",
        "VRE", "Proteus mirabilis", "Salmonella spp.", "H. influenzae",
        "Anaerobes (لاهوائيات)", "Stenotrophomonas maltophilia",
        "Candida albicans", "Candida spp.",
        "Neisseria meningitidis", "Listeria monocytogenes",
    ]
    BLOOD_CONTAMINANTS = [
        "Staphylococcus epidermidis", "Corynebacterium spp.",
        "Bacillus spp.", "Propionibacterium spp.", "Micrococcus spp.",
    ]

    # Route on the single canonical classifier so the engine and the UI can
    # never disagree about what a specimen is (see classify_specimen).
    cat = classify_specimen(specimen)

    # ══════════════════════════════════════════════════════════════════
    # URINE
    # ══════════════════════════════════════════════════════════════════
    if cat == "urine":

        # Pediatric threshold: < 2 years → any growth significant
        if age < 2:
            score += 20
            factors_pos.append("✅ Infant < 2 yrs — any colony count clinically significant")
            special_flags.append("PEDIATRIC_UTI")

        # Organism context
        if _org_in(organism, TYPICAL_UROPATHOGENS):
            score += 20
            factors_pos.append(f"✅ {organism} — typical uropathogen")
        elif _org_in(organism, ATYPICAL_UROPATHOGENS):
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
        else:
            # Additive, not an elif-chain. A real UTI commonly shows pyuria AND
            # positive nitrites together — the strongest combination there is —
            # but the old chain stopped at the first match, so the second finding
            # scored nothing and could not be entered anyway (the UI was a
            # single-select). Substring tests, so the UI is free to reword the
            # labels without silently detaching them from the engine.
            _ua = (urinalysis_result or "").lower()
            if "طبيعي" in (urinalysis_result or "") or "normal" in _ua:
                score -= 25
                factors_neg.append("❌ Normal urinalysis — strongly suggests contamination")
            else:
                if "pyuria" in _ua or "wbc" in _ua:
                    score += 15
                    factors_pos.append("✅ Pyuria noted on urinalysis")
                if "nitrit" in _ua:
                    score += 10
                    factors_pos.append("➕ Nitrites positive — bacterial activity")
                # Hematuria was offered in the UI and read by nothing: picking it
                # scored exactly zero. It is weak evidence on its own (stones,
                # tumours and menstruation all cause it) but it does support
                # cystitis alongside other findings, so it now carries a small
                # weight instead of being silently discarded.
                if "hematuria" in _ua or "haematuria" in _ua or "دم" in (urinalysis_result or ""):
                    score += 5
                    factors_pos.append("➕ Hematuria — يدعم التهاب المثانة (غير نوعي)")

        # ABU Detection
        classic_symp = [s for s in symptoms if s in [
            "Dysuria / Frequency / Urgency", "Fever (> 38°C)", "Flank pain / Loin pain"
        ]]
        # Not applied under 2 years: an infant cannot report dysuria or flank
        # pain, so "no symptoms entered" is not "asymptomatic", and the IDSA
        # 2019 do-not-treat recommendation must not be issued for them.
        if (age >= 2 and not classic_symp and cfu_val >= 100000
                and pus_val is not None and pus_val >= 5):
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
    elif cat in ("sputum", "respiratory"):
        # Expectorated sputum ('sputum') AND lower-respiratory aspirates
        # ('respiratory': BAL / bronchial / tracheal) share pathogen + symptom
        # scoring. Murray-Washington below only fires when WBC/epithelial counts
        # are supplied — the UI supplies them for expectorated sputum only, so
        # BAL is correctly scored WITHOUT Murray-Washington.

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
        if _org_in(organism, RESPIRATORY_PATHOGENS):
            score += 20
            factors_pos.append(f"✅ {organism} — recognized respiratory pathogen")
        elif _org_in(organism, URT_CONTAMINANTS_SPUTUM):
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
    elif cat == "blood":

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
        if _org_in(organism, TRUE_BLOOD_PATHOGENS):
            score += 25
            factors_pos.append(f"✅ {organism} — true bloodstream pathogen; single positive = significant")
        elif _org_in(organism, BLOOD_CONTAMINANTS):
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
        elif "Single bottle" in blood_source and _org_in(organism, BLOOD_CONTAMINANTS):
            score -= 15
            factors_neg.append("⚠️ Single bottle + contaminant organism — likely contamination")

        # Source identified
        if blood_source and "source" in blood_source.lower():
            score += 10
            factors_pos.append(f"➕ Source identified: {blood_source}")

    # ══════════════════════════════════════════════════════════════════
    # CSF
    # ══════════════════════════════════════════════════════════════════
    elif cat == "csf":
        score += 40
        factors_pos.append("✅ CSF — any growth is always clinically significant (sterile site)")
        special_flags.append("CSF_ALWAYS_SIGNIFICANT")
        # Skin flora (CoNS/Coryne/Propioni/Bacillus) can contaminate LP samples.
        if _org_in(organism, BLOOD_CONTAMINANTS):
            factors_neg.append(
                f"⚠️ {organism} is common skin flora — without a CNS device "
                "(VP shunt / EVD) or ≥2 concordant cultures, consider LP "
                "contamination. Treat empirically until excluded."
            )

    # ══════════════════════════════════════════════════════════════════
    # STOOL / GI
    # ══════════════════════════════════════════════════════════════════
    elif cat == "stool":

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

        if _org_in(organism, GI_TRUE_PATHOGENS):
            score += 40
            factors_pos.append(f"✅ {organism} — obligate GI pathogen; always clinically significant")
            special_flags.append("GI_TRUE_PATHOGEN")
        elif _org_in(organism, GI_NORMAL_FLORA):
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
    elif cat == "wound":
        # Only true wound/pus/abscess/tissue specimens reach here. Genital,
        # throat and other swabs are NOT wounds — they fall through to the
        # shared factors below (generic scoring), which is clinically correct.
        wound_lower = wound_type.lower() if wound_type else ""

        if _org_in(organism, NORMAL_SKIN_FLORA) and not wound_lower:
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
            factors_neg.append("⚠️ Superficial wound — assess depth and clinical signs")

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
        factors_pos.append(
            "✅ Pregnancy — any significant bacteriuria requires treatment"
            if cat == "urine"
            else "✅ Pregnancy — lower threshold for treating significant infection"
        )
    if not host_factors:
        score -= 5
        factors_neg.append("ℹ️ No host risk factors identified")

    # Pediatric global flag
    if age < 3 and "PEDIATRIC_UTI" not in special_flags and cat != "csf":
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
        verdict = "🟠 SPECIMEN INADEQUATE — Reject & Repeat"
        color   = "warning"
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

_SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")


def _parse_cfu(text: str) -> int:
    """Colony count (CFU/mL) from free text; 0 when no count is stated.

    Accepts the ways a count is actually written on reports:
        "≥ 10^5 CFU/mL"  "10⁵"  "5 x 10^4"  "1e5"  "100,000"  ">100000"
        "50,000 - 100,000" (the upper bound is used)
    Superscript exponents matter: "10⁵" contains no "^", and its digits are
    not decimal digits to a regex, so it used to parse as 10 CFU/mL.
    """
    if not text:
        return 0
    t = str(text).lower()
    t = re.sub(r"10([⁰¹²³⁴⁵⁶⁷⁸⁹]+)", lambda m: "10^" + m.group(1).translate(_SUPERSCRIPTS), t)
    t = re.sub(r"[\s\u2009\u00a0,]", "", t)
    values = []
    for mant, exp in re.findall(r"(\d+(?:\.\d+)?)?[x×*]?10\^(\d{1,2})", t):
        values.append(int(round(float(mant or 1) * 10 ** int(exp))))
    t_rest = re.sub(r"(\d+(?:\.\d+)?)?[x×*]?10\^\d{1,2}", " ", t)
    for mant, exp in re.findall(r"(\d+(?:\.\d+)?)e\+?(\d{1,2})(?![a-z0-9])", t_rest):
        values.append(int(round(float(mant) * 10 ** int(exp))))
    t_rest = re.sub(r"\d+(?:\.\d+)?e\+?\d{1,2}(?![a-z0-9])", " ", t_rest)
    values.extend(int(n) for n in re.findall(r"\d+", t_rest))
    return max(values) if values else 0


def _parse_pus(text: str):
    """Max WBC/HPF stated in `text`, or None when no count is given.

    TNTC ("too numerous to count") is the most florid pyuria a microscopist can
    report — and it contains no digits, so the old version returned None for it
    and the caller fell through to the weaker urinalysis branch. A field that
    says "the WBCs are uncountable" scored as "no pus cell count entered".
    We map it to a sentinel above every threshold.
    """
    if not text:
        return None
    t = str(text).strip().lower()
    if re.search(r"tntc|too\s+numerous|innumerable|uncountable|numerous", t):
        return 999
    if re.search(r"\bnil\b|\bnone\b|\babsent\b|لا\s*يوجد", t):
        return 0
    nums = re.findall(r"[\d]+", t)
    if not nums:
        return None
    return max(int(n) for n in nums)
