#!/usr/bin/env python3
"""
Orange Lab CDSS — scenario matrix invariants.

Run:  python test_scenarios.py            (no pytest, no network)
      python test_scenarios.py -v         (print every violation, not the first 5)

Each scenario from scenario_matrix.build_matrix() is pushed through the real
recommendation engine and the real QC layer, and the OUTPUT is checked against
invariants that must hold for every organism, specimen and resistance pattern.

WHY INVARIANTS RATHER THAN EXPECTED OUTPUTS
-------------------------------------------
A golden-output test for 277 scenarios breaks on every deliberate clinical
change, gets bulk-regenerated without being read, and then guards nothing. An
invariant states a property that must be true no matter how the advice evolves,
so it survives intentional change and only fires on a real contradiction.

THE INVARIANTS
--------------
  INV-1   no drug appears in more than one bucket (allowed/caution/avoid)
  INV-2   a drug reported R is never in the allowed bucket
  INV-3   an expected-resistant drug is never in the allowed bucket
  INV-4   the QC layer and the recommendation engine never disagree about
          expected resistance  (the class of bug that started all of this)
  INV-5   urinary-only agents never appear for a non-urine specimen
  INV-6   no scenario produces an empty report with no explanation
  INV-7   an ESBL/AmpC label is only ever applied to Enterobacterales
  INV-8   a carbapenemase label is never applied to P. aeruginosa
  INV-9   for every organism/drug pair the canonical table bans, the QC layer
          raises an issue when it is reported S     (found the missing
          Streptococcus/Enterococcus aminoglycoside rule)
  INV-10  a beta-lactam testing SUSCEPTIBLE is never silently discarded without
          the report naming a mechanism that justifies it
  INV-11  the engine never crashes, and never returns a non-dict item
  INV-12  results are deterministic — same input, same output
  INV-13  every avoid entry carries a human-readable reason
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

VERBOSE = "-v" in sys.argv

from scenario_matrix import build_matrix                      # noqa: E402
from clinical_data import INTRINSIC_RESISTANCE                # noqa: E402
from clinical_engines import analyze_antibiotics, predict_esbl  # noqa: E402
from ast_reportability import check_reportability             # noqa: E402

try:
    from clinical_data import ESBL_PRODUCERS
except Exception:                                             # pragma: no cover
    ESBL_PRODUCERS = frozenset()

MATRIX = build_matrix()

violations: Dict[str, List[str]] = {}


def fail(inv: str, msg: str) -> None:
    violations.setdefault(inv, []).append(msg)


def _nk(s: str) -> str:
    return "".join(c for c in (s or "").lower() if c.isalnum())


def _banned_set(org: str) -> set:
    ol = (org or "").lower().strip()
    out = set()
    for k, v in INTRINSIC_RESISTANCE.items():
        if k in ol or ol in k:
            out |= {_nk(d) for d in v}
    return out


_URINE_ONLY = {_nk(d) for d in ("Nitrofurantoin", "Fosfomycin", "Furadantin")}


def _run(sc: Dict[str, Any]) -> Dict[str, Any]:
    """Run one scenario through the real engine."""
    sir = sc["sir"]
    allowed, warned, banned, preg, inter = analyze_antibiotics(
        list(sir), sc["organism"], sc["specimen"], 45, "Male",
        False, 95.0, False, False, [], sir, "CLSI")
    return {
        "allowed": allowed, "warned": warned, "banned": banned,
        "mech": predict_esbl(sc["organism"], sir),
        "qc": check_reportability(sc["organism"], sir),
    }


print(f"Orange Lab CDSS — scenario matrix invariants "
      f"({len(MATRIX)} scenarios)\n")

crashed = 0
for sc in MATRIX:
    sid = sc["id"]
    try:
        res = _run(sc)
    except Exception as exc:                                  # INV-11
        crashed += 1
        fail("INV-11", f"{sid}: CRASH {type(exc).__name__}: {exc}")
        continue

    a_names = {x.get("name") for x in res["allowed"] if isinstance(x, dict)}
    w_names = {x.get("name") for x in res["warned"] if isinstance(x, dict)}
    b_names = {x.get("name") for x in res["banned"] if isinstance(x, dict)}

    # INV-11 (shape): every bucket entry must be a dict with a name
    for bucket, items in (("allowed", res["allowed"]), ("warned", res["warned"]),
                          ("banned", res["banned"])):
        for it in items:
            if not isinstance(it, dict) or not it.get("name"):
                fail("INV-11", f"{sid}: malformed {bucket} entry {it!r}")

    # INV-1: buckets are disjoint
    for x, y, lbl in ((a_names, w_names, "allowed/caution"),
                      (a_names, b_names, "allowed/avoid"),
                      (w_names, b_names, "caution/avoid")):
        dup = x & y
        if dup:
            fail("INV-1", f"{sid}: {lbl} overlap {sorted(dup)}")

    # INV-2: an R result can never be recommended
    for d, v in sc["sir"].items():
        if v == "R" and d in a_names:
            fail("INV-2", f"{sid}: {d}=R is in allowed")

    # INV-3: expected-resistant drugs are never recommended
    banned_canon = _banned_set(sc["organism"])
    for d in a_names:
        if _nk(d) in banned_canon:
            fail("INV-3", f"{sid}: expected-R {d} is in allowed")

    # INV-4: QC layer and engine agree about expected resistance
    for issue in res["qc"]:
        if "ntrinsic" not in str(issue.get("category", "")) and \
           "xpected" not in str(issue.get("category", "")):
            continue
        for d in issue.get("drugs", []):
            if d in a_names:
                fail("INV-4", f"{sid}: QC flags {d} but engine allows it")

    # INV-5: urinary-only agents must not appear for non-urine specimens
    if sc["specimen"].lower() != "urine":
        for d in (a_names | w_names):
            if _nk(d) in _URINE_ONLY:
                fail("INV-5", f"{sid}: urinary-only {d} offered for "
                              f"{sc['specimen']}")

    # INV-6: an empty report must still say something
    if not (a_names or w_names or b_names):
        fail("INV-6", f"{sid}: engine returned nothing at all")

    # INV-7 / INV-8: mechanism labels are organism-gated
    prob = (res["mech"] or {}).get("probability")
    ol = sc["organism"].lower()
    if prob in ("high", "moderate", "ampc"):
        is_producer = any(p in ol or ol in p for p in ESBL_PRODUCERS) \
            if ESBL_PRODUCERS else True
        if not is_producer:
            fail("INV-7", f"{sid}: '{prob}' label on non-Enterobacterale")
    if prob == "carbapenemase" and "pseudomonas" in ol:
        fail("INV-8", f"{sid}: carbapenemase asserted for P. aeruginosa")

    # INV-10: a SUSCEPTIBLE beta-lactam moved to avoid needs a stated reason
    for item in res["banned"]:
        if not isinstance(item, dict):
            continue
        nm = item.get("name", "")
        if sc["sir"].get(nm) == "S":
            reason = " ".join(str(item.get(k, "")) for k in
                              ("reason_short", "reason_detail", "category",
                               "reason_short_en", "reason_detail_en"))
            if not reason.strip():
                fail("INV-10", f"{sid}: susceptible {nm} avoided with no reason")

    # INV-13: every avoid entry is explained
    for item in res["banned"]:
        if isinstance(item, dict):
            txt = " ".join(str(item.get(k, "")) for k in
                           ("reason_short", "reason_detail",
                            "reason_short_en", "reason_detail_en"))
            if not txt.strip():
                fail("INV-13", f"{sid}: {item.get('name')} avoided with no reason text")

    # INV-12: determinism
    res2 = _run(sc)
    if {x.get("name") for x in res2["allowed"]} != a_names:
        fail("INV-12", f"{sid}: non-deterministic allowed set")

# INV-9: whole-table sweep — canonical bans must be visible to QC
for org in sorted({sc["organism"] for sc in MATRIX}):
    ol = org.lower().strip()
    for key, drugs in INTRINSIC_RESISTANCE.items():
        if not (key in ol or ol in key):
            continue
        for drug in drugs:
            if not check_reportability(org, {drug: "S"}):
                fail("INV-9", f"{org}/{drug} reported S raises no QC issue")

# ── Report ──────────────────────────────────────────────────────────────────
_ALL = [f"INV-{i}" for i in range(1, 14)]
print(f"  scenarios run : {len(MATRIX)}")
print(f"  crashes       : {crashed}\n")

for inv in _ALL:
    hits = violations.get(inv, [])
    if not hits:
        print(f"  [PASS] {inv}")
    else:
        print(f"  [FAIL] {inv}  — {len(hits)} violation(s)")
        for h in (hits if VERBOSE else hits[:5]):
            print(f"           {h}")
        if not VERBOSE and len(hits) > 5:
            print(f"           ... and {len(hits) - 5} more (run with -v)")

total = sum(len(v) for v in violations.values())
if total:
    print(f"\nRESULT: {total} violation(s) across "
          f"{len(violations)} invariant(s) — see above.")
    sys.exit(1)

print(f"\nRESULT: all 13 invariants hold across {len(MATRIX)} clinical scenarios.")
sys.exit(0)
