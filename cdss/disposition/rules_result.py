"""Rules driven by the drug's own S / I / R result."""
from __future__ import annotations

from typing import Optional

from .context import Context, DrugCase
from .findings import Finding, ban, tag, warn


def rule_resistant(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """R is final. Intrinsic and acquired resistance are both "R" but mean
    different things to the reader - Tetracycline-R is a finding about THIS
    isolate, Clindamycin-R is true of every E. coli - so they are tagged apart."""
    if d.sir != "R":
        return None
    org = ctx.organism_name
    if d.name in ctx.reportability_intrinsic:
        return ban(
            "intrinsic_resistant", "intrinsic",
            "مقاومة جوهرية — ليست نتيجة مزرعة.",
            f"{org} مقاوم لـ {d.name} بطبيعته، وليس باكتساب آلية "
            f"مقاومة. لم يكن خياراً علاجياً في أي وقت، ولا يُفترض وجوده "
            f"على اللوحة أصلاً.",
            "Intrinsic resistance — not a culture finding.",
            f"{org} is naturally resistant to {d.name}; this is not "
            f"an acquired mechanism. It was never a treatment option, and "
            f"should not have been on the panel in the first place.",
            terminal=True, sir_note="intrinsic",
            intrinsic_reason=ctx.reportability_intrinsic[d.name],
        )
    return ban(
        "resistant", "resistant", "مقاوم (R) في نتيجة المزرعة.",
        f"المزرعة أثبتت أن {d.name} لا يثبط نمو الجرثومة. MIC أعلى من الحد العلاجي → خطر فشل علاجي.",
        "Resistant (R) on culture.",
        f"The culture showed that {d.name} does not inhibit growth of this "
        f"organism. MIC above the therapeutic threshold → risk of treatment failure.",
        terminal=True,
    )


def rule_not_tested(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """A drug with no S/I/R result must never be presented as an option.
    (It used to be listed as allowed and labelled "S".)"""
    if d.sir is not None:
        return None
    return warn(
        "not_tested",
        "لم يُختبر في هذه المزرعة — لا يُعتمد عليه دون نتيجة حساسية.",
        "Not tested on this isolate — do not rely on it without a susceptibility result.",
        "لم يُختبر — لا يُستخدم دون نتيجة حساسية.",
        "Not tested — do not use without a result.",
        sir_category="NT",
    )


def rule_intermediate(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """"I" means opposite things in the two standards.

    EUCAST (2019+): "Susceptible, increased exposure" - an appropriate option
    PROVIDED the high-dose / prolonged-infusion regimen is used -> stays
    allowed, carrying the regimen note.
    CLSI: Intermediate - efficacy uncertain -> warned.
    """
    if d.sir != "I":
        return None
    if ctx.interp_std == "EUCAST":
        return tag(
            "increased_exposure",
            "حسّاس بزيادة التعرّض — يتطلب نظام الجرعة الأعلى "
            "أو التسريب المُطوّل، وليس الجرعة القياسية.",
            "Susceptible, increased exposure — requires the "
            "high-dose / prolonged-infusion regimen, NOT the standard dose.",
            sir_note="increased_exposure",
            sir_note_ar=("حسّاس بزيادة التعرّض — يتطلب نظام الجرعة الأعلى "
                         "أو التسريب المُطوّل، وليس الجرعة القياسية."),
            sir_note_en=("Susceptible, increased exposure — requires the "
                         "high-dose / prolonged-infusion regimen, NOT the "
                         "standard dose."),
        )
    ar = ("Intermediate (CLSI) — استخدم بحذر. معدّل "
          "الاستجابة قد يكون أقل من الحسّاس. قد يكون "
          "فعّالاً في المواقع التي يتركّز فيها الدواء "
          "(مثل البول) أو بجرعة أعلى من المعتادة. "
          "يُفضَّل بديل حسّاس إن وُجد.")
    en = ("Intermediate (CLSI) — use with caution. Response "
          "rates may be lower than for susceptible isolates. "
          "May be effective at body sites where the drug is "
          "concentrated (e.g. urine) or when a higher than "
          "normal dose can be used. Prefer a susceptible "
          "alternative where one exists.")
    return warn("intermediate_culture", ar, en,
                "Intermediate (CLSI) — استخدم بحذر؛ يُفضَّل بديل حسّاس.",
                "Intermediate (CLSI) — use with caution; prefer a susceptible alternative.",
                sir_note="use_with_caution",
                sir_note_ar=ar, sir_note_en=en)
