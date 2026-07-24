# Orange Lab — Microbiology CDSS · حزمة الثيم (Modernist skin)

تطبيق شكل واجهة **Orange Lab / Modernist** على برنامج الـ Streamlit الحالي
(`orange_lab.py`) **بدون تغيير المنطق أو تدفّق البيانات** — مجرّد إعادة تنسيق بصري.

---

## المحتويات

```
.streamlit/config.toml   ← ثيم Streamlit الأساسي (ألوان + خط)
orange_theme.py          ← حاقن CSS كامل لكل عناصر الواجهة + دوال مساعدة
```

---

## التركيب — 3 خطوات

**1) انسخ الملفين إلى جذر المشروع (repo root)**

بحيث يكون المسار:
```
Orange-Culture-tool-updated/
├── .streamlit/config.toml
├── orange_theme.py
├── orange_lab.py
└── ...
```
> لو عندك مجلد `.streamlit` قديم، ادمج محتوى `config.toml` أو استبدله.

**2) فعّل الثيم داخل `orange_lab.py`**

مباشرةً **بعد** سطر `st.set_page_config(...)`، أضف:

```python
from orange_theme import inject_theme
inject_theme()
```

**3) احذف الـ `<style>` القديم**

في `orange_lab.py` يوجد بلوك `st.markdown("""<style> .app-card ... </style>""")` قديم —
احذفه، لأن `orange_theme.py` يحلّ محلّه بالكامل ويتعارض معه لو تُرك.

خلاص — شغّل `streamlit run orange_lab.py` وستظهر الواجهة بالهوية الجديدة.

---

## ماذا يُنسَّق تلقائيًا؟

يتعرّف الحاقن على عناصر Streamlit القياسية ويُعيد تنسيقها:

- **الشريط الجانبي**: لوحة داكنة (ink)، وعناصر التنقّل (radio) تتحوّل لأزرار كتلة
  مع شريط برتقالي على العنصر النشط.
- **العناوين**: خط Archivo، محاذاة يسار، خط فاصل 2px تحت عنوان الصفحة.
- **الأزرار**: حواف حادة (0 radius)، حدود 2px، الأساسي برتقالي ممتلئ، والتنزيل داكن.
- **المدخلات** (نص/رقم/تاريخ/select/textarea): مربّعة، حد رفيع، تركيز برتقالي.
- **المقاييس `st.metric`**: خلايا محدودة بشريط برتقالي علوي.
- **التبويبات `st.tabs`**: تسطير برتقالي على التبويب النشط.
- **الجداول / DataFrame**: رأس داكن بنص أبيض، تحويم برتقالي خفيف.
- **الـ expanders، التنبيهات، رفع الملفات، الفواصل**: كلها بنفس اللغة البصرية.

---

## دوال مساعدة للأجزاء المخصّصة

### شرائح S / I / R (للـ Antibiogram / AST)

بدل عرض حرف نصّي عادي، استخدم شريحة ملوّنة:

```python
from orange_theme import sir_chip

st.markdown(sir_chip(row["result"]), unsafe_allow_html=True)
# "S" → أخضر · "I" → كهرماني · "R" → أحمر
```

### أصناف CSS جاهزة داخل أي `st.markdown(..., unsafe_allow_html=True)`

| الصنف | الاستخدام |
|-------|-----------|
| `ol-card` | بطاقة بيضاء بحد + شريط برتقالي علوي |
| `ol-kicker` | عنوان صغير علوي (uppercase) |
| `orange-badge` | شارة برتقالية ممتلئة |
| `muted-text` | نص ثانوي رمادي |
| `sir-s` / `sir-i` / `sir-r` | شرائح الحساسية |

مثال بطاقة:
```python
st.markdown(
    "<div class='ol-card'>"
    "<div class='ol-kicker'>Culture Result</div>"
    "<b>E. coli</b> — <span class='sir-r'>R</span> Ceftriaxone"
    "</div>", unsafe_allow_html=True)
```

---

## تعديل الألوان

كل الألوان في أعلى `orange_theme.py` كثوابت (`ORANGE`, `INK`, `GROUND` …).
غيّر القيمة في مكان واحد وتتحدّث كل الواجهة.
لو غيّرت `ORANGE`، حدّث أيضًا `primaryColor` في `config.toml` ليتطابقا.

---

## ملاحظات

- بعض أسماء `data-testid` في Streamlit تتغيّر بين الإصدارات. لو عنصرٌ ما لم يُنسَّق
  بعد ترقية Streamlit، افتح DevTools وحدّث اسم المُحدِّد (selector) المقابل في `orange_theme.py`.
- الحاقن آمن: لا يلمس أي منطق حساب أو بيانات — CSS فقط.
- للطباعة/تقارير PDF: الأصناف نفسها تعمل داخل أي HTML تبنيه للتقرير.
