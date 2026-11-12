"""Rules driven by the inferred beta-lactam resistance mechanism.

One table, applied uniformly to EVERY beta-lactam family (the old code had
separate, differently-ordered branches for cefepime, for "penicillins and
cephalosporins", and for "BLI combinations" - and the last was unreachable):

  policy          drug                          urine            elsewhere
  ─────────────   ───────────────────────────   ──────────────   ─────────
  esbl            carbapenem                    allowed          allowed
  esbl            any other beta-lactam, S/I    warn (cystitis   AVOID
                                                 only)
  ampc            carbapenem / cefepime         allowed          allowed
  ampc            any other beta-lactam, S/I    warn             AVOID
  cre             any beta-lactam               AVOID            AVOID
                  (aztreonam: warn)
  cre_possible    carbapenem, S/I               warn (confirm)   warn (confirm)
  cre_possible    any other beta-lactam, S/I    warn             AVOID

Sources: IDSA Guidance on the Treatment of Antimicrobial-Resistant
Gram-Negative Infections (2024); MERINO trial (2018); EUCAST v16
(report as tested - an S result is never edited to R, it is annotated).
"""
from __future__ import annotations

from typing import Optional

from .. import drugs as D
from .context import Context, DrugCase
from .findings import Finding, ban, tag, warn

_NAMES = {"esbl": "ESBL", "ampc": "AmpC", "cre": "Carbapenemase",
          "cre_possible": "ESBL/AmpC + porin loss or carbapenemase"}
_SHORT = {"esbl": "ESBL", "ampc": "AmpC", "cre": "CRE", "cre_possible": "Possible CRE"}


def _uti_only_warning(mech: str, short: str) -> Finding:
    ar = (f"كائن {mech}: هذا البيتا-لاكتام حسّاس معملياً — "
          "يُبلَّغ **كما هو** (EUCAST v16؛ لا تُحوّل الحساس إلى R). ليس خياراً "
          "مفضّلاً: يُنظر فيه لعدوى المسالك البولية البسيطة (التهاب المثانة) فقط "
          "عند ثبوت الحساسية وغياب البديل (يُفضَّل Nitrofurantoin/TMP-SMX، "
          "و Fosfomycin لـ E. coli). تجنّبه في تجرثم الدم أو التهاب الكلية "
          "الصاعد — Carbapenem أولاً (IDSA AMR 2024 / MERINO).")
    en = (f"{mech} organism: this beta-lactam is susceptible in vitro — "
          "report it AS TESTED (EUCAST v16; do not edit S to R). It is not a "
          "preferred agent: consider it for uncomplicated cystitis only, when "
          "proven S and no preferred option exists (prefer "
          "Nitrofurantoin/TMP-SMX; Fosfomycin for E. coli). Avoid in bacteremia "
          "or pyelonephritis — Carbapenem is first-line (IDSA AMR 2024 / MERINO).")
    return warn("esbl_bli_uti_only", ar, en,
                f"{short}: يُبلَّغ كما هو — لالتهاب المثانة البسيط فقط؛ ليس لتجرثم الدم/التهاب الكلية.",
                f"{short}: as tested — uncomplicated cystitis only; NOT for bacteremia/pyelonephritis.",
                esbl_note=ar, esbl_note_en=en)


def _systemic_ban(mech: str, carbapenemase: bool) -> Finding:
    alt = "Colistin / Ceftazidime-Avibactam" if carbapenemase else "Carbapenem (Meropenem/Ertapenem)"
    return ban(
        "mechanism_beta_lactam", "organism",
        f"غير مُوصى به — كائن منتج لـ {mech}.",
        f"الكائن منتج لـ {mech}. الحساسية المعملية تُبلَّغ كما هي، لكن "
        "لا يُنصح بهذا البيتا-لاكتام في العدوى الجهازية بـ ESBL/AmpC "
        "(أو مع Carbapenemase) حتى لو أظهرت المزرعة حساسية — تأثير اللقاح "
        f"(inoculum effect) في العينات غير البولية. الخيار العلاجي = {alt}.",
        f"Not recommended — {mech}-producing organism.",
        f"This organism produces {mech}. In-vitro susceptibility is "
        "reported as tested, but this beta-lactam is not recommended for "
        "systemic ESBL/AmpC (or carbapenemase) infection even if the culture "
        "reports susceptible (inoculum effect in non-urine specimens). "
        f"Treatment of choice = {alt}.",
    )


def rule_mechanism(ctx: Context, d: DrugCase) -> Optional[Finding]:
    policy = ctx.policy
    if not policy or d.family not in D.BETA_LACTAM_FAMILIES:
        return None
    mech = _NAMES[policy]
    carbapenem = d.family == D.CARBAPENEM
    urine = ctx.specimen == "urine"

    if policy == "cre":
        if carbapenem:
            return ban(
                "carbapenemase_carbapenem", "organism",
                "غير فعّال — كائن منتج لـ Carbapenemase.",
                "الكائن منتج لإنزيم Carbapenemase (KPC/MBL/OXA): مقاوم للكاربابينيمات. "
                "استخدم Colistin أو Ceftazidime-Avibactam (± Aztreonam لـ MBL) حسب الحساسية.",
                "Not effective — carbapenemase-producing organism.",
                "This organism produces a carbapenemase (KPC/MBL/OXA) and is resistant "
                "to carbapenems. Use Colistin or Ceftazidime-Avibactam (+/- Aztreonam "
                "for MBL) according to susceptibility.",
            )
        if d.family == D.MONOBACTAM:
            ar = ("كائن مقاوم للكاربابينيم: Aztreonam ثابت أمام إنزيمات MBL فقط، "
                  "ويتحلل بـ ESBL/AmpC/KPC المصاحبة غالباً. لا يُستخدم منفرداً — "
                  "فقط مع Ceftazidime-Avibactam وباستشارة أمراض معدية.")
            en = ("Carbapenem-resistant organism: Aztreonam is stable only to "
                  "MBLs and is hydrolysed by the ESBL/AmpC/KPC enzymes that "
                  "usually accompany them. Do not use alone — only with "
                  "Ceftazidime-Avibactam on infectious-diseases advice.")
            return warn("cre_aztreonam", ar, en,
                        "CRE: لا يُستخدم منفرداً — فقط مع Ceftazidime-Avibactam وباستشارة أمراض معدية.",
                        "CRE: not alone — only with ceftazidime-avibactam on ID advice.",
                        esbl_note=ar, esbl_note_en=en)
        return _systemic_ban(mech, carbapenemase=True)

    if policy == "cre_possible" and carbapenem:
        # R carbapenems never reach this rule (rule_resistant is terminal).
        ar = ("مقاومة Ertapenem فقط أو نتيجة I لكاربابينيم: النمط لا يثبت "
              "Carbapenemase (الأشيع ESBL/AmpC + فقد بورين). هذا الكاربابينيم "
              "حسّاس ويُبلَّغ كما هو — أكّد غياب الكاربابينيميز (mCIM/PCR) "
              "واستخدمه بتسريب مُطوّل للعدوى خارج المثانة (IDSA AMR 2024).")
        en = ("Ertapenem-only resistance, or a carbapenem reading I: this "
              "pattern does not establish a carbapenemase (ESBL/AmpC plus "
              "porin loss is commoner). This carbapenem tests susceptible and "
              "is reported as tested — confirm that no carbapenemase is "
              "present (mCIM/PCR) and give it by extended infusion for "
              "infections outside the bladder (IDSA AMR 2024).")
        return warn("carbapenem_confirm", ar, en,
                    "اشتباه CRE: أكّد غياب الكاربابينيميز (mCIM/PCR) واستخدمه بتسريب مُطوّل.",
                    "Possible CRE: confirm no carbapenemase (mCIM/PCR); give by extended infusion.",
                    esbl_note=ar, esbl_note_en=en)

    if carbapenem:
        return None                      # esbl / ampc: carbapenems are the answer

    if policy == "ampc" and d.name == "Cefepime":
        return tag(
            "ampc_cefepime",
            "كائن AmpC: Cefepime (حسّاس) هو الخيار المقترح (IDSA AMR 2024).",
            "AmpC organism: Cefepime (susceptible) is the suggested agent (IDSA AMR 2024).",
        )

    if urine:
        return _uti_only_warning(mech, _SHORT[policy])
    return _systemic_ban(mech, carbapenemase=False)


def rule_ampc_inducible_third_gen(ctx: Context, d: DrugCase) -> Optional[Finding]:
    """E. cloacae complex / K. aerogenes / C. freundii that still test S to a
    3rd-generation cephalosporin can derepress AmpC ON therapy."""
    if not (ctx.organism.is_("ampc_high_risk") and ctx.policy is None
            and d.name in D.THIRD_GEN_CEPHALOSPORINS and d.sir in ("S", "I")):
        return None
    ar = ("كائن عالي الخطورة لتحريض AmpC (E. cloacae complex / K. aerogenes / "
          "C. freundii): سيفالوسبورين الجيل الثالث قد يُظهر حساسية ثم تنشأ "
          "المقاومة أثناء العلاج. يُقبل لالتهاب المثانة البسيط فقط؛ للعدوى "
          "الأشد يُقترح Cefepime (أو Carbapenem) — IDSA AMR 2024.")
    en = ("Organism at high risk of AmpC induction (E. cloacae complex / "
          "K. aerogenes / C. freundii): a 3rd-generation cephalosporin can "
          "test susceptible and resistance then emerge on therapy. Acceptable "
          "for uncomplicated cystitis only; for anything more serious Cefepime "
          "(or a carbapenem) is suggested — IDSA AMR 2024.")
    return warn("ampc_inducible", ar, en,
                "خطر AmpC: قد تنشأ مقاومة أثناء العلاج — للمثانة البسيطة فقط؛ فضّل Cefepime.",
                "AmpC risk: resistance can emerge on therapy — cystitis only; prefer cefepime.",
                esbl_note=ar, esbl_note_en=en)
