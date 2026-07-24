"""Orange Lab CDSS — full clinical scenario matrix.

Runs every (organism x specimen x AST-archetype) case from scenario_matrix.py
through the WHOLE engine — analyze_antibiotics, classify_mdr, predict_esbl,
detect_resistance_phenotypes, assess_pathogenicity, run_ast_qc — and checks two
different things about each result:

  1. INVARIANTS. Properties that must hold for EVERY case, no exceptions. These
     are what catch bugs nobody anticipated: a drug landing in two buckets at
     once, an intrinsically-resistant agent reaching the Allowed list, a
     two-agent panel being called XDR. An invariant failure is always a bug.

  2. A GOLDEN SNAPSHOT. A stable digest of the clinically meaningful output of
     each case. A snapshot diff is NOT automatically a bug — it means the
     engine's answer changed and a human must decide whether that change was
     intended. Re-bless with:  python test_scenarios.py --update

Usage
-----
    python test_scenarios.py             # invariants + snapshot comparison
    python test_scenarios.py --update    # re-record the snapshot
    python test_scenarios.py --verbose   # list every failing case

REVIEW RULE (this is the part a test file cannot enforce for you):
a snapshot diff must be read before it is blessed. If nobody reads it, the
snapshot stops being a safety net and becomes decoration.
"""
from __future__ import annotations

import ast
import hashlib
import json
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

SNAPSHOT = ROOT / "scenario_snapshot.json"
UPDATE = "--update" in sys.argv
VERBOSE = "--verbose" in sys.argv


# ── Load the monolith's logic without starting Streamlit ─────────────────────
class _Mock:
    def __call__(self, *a, **k): return _Mock()
    def __getattr__(self, n): return _Mock()
    def __enter__(self): return _Mock()
    def __exit__(self, *a): return False
    def __bool__(self): return False


class _SessionState(dict):
    def __getattr__(self, n): return self.get(n)
    def __setattr__(self, n, v): self[n] = v


class _StreamlitStub(types.ModuleType):
    def __getattr__(self, n): return _Mock()


_stub = _StreamlitStub("streamlit")
_stub.session_state = _SessionState()
_stub.secrets = {}
sys.modules["streamlit"] = _stub

_src = (ROOT / "streamlit_app.py").read_text(encoding="utf-8")
_cut = _src.index("if not st.session_state.authenticated:")
APP: dict = {"__name__": "app_core"}
exec(compile(_src[:_cut], "streamlit_app.py", "exec"), APP)

analyze_antibiotics = APP["analyze_antibiotics"]
classify_mdr = APP["classify_mdr"]
predict_esbl = APP["predict_esbl"]
is_esbl_producer = APP["is_esbl_producer"]
detect_resistance_phenotypes = APP["detect_resistance_phenotypes"]
assess_pathogenicity = APP["assess_pathogenicity"]
run_ast_qc = APP["run_ast_qc"]
classify_specimen = APP["classify_specimen"]

from scenario_matrix import build_matrix, intrinsic_for      # noqa: E402

# ── Fixed patient context, so a snapshot diff can only come from the engine ──
PATIENT = dict(age=45, sex="Male", is_renal=False, cl_cr=95.0,
               is_preg=False, is_hepatic=False, current_meds=[])

failures: list[str] = []
checked = 0


def fail(case_id: str, invariant: str, detail: str = "") -> None:
    failures.append(f"[{invariant}] {case_id}" + (f" — {detail}" if detail else ""))


def run_case(case: dict) -> dict:
    """Run the whole engine on one scenario and return its snapshot record."""
    org, spec, sir = case["organism"], case["specimen"], dict(case["sir_map"])

    allowed, warned, banned, preg, inter = analyze_antibiotics(
        final_drugs=list(sir), organism_type=org, culture_type=spec,
        sir_map=sir, **PATIENT)
    mdr = classify_mdr(org, sir)
    esbl = predict_esbl(org, sir)
    phen = detect_resistance_phenotypes(org, sir)
    qc = run_ast_qc(org, sir, specimen=spec)
    patho = assess_pathogenicity(
        specimen=spec, organism=org, colony_count_text="", culture_purity="Pure",
        symptoms=[], pus_cells_text="", urinalysis_result="", gram_stain="",
        age=PATIENT["age"], sex=PATIENT["sex"], host_factors=[])

    a = {d["name"] for d in allowed}
    w = {d["name"] for d in warned}
    b = {d["name"] for d in banned}
    intrinsic = intrinsic_for(org)
    cid = case["id"]

    # ── INVARIANTS ───────────────────────────────────────────────────────────
    # INV-1  a drug is in at most one bucket
    for pair, lbl in (((a & w), "allowed+warned"), ((a & b), "allowed+banned"),
                      ((w & b), "warned+banned")):
        if pair:
            fail(cid, "INV-1 bucket-exclusivity", f"{lbl}: {sorted(pair)}")

    # INV-2  an intrinsically inactive agent is never offered
    leak = (a | w) & intrinsic
    if leak:
        fail(cid, "INV-2 intrinsic-never-offered", f"{sorted(leak)}")

    # INV-3  a Resistant result is never recommended
    r_allowed = {d for d in a if sir.get(d) == "R"}
    if r_allowed:
        fail(cid, "INV-3 R-never-allowed", f"{sorted(r_allowed)}")

    # INV-4  every routed drug was actually on the panel
    stray = (a | w | b) - set(sir)
    if stray:
        fail(cid, "INV-4 no-phantom-drugs", f"{sorted(stray)}")

    # INV-5  PDR means nothing tested Susceptible
    if mdr.get("level") == "PDR" and any(v == "S" for v in sir.values()):
        fail(cid, "INV-5 PDR-implies-no-S",
             f"S drugs: {sorted(d for d, v in sir.items() if v == 'S')}")

    # INV-6  ESBL is an Enterobacterales mechanism only
    if esbl.get("probability") in ("high", "moderate") and not is_esbl_producer(org):
        fail(cid, "INV-6 ESBL-gating", f"{org} -> {esbl.get('probability')}")

    # INV-7  a two-agent panel cannot establish XDR or PDR
    if case["archetype"] == "thin_panel" and mdr.get("level") in ("XDR", "PDR"):
        fail(cid, "INV-7 thin-panel-humility", f"level={mdr.get('level')}")

    # INV-8  P. aeruginosa carbapenem resistance is not a carbapenemase call
    if "pseudomonas" in org.lower() and esbl.get("probability") == "carbapenemase":
        fail(cid, "INV-8 no-carbapenemase-call-on-PA")

    # INV-9  a result contradicting intrinsic resistance must be flagged
    if case["archetype"] == "intrinsic_violation":
        offender = sorted(intrinsic & set(sir))
        if offender and not any(offender[0] in i.get("message", "") for i in qc):
            fail(cid, "INV-9 QC-catches-intrinsic", f"{offender[0]} not flagged")

    # INV-10  a urinary-only agent reported off-site must be flagged
    if case["archetype"] == "urine_agent_offsite":
        if not any("Nitrofurantoin" in i.get("message", "") for i in qc):
            fail(cid, "INV-10 QC-catches-offsite-urinary-agent")

    # INV-11  an all-susceptible wild type has options and is not MDR
    if case["archetype"] == "wild_type":
        if not a:
            fail(cid, "INV-11 wild-type-has-options", "Allowed list is empty")
        if mdr.get("level"):
            fail(cid, "INV-11 wild-type-not-MDR", f"level={mdr.get('level')}")

    # INV-12  pathogenicity output is well formed
    if not isinstance(patho.get("score"), int) or not patho.get("verdict"):
        fail(cid, "INV-12 pathogenicity-well-formed", f"{patho.get('score')!r}")

    # INV-13  every QC issue names a severity the UI can render
    for i in qc:
        if i.get("severity") not in ("error", "warning", "info"):
            fail(cid, "INV-13 QC-severity-renderable", f"{i.get('severity')!r}")

    # INV-14  every warning carries a reason the display layer can actually show.
    #  A warning_reason with no branch in the render code silently falls through to
    #  renal_note. That is not merely blank: on a suspected-carbapenemase warning
    #  for ceftriaxone it printed "renally safe, hepatically cleared" -- a
    #  reassuring, unrelated sentence attached to a resistance alert.
    _RENDERABLE = {"esbl_bli_uti_only", "possible_carbapenemase",
                   "intermediate_culture", "renal_adjustment"}
    for _w in warned:
        _wr = _w.get("warning_reason")
        if _wr and _wr not in _RENDERABLE:
            fail(cid, "INV-14 warning-is-renderable",
                 f"warning_reason={_wr!r} has no display branch")
        if _wr in ("esbl_bli_uti_only", "possible_carbapenemase") and not (
                _w.get("esbl_note") or _w.get("esbl_note_en")):
            fail(cid, "INV-14 warning-is-renderable",
                 f"{_wr} carries no esbl_note to display")

    # INV-15  every ban carries the reason_detail the report renders.
    for _b in banned:
        if not _b.get("reason_short"):
            fail(cid, "INV-15 ban-has-reason", f"{_b.get('name')} has no reason_short")

    # ── SNAPSHOT RECORD ──────────────────────────────────────────────────────
    return {
        "allowed":  sorted(a),
        "warned":   sorted(w),
        "banned":   sorted(b),
        "mdr":      mdr.get("level"),
        "mdr_cats": sorted(mdr.get("resistant_categories", [])),
        "esbl":     esbl.get("probability"),
        "esbl_conf": esbl.get("confidence"),
        "dtr":      esbl.get("dtr"),
        "phenotypes": sorted(p["phenotype"] for p in phen),
        "qc_ids":   sorted({i["id"] for i in qc}),
        "patho":    patho.get("verdict"),
        "preg_warn": sorted(d["name"] for d in preg),
    }


def main() -> int:
    global checked
    matrix = build_matrix()
    current: dict = {}
    for case in matrix:
        checked += 1
        try:
            current[case["id"]] = run_case(case)
        except Exception as exc:                       # noqa: BLE001
            fail(case["id"], "INV-0 no-crash", f"{type(exc).__name__}: {exc}")

    pairs = len({(c["specimen"], c["organism"]) for c in matrix})
    print(f"Orange Lab CDSS — scenario matrix")
    print(f"  {checked} scenarios · {pairs} organism x specimen pairs · "
          f"{len({c['archetype'] for c in matrix})} archetypes\n")

    # ── invariants ───────────────────────────────────────────────────────────
    if failures:
        by_inv: dict = {}
        for f in failures:
            by_inv.setdefault(f.split("]")[0][1:], []).append(f)
        print(f"  INVARIANTS: {len(failures)} violation(s) in "
              f"{len(by_inv)} invariant(s)")
        for inv, items in sorted(by_inv.items()):
            print(f"    FAIL {inv}  ({len(items)} case(s))")
            for it in (items if VERBOSE else items[:3]):
                print(f"         {it.split('] ', 1)[1]}")
            if not VERBOSE and len(items) > 3:
                print(f"         ... and {len(items) - 3} more (--verbose)")
    else:
        print(f"  INVARIANTS: all 15 hold across {checked} scenarios")

    # ── snapshot ─────────────────────────────────────────────────────────────
    payload = json.dumps(current, ensure_ascii=False, sort_keys=True, indent=1)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]

    if UPDATE or not SNAPSHOT.exists():
        SNAPSHOT.write_text(payload, encoding="utf-8")
        print(f"\n  SNAPSHOT: {'re-recorded' if UPDATE else 'created'} "
              f"({len(current)} cases, digest {digest})")
        print("  Review the diff before committing — a snapshot nobody reads is "
              "not a safety net.")
        return 1 if failures else 0

    previous = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    changed = [k for k in sorted(set(previous) | set(current))
               if previous.get(k) != current.get(k)]
    if not changed:
        print(f"  SNAPSHOT: identical ({len(current)} cases, digest {digest})")
    else:
        print(f"\n  SNAPSHOT: {len(changed)} case(s) changed — REVIEW REQUIRED")
        for k in (changed if VERBOSE else changed[:8]):
            before, after = previous.get(k), current.get(k)
            print(f"    ~ {k}")
            if before is None:
                print("        NEW case")
            elif after is None:
                print("        REMOVED case")
            else:
                for f in sorted(set(before) | set(after)):
                    if before.get(f) != after.get(f):
                        print(f"        {f}: {before.get(f)!r} -> {after.get(f)!r}")
        if not VERBOSE and len(changed) > 8:
            print(f"    ... and {len(changed) - 8} more (--verbose)")
        print("\n  If these changes are intended:  python test_scenarios.py --update")

    ok = not failures and not changed
    print("\n" + "=" * 68)
    print("RESULT: ALL GREEN" if ok else "RESULT: attention required")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
