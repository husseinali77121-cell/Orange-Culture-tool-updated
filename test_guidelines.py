"""Orange Lab CDSS — guideline traceability check.

Answers the question a behaviour test cannot: "does every clinical rule in this
engine come from a named, dated document, and has anyone actually checked it?"

FAILS when:
  * a rule in the engine has no row in guideline_registry.RULES
  * a registry row exists for a rule the engine no longer has (dead citation)
  * a row points at a source key that is not defined
  * a source is missing a version, date or URL
  * a verified row has gone stale (> STALE_AFTER_MONTHS)
  * a verified row does not name who checked it and when
  * a deprecated / ambiguous citation string is still used in the codebase

REPORTS (does not fail) the "pending" queue — rules inherited from earlier code
that nobody has verified against the source PDF yet. Keeping that number visible
is the whole point; a pending rule is not a bug, an invisible one is.

    python test_guidelines.py            # check
    python test_guidelines.py --queue    # print the pending review queue
"""
from __future__ import annotations

import datetime as _dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from guideline_registry import (                              # noqa: E402
    DEPRECATED_CITATIONS, RULES, SOURCES, STALE_AFTER_MONTHS, citation_line,
)

SHOW_QUEUE = "--queue" in sys.argv
TODAY = _dt.date.today()

failures: list[str] = []
warnings_: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)


# ── 1. Collect every rule id the engine actually uses ────────────────────────
def engine_rule_ids() -> set:
    ids: set = set()
    import ast_reportability as RP
    import ast_consistency as CN

    for group in ("INTRINSIC_RULES", "NO_BREAKPOINT_RULES", "INEFFECTIVE_INVIVO_RULES"):
        for r in getattr(RP, group, []):
            if isinstance(r, dict) and r.get("id"):
                ids.add(r["id"])
    for group in ("EQUIVALENCE_RULES", "HIERARCHY_RULES", "PREDICTIVE_RULES",
                  "CORRECTION_RULES"):
        for r in getattr(CN, group, []):
            if isinstance(r, dict) and r.get("id"):
                ids.add(r["id"])

    app = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
    ids |= set(re.findall(r'"id":\s*"(QC\d+)"', app))
    ids |= set(re.findall(r'f"(SPEC-URN|REP-GPO-GN):', app))
    return ids


ENGINE_IDS = engine_rule_ids()

print("Orange Lab CDSS — guideline traceability\n")

# ── 2. Every engine rule is registered, and vice versa ───────────────────────
unregistered = sorted(ENGINE_IDS - set(RULES))
for rid in unregistered:
    fail(f"rule '{rid}' is active in the engine but has no citation row")

dead = sorted(set(RULES) - ENGINE_IDS)
for rid in dead:
    fail(f"citation row '{rid}' has no matching rule in the engine (dead citation)")

# ── 3. Sources are complete ──────────────────────────────────────────────────
for key, src in SOURCES.items():
    for field in ("title", "version", "dated", "url"):
        if not src.get(field):
            fail(f"source '{key}' is missing '{field}'")
    if src.get("url") and not src["url"].startswith("http"):
        fail(f"source '{key}' has a URL that is not a URL: {src['url']!r}")

# ── 4. Rows are well formed, and 'primary' rows are attributed and fresh ─────
pending: list[str] = []
primary: list[str] = []
unsigned: list[str] = []

for rid, row in sorted(RULES.items()):
    if row.get("source") not in SOURCES:
        fail(f"rule '{rid}' points at undefined source {row.get('source')!r}")
    if not row.get("assertion"):
        fail(f"rule '{rid}' has no assertion text")

    level = row.get("verified")
    if level in ("source", "secondary"):
        primary.append(rid)
        if not row.get("checked_by"):
            fail(f"rule '{rid}' is marked {level} but names no checker")
        if not row.get("countersigned_by"):
            unsigned.append(rid)
        stamp = row.get("checked_on")
        if not stamp:
            fail(f"rule '{rid}' is marked {level} but carries no date")
            continue
        try:
            when = _dt.date.fromisoformat(stamp)
        except ValueError:
            fail(f"rule '{rid}' has an unparseable verified_on: {stamp!r}")
            continue
        if when > TODAY:
            fail(f"rule '{rid}' was verified in the future ({stamp})")
        months = (TODAY.year - when.year) * 12 + (TODAY.month - when.month)
        if months > STALE_AFTER_MONTHS:
            fail(f"rule '{rid}' verification is stale — checked {months} months ago "
                 f"({stamp}); limit is {STALE_AFTER_MONTHS}")
    elif level == "pending":
        pending.append(rid)
    else:
        fail(f"rule '{rid}' has an unknown verification level {level!r} "
             f"(expected 'source', 'secondary' or 'pending')")

# ── 5. Deprecated citation strings must be gone from the codebase ────────────
SKIP = {"guideline_registry.py", "test_guidelines.py"}
hits: dict = {}
for path in sorted(ROOT.rglob("*.py")):
    if path.name in SKIP:
        continue
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:                                          # noqa: BLE001
        continue
    for bad in DEPRECATED_CITATIONS:
        n = text.count(bad)
        if n:
            hits.setdefault(bad, []).append((path.name, n))

# ── Report ───────────────────────────────────────────────────────────────────
print(f"  rules in engine   : {len(ENGINE_IDS)}")
print(f"  citation rows     : {len(RULES)}")
print(f"  checked vs source : {len(primary)}")
print(f"  pending review    : {len(pending)}")
print(f"  awaiting human    : {len(unsigned)}  (checked, not yet countersigned)")

if hits:
    total = sum(n for v in hits.values() for _, n in v)
    print(f"\n  DEPRECATED CITATION STRINGS — {total} occurrence(s):")
    for bad, where in sorted(hits.items()):
        loc = ", ".join(f"{f} x{n}" for f, n in where)
        print(f"    \"{bad}\"  ({loc})")
        print(f"        -> {DEPRECATED_CITATIONS[bad]}")
        failures.append(f'deprecated citation "{bad}" still used ({loc})')

if SHOW_QUEUE and pending:
    print(f"\n  PENDING REVIEW QUEUE ({len(pending)}) — open the PDF, confirm the "
          f"assertion, then set verified/verified_by/verified_on:")
    for rid in pending:
        print(f"\n    {rid}")
        print(f"      {RULES[rid]['assertion'][:150]}")
        print(f"      -> {citation_line(rid)}")
        print(f"         {SOURCES[RULES[rid]['source']]['url']}")

if failures:
    print(f"\n  FAILURES ({len(failures)}):")
    for f in failures:
        print(f"    ✗ {f}")

print("\n" + "=" * 68)
if failures:
    print("RESULT: traceability incomplete")
else:
    print(f"RESULT: every rule traced. {len(primary)} checked against published "
          f"sources, {len(pending)} not yet checked, {len(unsigned)} awaiting a "
          f"clinician's countersignature. Run --queue for the review list.")
sys.exit(1 if failures else 0)
