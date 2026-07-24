# Orange Lab Microbiology CDSS — سجل المراجعة والتثبيت
### Audit & Hardening Log — commercial build (`streamlit_app.py`)

**تاريخ المراجعة:** 2026-07-22 · **الإصدار المرجعي:** EUCAST v16.0/16.1 · CLSI M100 Ed36 · IDSA AMR v4.0 (2024) · WHO AWaRe 2025 · WHO BPPL 2024

**الحجم:** 7 ملفات جديدة · 15 ملف معدّل · 1,024 سطر متغيّر

---

## ١. أخطاء تؤثر على المريض مباشرة (Patient-safety defects)

دي الأخطاء اللي كانت ممكن تغيّر قرار علاجي. كل واحدة موثّقة بمصدرها.

### 1.1 — Doxycycline كان بيتعرض كخيار فعّال لـ Acinetobacter ⛔
- **الحالة:** جدول الـ intrinsic مكانش فيه أي تتراسيكلين لـ Acinetobacter.
- **المصدر:** EUCAST v3.3 Table 2 fn.2 — *"Acinetobacter is intrinsically resistant to tetracycline and doxycycline but not to minocycline and tigecycline."*
- **الأثر:** توجيه لعلاج فاشل — أخطر من منع دوا شغّال.
- **الإصلاح:** Tetracycline + Doxycycline → IR. إضافة **Minocycline** للقائمة (مكانش موجود أصلاً، وهو الدوا الوحيد اللي بيشتغل).

### 1.2 — Cephalosporins كانت بتتشال من عزلات CRPA حسّاسة ⛔
- **الحالة:** أي كائن بكاربابينيمين R كان بياخد `carbapenemase 92%`، واللي بيفعّل `_is_carbapenemase` فيبنّ كل بنسلين وسيفالوسبورين **حتى لو S**.
- **المصدر:** IDSA AMR v4.0 — العزلة المقاومة للكاربابينيم والحسّاسة لبيتا-لاكتام تقليدي تُعالَج بذلك الدوا بجرعة عالية وتسريب ممتد، مش بالكوليستين.
- **الأثر:** عزلة سودوموناس بـ Ceftazidime-S + Cefepime-S + Pip-Tazo-S كانت بتخرج بـ **Amikacin و Colistin بس**.
- **الإصلاح:** مسار `crpa` منفصل (ثقة 45–60%) + تصنيف `DTR` بتعريف IDSA. الـ Enterobacterales ما اتغيرتش.

### 1.3 — Amoxicillin-Clavulanate كان بيتفلج IR بدل Ampicillin-Sulbactam ⛔
- **الحالة:** `extract_detected_drugs` كان بيطابق بالاحتواء الخام، فكل مضاد مركّب بيولّد أدوية وهمية:
  `Ampicillin/Sulbactam` → `Ampicillin` · `Amoxicillin + Clavulanic acid` → `Amoxicillin` · `Levofloxacin` → `Ofloxacin`
- **الأثر:** الأدوية الوهمية دي intrinsic لـ Acinetobacter فبتظهر تحذيرات لأدوية **متعملهاش اختبار أصلاً**.
- **الإصلاح:** scanner سطر-بسطر، الاسم الأطول أولاً مع حجز الـ span.

### 1.4 — Tigecycline ممنوع و Tetracycline/Doxycycline معروضين لـ Serratia ⛔
- **المصدر:** EUCAST v3.3 Table 2 fn.5 — نفس صياغة حاشية Acinetobacter.
- **الحالة:** الكود كان **مقلوب تماماً**.

### 1.5 — Amox-clav معفي من قاعدة Acinetobacter
- **الحالة:** `"clav"` كانت في `exclude` — الكلافولانيت مالوش أي فاعلية هنا؛ السولباكتام هو الاستثناء الوحيد.

---

## ٢. تناقضات بين المحركات (Engine disagreements)

### 2.1 — `ast_qa_engine` كان **ميت** بالكامل للسالب جرام
- بيعمل `from clinical_data import INTRINSIC_RESISTANCE` وملف `clinical_data.py` **مش موجود في الريبو**. الـ `except` بيرجّعه `{}` → فحص Level-1 معطّل لكل الـ Gram-negatives، وبيفحص MRSA و Mycoplasma بس.
- **الإصلاح:** إنشاء `clinical_data.py` كمصدر وحيد + `Guard 0` بيفشل الـ build لو الملف ناقص.

### 2.2 — الجداول الثلاثة كانت مختلفة
`streamlit_app` · `ast_reportability` · `ast_qa_engine` — كل واحد بجدول مختلف. اتوحّدوا، و`test_intrinsic_sync.py` بيفشل لو رجعوا يختلفوا.

### 2.3 — تكرار مرئي في الشاشة
البانلين بيعرضوا نفس النتيجة. `skip_categories` بيمنع التكرار.

### 2.4 — `not_organisms` كانت **بلا أي مفعول**
الـ evaluator في `AST_QC_RULES` مكانش بيقراها خالص — أي استثناء تكتبه كان بيتجاهَل. اتوصّلت، و QC003 بقى بيستثني الكائنات المقاومة جوهرياً للكوليستين.

---

## ٣. قواعد ناقصة تماماً (Missing rules)

| القاعدة | المصدر | الحالة قبل |
|---|---|---|
| `nobp_imipenem_proteae` | EUCAST v16.0 note 2 | مفيش — `Imipenem S` على Proteus كان بيعدّي |
| `intr_strep_enterococcus_aminoglycosides` | EUCAST Table 4 + CLSI HLAR | مفيش — `Gentamicin S` على Enterococcus كان بيعدّي |
| `intr_citrobacter_koseri_klebsiella_oxytoca_classA` | EUCAST v3.3 Table 2 | *C. koseri* مكانش عليه أي قاعدة |
| `intr_nonfermenter_narrow_spectrum` | EUCAST v3.3 Table 3 header | كانت "no breakpoints" الأضعف |
| Serratia في `nobp_tigecycline_proteae` | EUCAST v16.0 note 3/A | ناقصة |

---

## ٤. أخطاء برمجية (Code defects)

- `data/antibiotics.py` — `re.sub` بدون `import re` → NameError
- `modules/qc.py` — `AST_QC_RULES` غير معرّف → NameError
- `fuzzy_match` بيرجّع 100.0 لمجرد الاحتواء (لسه مفتوح)
- 132 استشهاد مبهم أو غلط اتصلّحوا (`IDSA AMR 2025` → `v4.0 (2024)` · `EUCAST 2026` → `Breakpoint Tables v16.0` · `CLSI M100 2026` → `Ed36`)

---

## ٥. البنية اللي اتبنت للتحقق

### الملفات الجديدة
| الملف | الوظيفة |
|---|---|
| `clinical_data.py` | مصدر وحيد للـ intrinsic (34 كائن) |
| `guideline_registry.py` | 36 قاعدة × مصدر مؤرَّخ + لينك + مين راجع وامتى |
| `scenario_matrix.py` | مولّد 791 سيناريو |
| `test_scenarios.py` | 13 invariant + golden snapshot |
| `test_intrinsic_sync.py` | 86 تست للجداول والـ OCR |
| `test_guidelines.py` | تتبّع الاستشهادات |
| `scenario_snapshot.json` | البصمة المرجعية |

### الـ 13 invariant
1. دوا واحد في bucket واحد · 2. intrinsic ما يوصلش Allowed · 3. R ما يتوصّاش · 4. مفيش أدوية وهمية · 5. PDR يعني مفيش S · 6. ESBL للـ Enterobacterales بس · 7. لوحة رفيعة ما تدّعيش XDR · 8. السودوموناس مش carbapenemase · 9. انتهاك intrinsic يتفلج · 10. دوا بولي برّه البول يتفلج · 11. wild-type عنده خيارات · 12–13. صياغة سليمة

---

## ٦. إزاي تتحقق إن البرنامج سليم

```bash
python test_intrinsic_invariant.py    # انحراف الجداول
python test_intrinsic_sync.py         # 86 تست
python test_scenarios.py              # 791 سيناريو
python test_guidelines.py             # تتبّع المصادر
python test_guidelines.py --queue     # اللي لسه محتاج مراجعة
N_FUZZ=20000 python test_comprehensive.py
python -m compileall -q .
```

الـ CI (`.github/workflows/cdss-tests.yml`) بيشغّل السبعة على كل push.

**لو `test_scenarios.py` قال `SNAPSHOT: N case(s) changed`:**
1. `python test_scenarios.py --verbose` واقرا الفرق
2. اسأل: التغيير ده مقصود؟
3. لو أيوة: `python test_scenarios.py --update`

⚠️ **snapshot محدش بيقراه بيبقى ديكور مش شبكة أمان.**

---

## ٧. الحالة النهائية

```
Guard 0  clinical_data موجود          ✅  34 كائن
Guard 1  انحراف الجداول                ✅
Guard 2  التزامن + OCR                ✅  86 passed
Guard 3  مصفوفة السيناريوهات           ✅  791 × 13 invariant
Guard 4  تتبّع الـ Guidelines           ✅  36 قاعدة
Guard 5  الشامل                       ✅  N=20000
Guard 6  compileall                   ✅
fuzz                                  ✅  8000 حالة، صفر أخطاء
```

**تتبّع القواعد:** 20 من نص المصدر · 11 من مصدر ثانوي · **5 لسه غير متحقَّق منها**

---

## ٨. اللي لسه مفتوح

### ٨.١ — 5 قواعد غير متحقَّق منها
| القاعدة | ليه |
|---|---|
| `QC003` / `QC004` | heuristics معقولة، مش قواعد منشورة |
| `QC005` | CLSI Table 2C وراء paywall |
| `nobp_cefoperazone` | إثبات **غياب** — غياب الدليل مش دليل الغياب |
| `nobp_nonfermenter_narrow_spectrum` | الجزء المؤكد اتنقل لقاعدة intrinsic؛ الباقي لأ |

### ٨.٢ — قاعدة محتاجة الـ PDF الأصلي
`intr_listeria_cephalosporins` — الحقيقة الإكلينيكية مش محل شك، لكن صف EUCAST 4.11 فيه علامتين R ومحاذاة الأعمدة مش واضحة من النص المسطّح.

### ٨.٣ — **31 قاعدة مستنية توقيع إكلينيكي**
`countersigned_by` فاضي في كل الصفوف. المراجعة اتعملت بمساعدة AI من مصادر منشورة — **مش نفس حاجة طبيب بيقرا المعيار ويتحمّل المسؤولية.**

### ٨.٤ — أخطاء معروفة لم تُصلَح
- `fuzzy_match` بيرجّع 100.0 للاحتواء → عتبة 82 بلا معنى
- الـ multiselect اليدوي مش بيمرّ على `_hide_urine_only`
- `modules/` + `data/` + `ui/` شجرة ميتة — الأب مش بيستوردها (يُفضَّل حذفها)

### ٨.٥ — قرارات مؤجلة
- **OCR:** `image_to_string` بيرمي معلومات الموقع → التقارير المجمّعة (Sensitive/Resistant كأعمدة) بتطلّع `sir_map` **فاضي**. الحل: `image_to_data` + ترسية على العناوين + شاشة تأكيد إجبارية.
- **P. aeruginosa wild-type** المفروض يتقرا `I` مش `S` حسب EUCAST 2019+
- **أدوية جديدة** (Cefiderocol · Sulbactam-durlobactam · Ceftazidime-avibactam) — مش متاحة عملياً في مصر
- **XDR/PDR** المفروض يتحجبوا لو لوحة Magiorakos الدنيا مش متختبرة

---

## ٩. ملاحظة على منهج المراجعة

النظام ده بيقدر يثبت إن **الكود مطابق للجداول**. مش بيقدر يثبت إن **الجداول مطابقة لـ EUCAST v16** — دي محتاجة إنسان يفتح الـ PDF.

`guideline_registry.py` بيخلّي المراجعة دي **منظّمة وموثّقة وقابلة للانتهاء** (18 شهر) — بس مش بيلغيها.
