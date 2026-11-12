"""Strict lexicographic ranking of the allowed antibiotics."""
from __future__ import annotations

from typing import Dict, List

from clinical_data import RANKING_WEIGHTS

from .sir import normalize_sir_map

def rank_sensitive_antibiotics(
    allowed:      List[Dict],
    culture_type: str,
    organism:     str,
    sir_map:      Dict[str, str],
    phenotypes:   List[Dict],
) -> List[Dict]:
    """
    يرتب الأدوية المسموحة بترتيب هرمي صارم (lexicographic) — كل معيار يكسر
    التعادل في المعيار الأهم منه فقط، فلا يتغلب معيار أدنى على أعلى:

      1. نتيجة المزرعة   : S قبل I  (بوابة صارمة — لا يتخطى I دواءً S أبداً)
      2. ملاءمة العينة   : دواء له specimen_note للعينة الحالية أولاً
      3. WHO AWaRe       : Access > Watch > Reserve
      4. طريق الإعطاء     : Oral قبل IV/IM
      5. Priority        : أولوية الـ guidelines (أقل = أفضل)
      6. الاسم           : لضمان ترتيب ثابت (deterministic)

    ملاحظة تصميمية: جمع النقاط كان يسمح لدواء Intermediate ذي AWaRe/route جيد
    أن يتفوق على دواء Sensitive — وهذا خطأ إكلينيكي (الفعالية المخبرية تسبق كل
    شيء). يُحتفظ بـ _score كقيمة عرض تقريبية فقط، لا للترتيب.
    """
    sir_map = normalize_sir_map(sir_map)
    ph_names = [p.get("phenotype", "") for p in (phenotypes or [])]
    _sir_rank   = {"S": 0, "I": 1}
    _aware_rank = {"Access": 0, "Watch": 1, "Reserve": 2}

    def sort_key(item):
        name = item.get("name", "")
        sir  = sir_map.get(name)
        k_sir = _sir_rank.get(sir, 2)                       # S=0, I=1, unknown=2
        k_spec = 0 if (item.get("specimen_notes") or {}).get(culture_type) else 1
        aware = item.get("aware")
        k_aware = _aware_rank.get(aware, 3)
        if any(ph in ph_names for ph in ["CRE", "CRAB", "CRPA"]):
            cls = item.get("class", "").lower()
            if "cephalosporin" in cls and sir != "S":
                k_aware += 5
        k_route = 0 if item.get("high_po") else 1
        k_priority = item.get("priority", 99)
        return (k_sir, k_spec, k_aware, k_route, k_priority, name)

    def _display_score(item):
        name = item.get("name", "")
        sir  = sir_map.get(name)
        s = 0
        if sir == "S": s += 4
        elif sir == "I": s += 1
        s += RANKING_WEIGHTS["aware_score"].get(item.get("aware"), 0)
        s += RANKING_WEIGHTS["route_score"]["oral" if item.get("high_po") else "iv"]
        if (item.get("specimen_notes") or {}).get(culture_type):
            s += RANKING_WEIGHTS["specimen_match"]
        s += RANKING_WEIGHTS["priority_bonus"](item.get("priority", 5))
        return s

    scored = [
        {**item, "_score": _display_score(item), "_sir": (sir_map.get(item.get("name", "")) or "—")}
        for item in (allowed or [])
    ]
    return sorted(scored, key=sort_key)
