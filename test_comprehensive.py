#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orange Lab CDSS (COMMERCIAL / streamlit_app.py) — COMPREHENSIVE INVARIANT TEST
============================================================================
streamlit_app.py is a Streamlit MONOLITH whose UI runs at import time, so it
cannot be `import`ed for testing. Instead we AST-EXTRACT its pure decision
functions + tables and exec them in isolation — no Streamlit runtime, no UI.
We then import the real data modules (organism_profile, abx_guidelines) that sit
next to it in the repo for full organism/drug coverage, with a safe fallback so
the core invariants still run even if those modules are momentarily unavailable.

The bugs we fixed all lived in TWO decision functions — predict_esbl (the ESBL
gate) and is_intrinsically_avoided (the Avoid decision) — so we hammer those two
directly across the whole organism × drug space.

Run:  python test_comprehensive.py           |   N_FUZZ=50000 python test_comprehensive.py
Files needed next to it: streamlit_app.py (+ organism_profile.py, abx_guidelines.py)
============================================================================
"""
from __future__ import annotations
import ast, os, sys, random
from typing import Dict, Any, List

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.join(HERE, "streamlit_app.py")
N_FUZZ = int(os.environ.get("N_FUZZ", "8000"))
SEED   = int(os.environ.get("SEED", "1"))

# ── AST-extract the pure logic bundle from the monolith ────────────────────────
_WANT = ["INTRINSIC_RESISTANCE","ESBL_PRODUCERS","AMPC_PRODUCERS","ESBL_MARKERS",
         "CARBAPENEMS","ORGANISM_AVOID_CLASS_MAP","is_esbl_producer",
         "_remove_intrinsic_resistance","predict_esbl","is_intrinsically_avoided"]
def _extract(path, names):
    src = open(path, encoding="utf-8").read(); tree = ast.parse(src); lines = src.splitlines(keepends=True)
    seg = {}
    for n in tree.body:
        nm = getattr(n, "name", None)
        if nm is None and isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name): nm = t.id
        if nm in names and nm not in seg:
            seg[nm] = "".join(lines[n.lineno-1:n.end_lineno])
    return seg

if not os.path.exists(APP):
    print(f"ENVIRONMENT INCOMPLETE — {APP} not found. Put this test next to streamlit_app.py.")
    sys.exit(2)
_seg = _extract(APP, _WANT)

# Real data modules (for full coverage); fall back gracefully if unavailable.
try:    from organism_profile import ORGANISM_PROFILE
except Exception: ORGANISM_PROFILE = {}
try:    from abx_guidelines import ABX_GUIDELINES
except Exception: ABX_GUIDELINES = {}

# INTRINSIC_RESISTANCE moved out of streamlit_app.py into clinical_data.py (it is
# now the single source of truth shared with ast_qa_engine.py), so seed the exec
# namespace with it instead of expecting to slice it out of the monolith.
try:
    from clinical_data import INTRINSIC_RESISTANCE as _CANON_IR
except Exception as _e:
    print(f"ENVIRONMENT INCOMPLETE — clinical_data.py not importable ({_e}).")
    sys.exit(2)

NS: Dict[str, Any] = {"Dict":Dict,"Any":Any,"List":List,"ORGANISM_PROFILE":ORGANISM_PROFILE,
                      "INTRINSIC_RESISTANCE":_CANON_IR}
for k in _WANT:
    if k in _seg: exec(_seg[k], NS)
predict_esbl          = NS["predict_esbl"]
is_intrinsically_avoided = NS["is_intrinsically_avoided"]
is_esbl_producer      = NS["is_esbl_producer"]
INTRINSIC             = NS["INTRINSIC_RESISTANCE"]   # = clinical_data.INTRINSIC_RESISTANCE
MARK                  = NS["ESBL_MARKERS"]

# ── Organism / drug universe (real modules if present, else derived) ───────────
ORGANISMS = list(ORGANISM_PROFILE.keys()) or sorted(
    set(INTRINSIC) | set(NS["ESBL_PRODUCERS"]) | set(NS["AMPC_PRODUCERS"]) | {
        "pseudomonas aeruginosa","acinetobacter baumannii","stenotrophomonas maltophilia",
        "enterococcus faecalis","staphylococcus aureus","escherichia coli"})
DRUGS = list(ABX_GUIDELINES.keys()) or sorted(
    {d for v in INTRINSIC.values() for d in v}
    | set(MARK.get("primary",[])) | set(MARK.get("secondary",[])) | set(MARK.get("medium",[]))
    | set(NS["CARBAPENEMS"]) | {"Ciprofloxacin","Levofloxacin","Gentamicin","Amikacin",
                                "Piperacillin + Tazobactam","Ceftazidime","Cefepime"})
_seen_org, _seen_drug, _seen_mech = set(), set(), set()

def intrinsic_of(org):
    ol=(org or "").lower().strip(); out=set()
    for k,v in INTRINSIC.items():
        if k and (k in ol or ol in k): out.update(v)
    return out

# ════════════════════════════════════════════════════════════════════════════
# INTR-1 — every intrinsic drug is flagged 'avoid' at its decision source
# ════════════════════════════════════════════════════════════════════════════
def test_intrinsic_always_avoided():
    for org in ORGANISMS:
        _seen_org.add(org)
        for drug in sorted(intrinsic_of(org)):
            _seen_drug.add(drug)
            assert is_intrinsically_avoided(org, drug, {"class": ""}) is True, \
                f"[INTR-1] {org}: intrinsic {drug} not flagged avoided"

def test_active_antipseudomonals_not_avoided():
    """Guard the OTHER direction: the anti-pseudomonal agents must NOT be flagged
    intrinsic for P. aeruginosa (else we'd wrongly ban the drugs that work)."""
    for drug in ["Ceftazidime","Cefepime","Ciprofloxacin","Meropenem","Amikacin",
                 "Piperacillin + Tazobactam"]:
        assert is_intrinsically_avoided("Pseudomonas aeruginosa", drug, {"class":""}) is False, \
            f"[INTR-1b] anti-pseudomonal {drug} wrongly flagged intrinsic"

# ════════════════════════════════════════════════════════════════════════════
# ESBL-1 — ESBL only for known producers (exhaustive over every organism)
# ════════════════════════════════════════════════════════════════════════════
def test_esbl_only_for_producers():
    pattern = {"Ceftriaxone":"R","Cefotaxime":"R","Cefepime":"R","Ceftazidime":"R",
               "Cefuroxime":"R","Cephalexin":"R"}
    for org in ORGANISMS:
        prob = predict_esbl(org, pattern).get("probability")
        if prob: _seen_mech.add(prob)
        if not is_esbl_producer(org):
            assert prob not in ("high","moderate"), \
                f"[ESBL-1] non-producer {org} produced ESBL probability '{prob}'"

def test_intrinsic_never_infers_mechanism():
    for org in ORGANISMS:
        intr = {d:"R" for d in intrinsic_of(org)}
        if not intr: continue
        prob = predict_esbl(org, intr).get("probability")
        assert prob in (None, "low"), \
            f"[INTR-2] {org}: resistance to only-intrinsic drugs produced mechanism '{prob}'"

def test_carbapenemase_needs_a_carbapenem():
    for org in ORGANISMS:
        if not (is_esbl_producer(org) or (org or "").lower() in {o.lower() for o in NS["AMPC_PRODUCERS"]}):
            continue
        assert predict_esbl(org, {"Ciprofloxacin":"R","Gentamicin":"R"}).get("probability") != "carbapenemase", \
            f"[CARB-1] {org}: carbapenemase inferred with no carbapenem"

# ════════════════════════════════════════════════════════════════════════════
# Property-based fuzz over predict_esbl (determinism + monotonic-ish gating)
# ════════════════════════════════════════════════════════════════════════════
def test_fuzz_predict_esbl():
    rng = random.Random(SEED)
    for _ in range(N_FUZZ):
        org = rng.choice(ORGANISMS)
        sir = {d: rng.choice(["S","I","R"]) for d in rng.sample(DRUGS, rng.randint(1, min(12,len(DRUGS))))}
        _seen_org.add(org); _seen_drug.update(sir)
        r1 = predict_esbl(org, dict(sir)); r2 = predict_esbl(org, dict(sir))
        assert r1 == r2, f"[DET-1] predict_esbl non-deterministic for {org}"
        # ESBL gate holds on ALL random panels, not just the crafted one
        if not is_esbl_producer(org):
            assert r1.get("probability") not in ("high","moderate"), \
                f"[ESBL-1] non-producer {org} lit up ESBL on random panel {sir}"

def test_edge_inputs_dont_crash():
    for org in ORGANISMS[:6] + ["Totally Unknown sp.", "", "  "]:
        for sir in ({}, {"__nope__":"S"}, {d:"R" for d in DRUGS[:6]}, {d:"S" for d in DRUGS[:6]}):
            try:
                predict_esbl(org, dict(sir))
                for d in list(sir)[:3]:
                    is_intrinsically_avoided(org, d, {"class":""})
            except Exception as e:
                raise AssertionError(f"[ROB] crash on org={org!r} sir={sir}: {e!r}")

# ── Coverage gate ──────────────────────────────────────────────────────────────
def test_coverage_complete():
    missed_org = set(ORGANISMS) - _seen_org
    assert not missed_org, f"[COVERAGE] organisms never exercised: {sorted(missed_org)}"

def _run():
    # Run in DEFINITION order (by source line), NOT alphabetically, so the
    # coverage gate — which must see what every other test exercised — runs last.
    tests = [v for k,v in globals().items() if k.startswith("test_") and callable(v)]
    tests.sort(key=lambda f: f.__code__.co_firstlineno)
    print(f"Extracted {sum(1 for k in _WANT if k in _seg)}/{len(_WANT)} logic symbols | "
          f"Organisms: {len(ORGANISMS)} (ORGANISM_PROFILE={'yes' if ORGANISM_PROFILE else 'derived'}) | "
          f"Drugs: {len(DRUGS)} (ABX_GUIDELINES={'yes' if ABX_GUIDELINES else 'derived'}) | N={N_FUZZ}\n")
    failed=0
    for t in tests:
        try: t(); print(f"  PASS  {t.__name__}")
        except AssertionError as e: failed+=1; print(f"  FAIL  {t.__name__}\n        {e}")
        except Exception as e: failed+=1; print(f"  ERROR {t.__name__}: {e!r}")
    print(f"\nCoverage: {len(_seen_org)}/{len(ORGANISMS)} organisms, {len(_seen_drug)} drugs, mechanisms: {sorted(_seen_mech)}")
    print("RESULT:", "ALL GREEN — invariants hold across the culture space." if not failed
          else f"{failed} invariant(s) VIOLATED.")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(_run())
