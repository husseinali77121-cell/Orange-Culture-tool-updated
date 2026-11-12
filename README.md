# Orange Lab — Microbiology CDSS (v2.0)

برنامج دعم القرار لمزارع الميكروبيولوجي: استخراج تقرير المزرعة (OCR)، فحص جودة
الـ AST، وتصنيف المضادات إلى موصى به / بحذر / ممنوع حسب الكائن والعينة والمريض.

> **للتشغيل:** `streamlit run orange_lab-41.py`
> **سجل التغييرات في هذه النسخة:** [`CHANGES_v2.md`](CHANGES_v2.md)

## البنية

```
orange_lab-41.py        واجهة Streamlit (عرض فقط — لا منطق إكلينيكي)
reports.py              تقارير PDF / نص / صورة
ocr_extract.py          استخراج البيانات من صورة التقرير
clinical_engines.py     واجهة موحّدة (facade) تعيد تصدير دوال cdss — لا منطق فيها

cdss/                   ← المنطق الإكلينيكي كله، بدون أي اعتماد على Streamlit
  sir.py                توحيد نتائج S / I / R عند المدخل
  organisms.py          محلِّل واحد لهوية الكائن ومجموعاته والمقاومة الجوهرية
  drugs.py              تصنيف صريح لكل دواء (العائلة، بيتا-لاكتام؟ بولي فقط؟)
  specimens.py          مصنِّف واحد للعينات
  renal.py              تصفية الكرياتينين
  mechanisms.py         ESBL / AmpC / مقاومة الكاربابينيم
  mdr.py                MDR / XDR / PDR (Magiorakos 2012)
  phenotypes.py         MRSA / VRE / CRE / CRAB / CRPA
  disposition/          تصنيف كل دواء
    context.py            حقائق الحالة — تُحسب مرة واحدة
    findings.py           نوع "النتيجة" وترتيب الشدة
    rules_result.py       قواعد نتيجة الدواء نفسه (R / I / غير مُختبَر)
    rules_organism.py     قواعد الكائن (جوهرية، MRSA، D-test، ...)
    rules_mechanism.py    قواعد آلية المقاومة (جدول واحد لكل البيتا-لاكتام)
    rules_patient.py      العمر / الكلى / الحمل
    rules_specimen.py     الأدوية البولية فقط
    alerts.py             التنبيهات النصية (تداخلات، كبد)
    engine.py             يشغّل كل القواعد ويختار بالشدّة
  duration.py  severity.py  stewardship.py  syndromes.py
  pathogenicity.py  qc.py  ranking.py  regimen_notes.py

clinical_data.py        الجداول (المقاومة الجوهرية، مدد العلاج، ...)
abx_guidelines.py       بيانات المضادات (50 دواء)
organism_profile.py     بيانات الكائنات (22 كائن)
ast_reportability.py    قواعد ما لا يصحّ تبليغه (جوهري / بلا breakpoints)
ast_consistency.py      تناقضات النتائج داخل اللوحة
ast_qa_engine.py        محرك QA التفصيلي
guideline_registry.py   كل قاعدة ← مصدرها المؤرَّخ وحالة التحقق

tests/                  اختبارات pytest — ملف لكل مجموعة وحدات
test_*.py (الجذر)        الحُرّاس الخمسة الأصليون (جداول، OCR، سيناريوهات، مراجع)
```

## القاعدة الأساسية في التصميم

كل دواء تُطبَّق عليه **كل** القواعد، والنتيجة الأشدّ هي التي تحدد قائمته
(ممنوع > قرار طبيب في الحمل > بحذر > موصى به). ترتيب كتابة القواعد لا يغيّر
النتيجة — وهذا مُختبَر (`test_outcome_does_not_depend_on_rule_order`).

لإضافة قاعدة جديدة: دالة صغيرة في ملف `rules_*.py` المناسب ترجّع `Finding` أو
`None`، تُضاف لقائمة `RULES` في `engine.py`، ويُكتب لها اختبار في
`tests/test_disposition.py`، وصف في `guideline_registry.py`.

لإضافة دواء جديد: صف في `abx_guidelines.py` **و** صف في
`cdss/drugs.py: DRUG_FAMILY` (الاختبارات تفشل لو نسيت الثاني).

## الاختبارات

```bash
pip install -r requirements-dev.txt
python -m pytest -q tests            # 230 اختبار — ثوانٍ
python test_intrinsic_invariant.py   # تطابق الجداول
python test_intrinsic_sync.py        # OCR + الآليات
python test_comprehensive.py         # 8000 حالة عشوائية
python test_scenarios.py             # 277 سيناريو × 13 invariant
python test_guidelines.py            # تتبّع المراجع
python guideline_registry.py --queue # القواعد المنتظِرة مراجعة إكلينيكية
```

الـ CI (`.github/workflows/cdss-tests.yml`) يشغّلها كلها على كل push.

## تنبيه

أداة دعم قرار — القرار العلاجي مسؤولية الطبيب المعالج. القواعد الجديدة في v2.0
مُسجَّلة كـ `pending` في `guideline_registry.py` حتى يراجعها طبيب على المصدر.

ملف الثيم: [`docs/THEME.md`](docs/THEME.md).
