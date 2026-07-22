#!/usr/bin/env python3
"""
Orange Lab CDSS — guideline registry guard.

Run:  python test_guidelines.py           (no pytest, no network)
      python test_guidelines.py --queue   (print the verification queue and exit 0)

WHAT THIS ENFORCES
------------------
A citation string in a comment proves nothing: nobody re-reads it, and when the
underlying document is revised the string keeps its old text forever. These
checks turn the registry into something that can actually FAIL a build:

  G1  every rule names a source that exists in SOURCES
  G2  no rule cites a document the registry itself marks as superseded
  G3  every "primary" verification carries who + when, in a parseable date
  G4  no primary verification is older than STALENESS_MONTHS
  G5  every rule id in ast_reportability._RULES has a registry row  (and back)
  G6  no source metadata is missing a version, date or URL
  G7  the superseded EUCAST wording is gone from the shipped source files

G5 is the one that catches real drift: it means a clinician cannot add a QC rule
to the engine without also stating which document it comes from.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from guideline_registry import (  # noqa: E402
    RULES, SOURCES, STALENESS_MONTHS,
    pending_rules, stale_rules, superseded_citations, print_queue,
)

failures: list[str] = []
passes = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global passes
    if ok:
        passes += 1
        print(f"  [PASS] {label}")
    else:
        failures.append(f"{label}{' — ' + detail if detail else ''}")
        print(f"  [FAIL] {label}" + (f"  — {detail}" if detail else ""))


print("Orange Lab CDSS — guideline registry guard\n")

# ── G1: every rule points at a real source ──────────────────────────────────
bad = {rid: r["source"] for rid, r in RULES.items() if r["source"] not in SOURCES}
check("G1  every rule names a source present in SOURCES", not bad, str(bad))

# ── G2: nothing cites a superseded document ─────────────────────────────────
sup = superseded_citations()
check("G2  no rule cites a superseded document", not sup,
      f"{sorted(sup)} still cite superseded sources")

# ── G3: primary verifications are attributable and parseable ────────────────
_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
malformed = {}
for rid, r in RULES.items():
    if r.get("verified") == "primary":
        if not r.get("verified_by"):
            malformed[rid] = "missing verified_by"
        elif not r.get("verified_on"):
            malformed[rid] = "missing verified_on"
        elif not _DATE.match(str(r["verified_on"])):
            malformed[rid] = f"unparseable date {r['verified_on']!r}"
check("G3  every primary verification has who + when", not malformed, str(malformed))

# ── G4: no primary verification has gone stale ──────────────────────────────
stale = stale_rules()
check(f"G4  no primary verification older than {STALENESS_MONTHS} months",
      not stale, str(stale))

# ── G5: registry and engine rule-sets are in sync ───────────────────────────
def _engine_rule_ids(path: str) -> set[str]:
    """Pull the "id" of every dict in the module-level _RULES list, via AST."""
    if not os.path.exists(path):
        return set()
    tree = ast.parse(open(path, encoding="utf-8").read())
    ids: set[str] = set()
    for node in tree.body:
        # The list is written as an annotated assignment
        # (INTRINSIC_RULES: List[Dict[str, Any]] = [...]), which is ast.AnnAssign,
        # NOT ast.Assign -- checking only Assign silently found nothing and the
        # whole G5 sync check degraded to [SKIP].
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        elif isinstance(node, ast.Assign):
            targets = node.targets
        else:
            continue
        if any(
            getattr(t, "id", None) in ("INTRINSIC_RULES", "_RULES", "RULES",
                                       "_REPORTABILITY_RULES")
            for t in targets
        ) and isinstance(node.value, (ast.List, ast.Tuple)):
            for elt in node.value.elts:
                if isinstance(elt, ast.Dict):
                    for k, v in zip(elt.keys, elt.values):
                        if getattr(k, "value", None) == "id" and isinstance(v, ast.Constant):
                            ids.add(v.value)
    return ids


engine_ids = _engine_rule_ids(os.path.join(HERE, "ast_reportability.py"))
if not engine_ids:
    print("  [SKIP] G5  ast_reportability.py has no extractable _RULES list")
else:
    missing_in_registry = engine_ids - set(RULES)
    check("G5a every ast_reportability rule has a registry row",
          not missing_in_registry, str(sorted(missing_in_registry)))
    # The registry legitimately holds rows for logic that lives elsewhere
    # (mechanism inference, therapy notes), so only intr_* ids must round-trip.
    intr_registry = {k for k in RULES if k.startswith("intr_")}
    orphan = intr_registry - engine_ids
    check("G5b every intr_* registry row exists in ast_reportability",
          not orphan, str(sorted(orphan)))

# ── G6: source metadata is complete enough to be actionable ─────────────────
incomplete = {
    k: [f for f in ("title", "version", "published", "url") if not v.get(f)]
    for k, v in SOURCES.items()
    if not all(v.get(f) for f in ("title", "version", "published", "url"))
}
check("G6  every source has title / version / date / url", not incomplete,
      str(incomplete))

# ── G7: the superseded EUCAST wording is gone from shipped code ─────────────
# EUCAST retired "intrinsic resistance" as a published document name in 2022.
# A stale citation in a report is a clinical-credibility problem, so it fails.
stale_cite = []
for fn in sorted(f for f in os.listdir(HERE) if f.endswith(".py")):
    if fn.startswith("test_") or fn == "guideline_registry.py":
        continue
    txt = open(os.path.join(HERE, fn), encoding="utf-8").read()
    if "EUCAST Intrinsic Resistance v3.3" in txt:
        stale_cite.append(fn)
check("G7  no shipped file still cites 'EUCAST Intrinsic Resistance v3.3'",
      not stale_cite, str(stale_cite))

# ── Report ──────────────────────────────────────────────────────────────────
pend = pending_rules()
print(f"\n  {passes} check(s) passed, {len(failures)} failed")
print(f"  registry: {len(RULES)} rules across {len(SOURCES)} sources — "
      f"{len(RULES) - len(pend)} primary-verified, {len(pend)} pending")

if pend:
    print("\n  NOTE: 'pending' rows are NOT a build failure. They are assertions")
    print("        carried over from earlier development that no human has yet")
    print("        checked against the source PDF. Run:")
    print("            python guideline_registry.py --queue")
    print("        to get the list with direct document links.")

if failures:
    print("\nRESULT: guideline registry FAILED")
    for f in failures:
        print("   x " + f)
    sys.exit(1)

print("\nRESULT: guideline registry OK — every clinical rule is traceable to a "
      "versioned, current document.")
if "--queue" in sys.argv:
    print_queue()
sys.exit(0)
