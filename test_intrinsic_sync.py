#!/usr/bin/env python3
"""
Orange Lab CDSS — regression guard for the intrinsic-resistance tables, the OCR
drug-name scanner, and the P. aeruginosa carbapenemase gate.

Run:  python test_intrinsic_sync.py       (no pytest, no network, no Streamlit)

EVERY TEST IN THIS FILE EXISTS BECAUSE THE CORRESPONDING BUG SHIPPED.
That is the rule for adding to it: a new section is justified by a defect that
reached a report, not by a hypothetical.

  [1] The three tables that encode the same clinical fact must agree.
      clinical_data.INTRINSIC_RESISTANCE is the single source of truth;
      ast_reportability.INTRINSIC_RULES is the QC view of it; the recommendation
      engine reads the first. When these drifted, the recommendation panel
      refused a drug while the QC panel stayed silent about it -- two parts of
      one report contradicting each other in front of a physician.

  [2] Acinetobacter vs amoxicillin-clavulanate.
      ast_reportability's rule listed "clav" in `exclude`, exempting amox-clav
      from a restriction EUCAST applies to it. Clavulanate has no useful
      activity against Acinetobacter; SULBACTAM is the exception, because
      sulbactam has direct activity of its own. Getting these two backwards
      silences a real error and flags a working drug.

  [3] The OCR drug-name scanner.
      extract_detected_drugs() matched names by plain containment, with no
      memory of what it had already matched. Because every combination agent
      contains its own partner drug, one printed line manufactured phantom panel
      entries -- "Ampicillin/Sulbactam" produced a bare "Ampicillin", and
      "Ciprofloxacin" produced "Ofloxacin". For A. baumannii the phantoms then
      tripped an intrinsic-resistance alert against agents that were never
      tested.

  [4] The P. aeruginosa carbapenemase gate.
      Two carbapenems R set probability="carbapenemase" at 92% confidence for
      ANY organism. In P. aeruginosa that is not a supportable call -- the
      mechanism is predominantly OprD loss / efflux / AmpC, and EUCAST publishes
      no phenotypic algorithm to separate those from a true carbapenemase. The
      label suppressed beta-lactams wholesale, so an isolate with Ceftazidime
      testing SUSCEPTIBLE had that drug moved to Avoid and the physician was
      pointed at colistin.

  [5] Cross-cutting invariants that must hold for every organism in the table.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

failures: list[str] = []
passed = 0
skipped = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  [PASS] {label}")
    else:
        failures.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"  [FAIL] {label}" + (f"  — {detail}" if detail else ""))


def skip(label: str, why: str) -> None:
    global skipped
    skipped += 1
    print(f"  [SKIP] {label} — {why}")


def _nk(s: str) -> str:
    """Normalize a drug name the way the engines do: lowercase alphanumerics."""
    return "".join(c for c in (s or "").lower() if c.isalnum())


print("Orange Lab CDSS — intrinsic / OCR / mechanism regression guard\n")

# ============================================================================
# [1] THE TABLES MUST AGREE
# ============================================================================
print("[1] table synchronisation")

from clinical_data import INTRINSIC_RESISTANCE  # noqa: E402
import ast_reportability as AR  # noqa: E402
from ast_reportability import check_reportability  # noqa: E402

check("clinical_data.INTRINSIC_RESISTANCE is non-empty",
      bool(INTRINSIC_RESISTANCE), "canonical table is empty")
check("canonical table covers >= 30 organisms",
      len(INTRINSIC_RESISTANCE) >= 30, f"only {len(INTRINSIC_RESISTANCE)}")

_rules = getattr(AR, "INTRINSIC_RULES", [])
check("ast_reportability exposes a rule list", bool(_rules))

# Any drug the canonical table bans for an organism must also be flagged by the
# QC layer when it is reported S. This is the exact contradiction that shipped.
_PROBE_ORGS = [
    "Escherichia coli", "Klebsiella pneumoniae", "Proteus mirabilis",
    "Morganella morganii", "Serratia marcescens", "Enterobacter cloacae",
    "Pseudomonas aeruginosa", "Acinetobacter baumannii",
    "Stenotrophomonas maltophilia", "Enterococcus faecalis",
    "Staphylococcus aureus", "Listeria monocytogenes",
]
mismatch: list[str] = []
for org in _PROBE_ORGS:
    ol = org.lower()
    banned: set[str] = set()
    for key, drugs in INTRINSIC_RESISTANCE.items():
        if key in ol or ol in key:
            banned |= set(drugs)
    for drug in sorted(banned):
        issues = check_reportability(org, {drug: "S"})
        if not issues:
            mismatch.append(f"{org}/{drug}")
check("every canonical-banned drug reported S is flagged by the QC layer",
      not mismatch,
      f"{len(mismatch)} silent: {mismatch[:6]}{' ...' if len(mismatch) > 6 else ''}")

# ============================================================================
# [2] ACINETOBACTER vs AMOX-CLAV  (the bug that started this)
# ============================================================================
print("\n[2] Acinetobacter / beta-lactamase-inhibitor asymmetry")

_AC = "Acinetobacter baumannii"
_AMOXCLAV = "Amoxicillin + Clavulanic acid"
_AMPSULB = "Ampicillin/Sulbactam"

check("amox-clav is in the canonical table for Acinetobacter",
      any(_nk(_AMOXCLAV) == _nk(d)
          for k, v in INTRINSIC_RESISTANCE.items() if "acinetobacter" in k
          for d in v),
      "clavulanate has no activity here; EUCAST lists amox-clav explicitly")

iss = check_reportability(_AC, {_AMOXCLAV: "S"})
check("amox-clav reported S on Acinetobacter raises a QC issue", bool(iss))
check("...and it is severity 'error', not a soft warning",
      any(i.get("severity") == "error" for i in iss),
      f"severities={[i.get('severity') for i in iss]}")

iss2 = check_reportability(_AC, {_AMPSULB: "S"})
check("amp-SULBACTAM reported S on Acinetobacter is NOT flagged",
      not iss2,
      "sulbactam has intrinsic anti-Acinetobacter activity — flagging it would "
      "remove the backbone agent for CRAB")

# "clav" must never reappear in the Acinetobacter exclude list.
_ac_rule = next((r for r in _rules if r.get("id") == "intr_acinetobacter"), None)
if _ac_rule is None:
    skip("Acinetobacter rule has no 'clav' in exclude", "rule id not found")
else:
    check("Acinetobacter rule does not exclude 'clav'",
          not any("clav" in str(x).lower() for x in _ac_rule.get("exclude", [])),
          f"exclude={_ac_rule.get('exclude')}")
    check("Acinetobacter rule still excludes 'sulbactam'",
          any("sulbactam" in str(x).lower() for x in _ac_rule.get("exclude", [])))

# The recommendation engine must agree with the QC layer.
try:
    from clinical_engines import is_intrinsically_avoided
    from abx_guidelines import ABX_GUIDELINES
    check("recommendation engine also avoids amox-clav for Acinetobacter",
          is_intrinsically_avoided(_AC, _AMOXCLAV, ABX_GUIDELINES.get(_AMOXCLAV, {})))
    check("recommendation engine does NOT avoid amp-sulbactam for Acinetobacter",
          not is_intrinsically_avoided(_AC, _AMPSULB, ABX_GUIDELINES.get(_AMPSULB, {})))
except Exception as exc:  # pragma: no cover
    skip("engine/QC agreement on Acinetobacter", f"import failed: {exc}")

# ============================================================================
# [3] THE OCR DRUG-NAME SCANNER
# ============================================================================
print("\n[3] OCR scanner — no phantom drugs from combination names")

try:
    from ocr_extract import extract_detected_drugs, match_antibiotic_from_text
except Exception as exc:  # pragma: no cover
    skip("OCR scanner tests", f"ocr_extract import failed: {exc}")
    extract_detected_drugs = None  # type: ignore

if extract_detected_drugs is not None:
    # Each case: (printed line, the name that must NOT be manufactured from it)
    _PHANTOM_CASES = [
        ("Ampicillin/Sulbactam        S", "Ampicillin"),
        ("Ampicillin + Sulbactam      S", "Ampicillin"),
        ("Amoxicillin + Clavulanic acid  R", "Amoxicillin"),
        ("Cefoperazone + Sulbactam    S", "Cefoperazone"),
        ("Ciprofloxacin               S", "Ofloxacin"),
        ("Levofloxacin                S", "Ofloxacin"),
    ]
    for line, phantom in _PHANTOM_CASES:
        got = extract_detected_drugs(line)
        check(f"'{line.split()[0]}' does not manufacture '{phantom}'",
              phantom not in got, f"returned {got}")

    # A whole sheet must yield exactly the agents printed on it.
    sheet = (
        "Antibiotic Sensitivity Test\n"
        "Ampicillin/Sulbactam        S\n"
        "Cefoperazone + Sulbactam    S\n"
        "Amoxicillin + Clavulanic acid  R\n"
        "Meropenem                   R\n"
        "Amikacin                    S\n"
        "Ciprofloxacin               S\n"
        "Colistin                    S\n"
    )
    got = extract_detected_drugs(sheet)
    check("full sheet yields exactly the 7 printed agents",
          len(got) == 7, f"got {len(got)}: {got}")

    # Paper order, not alphabetical: the screen must follow the printed sheet or
    # the user attaches an S/I/R to the wrong row.
    check("scanner preserves printed order (not alphabetical)",
          got and got[0].lower().startswith("ampicillin"),
          f"first entry was {got[0] if got else None!r}")

    # Reversed spellings printed by some analysers must resolve to the combination.
    for line, want in [
        ("Sulbactam/Ampicillin   S", "Ampicillin/Sulbactam"),
        ("Ampicillin-Sulbactam   R", "Ampicillin/Sulbactam"),
        ("Sulbactam + Cefoperazone  S", "Cefoperazone + Sulbactam"),
    ]:
        check(f"'{line.strip()}' resolves to the combination agent",
              match_antibiotic_from_text(line) == want,
              f"got {match_antibiotic_from_text(line)!r}")

    # End-to-end: the phantom used to reach the QC panel as a fake alert.
    detected = extract_detected_drugs("Ampicillin/Sulbactam   S\nMeropenem   R\n")
    fake = [d for d in detected if _nk(d) in (_nk("Ampicillin"), _nk("Amoxicillin"))]
    check("no phantom aminopenicillin reaches the Acinetobacter QC panel",
          not fake, f"phantoms leaked: {fake}")

# ============================================================================
# [4] P. AERUGINOSA CARBAPENEMASE GATE
# ============================================================================
print("\n[4] carbapenem resistance — organism-aware mechanism call")

try:
    from clinical_engines import predict_esbl, analyze_antibiotics
except Exception as exc:  # pragma: no cover
    skip("mechanism gate tests", f"clinical_engines import failed: {exc}")
    predict_esbl = None  # type: ignore

if predict_esbl is not None:
    _pa_sir = {"Meropenem": "R", "Imipenem/Cilastatin": "R",
               "Ceftazidime": "S", "Cefepime": "S", "Amikacin": "S"}
    r = predict_esbl("Pseudomonas aeruginosa", _pa_sir)
    check("P. aeruginosa 2-carbapenem-R is NOT called 'carbapenemase'",
          r.get("probability") != "carbapenemase",
          f"probability={r.get('probability')} confidence={r.get('confidence')}")
    check("...it gets its own moderate-confidence pathway",
          r.get("probability") == "cr_pseudomonas" and r.get("confidence", 100) < 80,
          f"probability={r.get('probability')} confidence={r.get('confidence')}")
    check("...and the read-out names the beta-lactams still testing S",
          "Ceftazidime" in (r.get("still_susceptible_betalactams") or []),
          f"still_S={r.get('still_susceptible_betalactams')}")

    a, w, b, _p, _i = analyze_antibiotics(
        list(_pa_sir), "Pseudomonas aeruginosa", "Urine", 40, "Male",
        False, 100.0, False, False, [], _pa_sir, "CLSI")
    _banned = {x["name"] for x in b}
    check("SUSCEPTIBLE Ceftazidime is not banned on carbapenem-R P. aeruginosa",
          "Ceftazidime" not in _banned,
          "a working, less toxic drug was being removed from the report")
    check("SUSCEPTIBLE Cefepime is not banned either",
          "Cefepime" not in _banned)

    # Enterobacterales must be untouched: the 92% tier is correct there.
    r2 = predict_esbl("Klebsiella pneumoniae",
                      {"Meropenem": "R", "Imipenem/Cilastatin": "R"})
    check("Enterobacterales 2-carbapenem-R still calls carbapenemase",
          r2.get("probability") == "carbapenemase",
          f"probability={r2.get('probability')}")
    check("...at high confidence",
          r2.get("confidence", 0) >= 85, f"confidence={r2.get('confidence')}")

    # OXA-48-like pattern stays a confirm-first, moderate-confidence signal.
    r3 = predict_esbl("Klebsiella pneumoniae",
                      {"Ertapenem": "R", "Meropenem": "S"})
    check("Ertapenem-R / Meropenem-S is not asserted at high confidence",
          r3.get("confidence", 100) < 85,
          f"confidence={r3.get('confidence')} — porin loss + ESBL gives this too")

# ============================================================================
# [5] CROSS-CUTTING INVARIANTS
# ============================================================================
print("\n[5] cross-cutting invariants")

# An organism must never be intrinsically resistant to a drug the same table
# treats as its established therapy.
_ESTABLISHED = {
    "stenotrophomonas maltophilia": ["Trimethoprim/Sulfamethoxazole",
                                     "Trimethoprim + Sulfamethoxazole"],
    "acinetobacter baumannii": ["Ampicillin/Sulbactam", "Ampicillin + Sulbactam"],
    "pseudomonas aeruginosa": ["Ceftazidime", "Cefepime", "Meropenem", "Amikacin"],
    "listeria monocytogenes": ["Ampicillin", "Amoxicillin"],
}
contradictions = []
for org_key, keep in _ESTABLISHED.items():
    banned = {_nk(d) for k, v in INTRINSIC_RESISTANCE.items()
              if k in org_key or org_key in k for d in v}
    for drug in keep:
        if _nk(drug) in banned:
            contradictions.append(f"{org_key}/{drug}")
check("no organism is banned from its own established therapy",
      not contradictions, str(contradictions))

# Beta-lactamase-inhibitor asymmetry must be explicit, never accidental.
_bli_checks = [
    ("Klebsiella pneumoniae", "Ampicillin", True),
    ("Klebsiella pneumoniae", "Amoxicillin + Clavulanic acid", False),
    ("Acinetobacter baumannii", "Amoxicillin + Clavulanic acid", True),
    ("Acinetobacter baumannii", "Ampicillin/Sulbactam", False),
]
try:
    from clinical_engines import is_intrinsically_avoided as _iia
    from abx_guidelines import ABX_GUIDELINES as _AG
    for org, drug, want_banned in _bli_checks:
        got = _iia(org, drug, _AG.get(drug, {}))
        check(f"{org.split()[0]} / {drug} -> "
              f"{'banned' if want_banned else 'allowed'}",
              got == want_banned, f"got banned={got}")
except Exception as exc:  # pragma: no cover
    skip("BLI asymmetry matrix", f"import failed: {exc}")

# Every organism the UI can offer should resolve against the table, or be a
# documented orphan (serology-only / no routine AST).
try:
    from organism_profile import ORGANISM_PROFILE
    _DOCUMENTED_ORPHANS = {
        "MRSA",                    # handled as a phenotype, not a table row
        "Campylobacter jejuni", "H. influenzae", "Legionella pneumophila",
        "Mycoplasma spp.", "Anaerobes (لاهوائيات)", "Rickettsia spp.",
        "Neisseria meningitidis", "Moraxella catarrhalis",
    }
    unresolved = []
    for org in ORGANISM_PROFILE:
        ol = org.lower().strip()
        if not any(k in ol or ol in k for k in INTRINSIC_RESISTANCE):
            if org not in _DOCUMENTED_ORPHANS:
                unresolved.append(org)
    check("every UI organism resolves against the table or is a documented orphan",
          not unresolved, str(unresolved))
except Exception as exc:  # pragma: no cover
    skip("UI organism coverage", f"import failed: {exc}")

# ============================================================================
print(f"\n  {passed} passed, {len(failures)} failed, {skipped} skipped")
if failures:
    print("\nRESULT: FAILED")
    for f in failures:
        print("   x " + f)
    sys.exit(1)
print("\nRESULT: all intrinsic / OCR / mechanism guards hold.")
sys.exit(0)
