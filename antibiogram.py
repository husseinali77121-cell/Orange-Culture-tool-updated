# Antibiogram Engine — Orange Lab Microbiology CDSS
# Builds a cumulative antibiogram (%S per organism × antibiotic) from the
# isolate registry, following CLSI M39 guardrails:
#   • First isolate per patient per organism (repeats do NOT inflate resistance)
#   • Report an organism only when it has >= min_isolates (default 30)
#   • Hide/flag drug cells tested on < min_isolates (small-n is unreliable)
#
# compute_antibiogram() is pure and unit-tested. Rendering functions use
# Streamlit and are imported by orange_lab.py.

import io
import csv
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import streamlit as st

from isolate_registry import IsolateRegistry

logger = logging.getLogger("orange_lab.antibiogram")

MIN_ISOLATES_DEFAULT = 30
_VALID_SIR = {"S", "I", "R"}


def _parse_date(s: str):
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(s)[:len(fmt) + 2], fmt)
        except Exception:
            continue
    return datetime.min


def first_isolates(isolates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Keep the FIRST isolate per (patient, organism) across the whole dataset
    (CLSI M39 first-isolate rule). Order is by date_in then created_at.
    """
    ordered = sorted(
        isolates,
        key=lambda r: (_parse_date(r.get("date_in") or r.get("created_at") or ""),
                       str(r.get("created_at", ""))),
    )
    seen = set()
    kept = []
    for rec in ordered:
        key = (IsolateRegistry.patient_key(rec), (rec.get("organism") or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(rec)
    return kept


def compute_antibiogram(
    isolates: List[Dict[str, Any]],
    min_isolates: int = MIN_ISOLATES_DEFAULT,
    include_low_n: bool = False,
) -> Dict[str, Any]:
    """
    Returns:
    {
      "organisms": {
         "Escherichia coli": {
            "n": 42,
            "drugs": { "Nitrofurantoin": {"pct_s": 88, "n": 40, "low_n": False}, ... }
         }, ...
      },
      "excluded": { "Proteus mirabilis": 11, ... },   # organism -> isolate count (< min)
      "total_isolates": 120,
      "total_first_isolates": 95,
      "min_isolates": 30,
    }
    """
    firsts = first_isolates(isolates)

    by_org: Dict[str, List[Dict[str, Any]]] = {}
    for rec in firsts:
        org = (rec.get("organism") or "").strip()
        if not org:
            continue
        by_org.setdefault(org, []).append(rec)

    organisms: Dict[str, Any] = {}
    excluded: Dict[str, int] = {}

    for org, recs in by_org.items():
        n_org = len(recs)
        if n_org < min_isolates:
            excluded[org] = n_org
            continue

        # tally per drug
        counts: Dict[str, Dict[str, int]] = {}
        for rec in recs:
            sir = rec.get("sir") or {}
            for drug, val in sir.items():
                v = str(val).strip().upper()
                if v not in _VALID_SIR:
                    continue
                c = counts.setdefault(drug, {"S": 0, "tested": 0})
                c["tested"] += 1
                if v == "S":
                    c["S"] += 1

        drugs: Dict[str, Any] = {}
        for drug, c in counts.items():
            tested = c["tested"]
            if tested == 0:
                continue
            low_n = tested < min_isolates
            if low_n and not include_low_n:
                continue
            drugs[drug] = {
                "pct_s": round(100 * c["S"] / tested),
                "n": tested,
                "low_n": low_n,
            }

        organisms[org] = {
            "n": n_org,
            "drugs": dict(sorted(drugs.items(), key=lambda kv: kv[1]["pct_s"], reverse=True)),
        }

    return {
        "organisms": dict(sorted(organisms.items(), key=lambda kv: kv[1]["n"], reverse=True)),
        "excluded": dict(sorted(excluded.items(), key=lambda kv: kv[1], reverse=True)),
        "total_isolates": len(isolates),
        "total_first_isolates": len(firsts),
        "min_isolates": min_isolates,
    }


def _antibiogram_csv(result: Dict[str, Any]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Organism", "Isolates (n)", "Antibiotic", "%S", "Tested (n)"])
    for org, data in result["organisms"].items():
        for drug, cell in data["drugs"].items():
            w.writerow([org, data["n"], drug, cell["pct_s"], cell["n"]])
    return buf.getvalue().encode("utf-8-sig")


# ─────────────────────────────────────────────────────────────────────────
# Streamlit rendering
# ─────────────────────────────────────────────────────────────────────────
def render_antibiogram_page(registry: IsolateRegistry) -> None:
    st.title("📊 Local Antibiogram")
    st.caption("خريطة الحساسية التراكمية لمعملك — CLSI M39")

    isolates = registry.list_isolates()
    total = len(isolates)

    if total == 0:
        st.info("لسه مفيش عزلات محفوظة. حلّل مزرعة واضغط **💾 احفظ في السجل** عشان تبدأ.")
        return

    min_n = st.slider(
        "أقل عدد عزلات لعرض النسبة (CLSI M39 = 30)",
        min_value=5, max_value=50, value=MIN_ISOLATES_DEFAULT, step=5,
        help="النسب المبنية على عيّنة أصغر غير موثوقة — لذلك تُخفى.",
    )
    show_low = st.checkbox("اعرض النسب قليلة العدد (n صغير) مع تنبيه", value=False)

    result = compute_antibiogram(isolates, min_isolates=min_n, include_low_n=show_low)

    c1, c2, c3 = st.columns(3)
    c1.metric("إجمالي العزلات", result["total_isolates"])
    c2.metric("عزلات أولى (بعد التنقية)", result["total_first_isolates"])
    c3.metric("ميكروبات مؤهلة", len(result["organisms"]))

    st.caption(
        "«عزلات أولى» = أول عزلة لكل مريض لكل ميكروب (منع تضخيم المقاومة). "
        "الميكروب لازم يوصل للحد الأدنى قبل ما يظهر."
    )

    if not result["organisms"]:
        st.warning(
            f"مفيش أي ميكروب وصل لـ **{min_n} عزلة** لسه. "
            "كمّل حفظ الحالات، أو نزّل الحد الأدنى مؤقتًا للاستطلاع (مش للتقارير الرسمية)."
        )
    else:
        for org, data in result["organisms"].items():
            with st.expander(f"🦠 {org}  —  n = {data['n']}", expanded=True):
                if not data["drugs"]:
                    st.caption("مفيش مضاد اتفحص على عدد كافٍ من العزلات.")
                    continue
                rows = []
                for drug, cell in data["drugs"].items():
                    flag = "  ⚠️ n صغير" if cell.get("low_n") else ""
                    rows.append({
                        "Antibiotic": drug,
                        "%S": cell["pct_s"],
                        "Tested (n)": cell["n"],
                        "": flag.strip(),
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)

        st.download_button(
            "⬇️ تحميل الأنتيبيوجرام (CSV)",
            data=_antibiogram_csv(result),
            file_name=f"antibiogram_{datetime.now():%Y%m%d}.csv",
            mime="text/csv",
        )

    if result["excluded"]:
        with st.expander(f"🔎 ميكروبات تحت الحد الأدنى ({len(result['excluded'])})", expanded=False):
            st.caption("لسه معندهاش عزلات كفاية — بتظهر هنا للمتابعة بس، من غير نسب.")
            st.dataframe(
                [{"Organism": k, "Isolates (n)": v} for k, v in result["excluded"].items()],
                use_container_width=True, hide_index=True,
            )

    st.divider()
    st.caption(
        "⚠️ الأنتيبيوجرام ملخّص وبائي تراكمي، مش بديل عن نتيجة مزرعة فردية. "
        "لا يُستخدم للقرار العلاجي للمريض الواحد بمعزل عن حالته."
    )


def render_registry_page(registry: IsolateRegistry) -> None:
    st.title("📇 سجل العزلات")
    isolates = registry.list_isolates()
    st.metric("العزلات المحفوظة", len(isolates))

    if not isolates:
        st.info("لسه فاضي. بعد تحليل أي مزرعة اضغط **💾 احفظ في السجل**.")
        return

    q = st.text_input("🔎 بحث (اسم / كود / موبايل / ميكروب)", "").strip().lower()

    def _match(rec):
        if not q:
            return True
        blob = " ".join(str(rec.get(k, "")) for k in
                        ("patient_name", "lab_id", "mobile", "organism", "specimen")).lower()
        return q in blob

    shown = [r for r in isolates if _match(rec=r)]
    st.caption(f"يعرض {len(shown)} من {len(isolates)}")

    for rec in shown[:200]:
        title = f"{rec.get('date_in','')} · {rec.get('organism','?')} · {rec.get('specimen','?')}"
        with st.expander(title):
            meta = {
                "التاريخ": rec.get("date_in", ""),
                "الفرع": rec.get("branch", ""),
                "كود المعمل": rec.get("lab_id", ""),
                "الاسم": rec.get("patient_name", ""),
                "الموبايل": rec.get("mobile", ""),
                "السن": rec.get("age", ""),
                "النوع": rec.get("sex", ""),
                "العينة": rec.get("specimen", ""),
                "الميكروب": rec.get("organism", ""),
                "الآلية": rec.get("mechanism", "") or "—",
            }
            st.write({k: v for k, v in meta.items() if v not in ("", None)})
            sir = rec.get("sir") or {}
            if sir:
                st.dataframe(
                    [{"Antibiotic": d, "Result": v} for d, v in sir.items()],
                    use_container_width=True, hide_index=True,
                )
            if st.button("🗑️ حذف (soft delete)", key=f"del_{rec['id']}"):
                registry.soft_delete(rec["id"])
                st.warning("اتحذفت. لتثبيت الحذف على GitHub اضغط **مزامنة** بالأسفل.")
                st.rerun()
