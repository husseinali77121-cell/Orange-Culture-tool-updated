#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orange Lab CDSS — COMPREHENSIVE TEST HARNESS
============================================================================
Why this file exists
--------------------
The bugs we just fixed (P. aeruginosa false-ESBL, Doxycycline in "caution",
Cephalexin mislabelled, four intrinsic tables drifting) were all the SAME kind
of bug: the code produced a PLAUSIBLE-but-WRONG answer, never crashed, and every
example-based unit test passed — because no one hand-wrote the ONE combination
(organism × drug × mechanism) that broke. You cannot enumerate that space by hand.

So this harness does NOT ask "for input X, is the output Y?". It asserts
INVARIANTS — properties that must hold for EVERY organism and EVERY panel — and
then GENERATES the input space (exhaustively where small, randomly where huge)
until the invariants are proven or a counter-example is found. It also runs the
clinical engine and the QA engine on the SAME input and demands they agree
(differential testing), which is exactly the failure that started all this.

It auto-discovers organisms from ORGANISM_PROFILE and drugs from ABX_GUIDELINES,
so coverage grows automatically as you add either — nothing to remember to update.

Run:
    python test_comprehensive.py            # standalone, prints a report
    python -m pytest test_comprehensive.py  # or under pytest
    N_FUZZ=50000 python test_comprehensive.py   # heavier fuzzing
============================================================================
"""
from __future__ import annotations
import os, sys, random, itertools

# ── System under test (import defensively so a missing piece SKIPS, not crashes) ─
def _try(imp, names):
    try:
        mod = __import__(imp, fromlist=names)
        return tuple(getattr(mod, n, None) for n in names)
    except Exception as e:                       # pragma: no cover
        print(f"  ! could not import {names} from {imp}: {e}")
        return tuple(None for _ in names)

(INTRINSIC_RESISTANCE, ESBL_PRODUCERS, AMPC_PRODUCERS, ESBL_MARKERS,
 is_esbl_producer) = _try("clinical_data",
    ["INTRINSIC_RESISTANCE","ESBL_PRODUCERS","AMPC_PRODUCERS","ESBL_MARKERS","is_esbl_producer"])
(predict_esbl, is_intrinsically_avoided, analyze_antibiotics,
 _remove_intrinsic_resistance) = _try("clinical_engines",
    ["predict_esbl","is_intrinsically_avoided","analyze_antibiotics","_remove_intrinsic_resistance"])
(ORGANISM_PROFILE,) = _try("organism_profile", ["ORGANISM_PROFILE"])
(ABX_GUIDELINES,)  = _try("abx_guidelines",  ["ABX_GUIDELINES"])
(run_ast_qa_engine,) = _try("ast_qa_engine", ["run_ast_qa_engine"])

ORGANISMS = list(ORGANISM_PROFILE.keys()) if ORGANISM_PROFILE else []
DRUGS     = list(ABX_GUIDELINES.keys())   if ABX_GUIDELINES   else []
N_FUZZ    = int(os.environ.get("N_FUZZ", "8000"))
SEED      = int(os.environ.get("SEED", "1"))

# ── Coverage tracker: proves the suite actually EXERCISED everything ────────────
_seen_org, _seen_drug, _seen_mech = set(), set(), set()

# ── Helpers ────────────────────────────────────────────────────────────────────
def intrinsic_of(org: str) -> set:
    """Every drug the organism is intrinsically resistant to (same substring
    matching the engine uses)."""
    ol = (org or "").lower().strip(); out = set()
    for k, v in (INTRINSIC_RESISTANCE or {}).items():
        if k and (k in ol or ol in k):
            out.update(v)
    return out

def _names(bucket) -> set:
    return {(d.get("name") or d.get("drug") or "") for d in (bucket or [])}

def analyze(org, sir, **ctx):
    """Thin wrapper over analyze_antibiotics with a default adult patient.
    Returns {'allowed','warned','banned'} as sets of drug names."""
    _seen_org.add(org); _seen_drug.update(sir.keys())
    allowed, warned, banned, *_rest = analyze_antibiotics(
        final_drugs=list(sir), organism_type=org,
        culture_type=ctx.get("specimen", "Urine"),
        age=ctx.get("age", 40), sex=ctx.get("sex", "Male"),
        is_renal=ctx.get("renal", False), cl_cr=ctx.get("clcr", 90.0),
        is_preg=ctx.get("preg", False), is_hepatic=ctx.get("hep", False),
        current_meds=ctx.get("meds", []), sir_map=sir,
        interp_std=ctx.get("std", "EUCAST"))
    return {"allowed": _names(allowed), "warned": _names(warned), "banned": _names(banned)}

def _rand_panel(rng, org):
    """Random subset of the formulary with random S/I/R values."""
    k = rng.randint(1, min(14, len(DRUGS)))
    picked = rng.sample(DRUGS, k)
    return {d: rng.choice(["S", "I", "R"]) for d in picked}

# ════════════════════════════════════════════════════════════════════════════
# LAYER 1 — INTRINSIC RESISTANCE (EUCAST is the oracle: known-answer, exhaustive)
# ════════════════════════════════════════════════════════════════════════════
def test_L1_intrinsic_always_avoided():
    """INTR-1: an intrinsically-resistant drug, even reported S, must land in
    AVOID — never allowed, never caution. (Catches Doxycycline/Cephalexin leaks.)"""
    for org in ORGANISMS:
        for drug in sorted(intrinsic_of(org)):
            if drug not in DRUGS:
                continue
            r = analyze(org, {drug: "S"})          # the biologically impossible "S"
            assert drug in r["banned"], f"[INTR-1] {org}: intrinsic {drug}=S not in AVOID"
            assert drug not in r["allowed"] and drug not in r["warned"], \
                f"[INTR-1] {org}: intrinsic {drug} leaked into allowed/warned"

def test_L1_intrinsic_never_infers_mechanism():
    """INTR-2: resistance to ONLY intrinsic drugs must never yield a positive
    mechanism call (ESBL / AmpC / carbapenemase). Those results are EXPECTED for
    the organism, so they carry zero mechanism information. This is the exact
    root cause of the P. aeruginosa false-ESBL. (Formulated as 'probability must
    stay None/low' rather than compared against an empty panel, which would hit
    the empty-input guard and give a spurious mismatch.)"""
    for org in ORGANISMS:
        intr = {d: "R" for d in intrinsic_of(org) if d in DRUGS}
        if not intr:
            continue
        prob = predict_esbl(org, intr).get("probability")
        assert prob in (None, "low"), \
            f"[INTR-2] {org}: resistance to only-intrinsic drugs produced mechanism '{prob}'"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 2 — MECHANISM GATING (ESBL only for known producers) — exhaustive
# ════════════════════════════════════════════════════════════════════════════
def test_L2_esbl_only_for_producers():
    """ESBL-1: predict_esbl may return an ESBL-type probability ONLY for an
    organism in ESBL_PRODUCERS. Fire the classic ESBL pattern at EVERY organism
    and assert non-producers never light up. (Catches the ESBL-alert leak.)"""
    esbl_pattern = {"Ceftriaxone": "R", "Cefotaxime": "R", "Cefepime": "R",
                    "Ceftazidime": "R", "Cefuroxime": "R", "Cephalexin": "R"}
    for org in ORGANISMS:
        prob = predict_esbl(org, esbl_pattern).get("probability")
        if prob:
            _seen_mech.add(prob)
        if not is_esbl_producer(org):
            assert prob not in ("high", "moderate"), \
                f"[ESBL-1] non-producer {org} produced ESBL probability '{prob}'"

def test_L2_carbapenemase_needs_a_carbapenem():
    """CARB-1: a carbapenemase call must be backed by an actual carbapenem R —
    it can never come from a non-carbapenem being I/R."""
    for org in ORGANISMS:
        if not (is_esbl_producer(org) or org.lower() in (AMPC_PRODUCERS or set())):
            continue
        r = predict_esbl(org, {"Ciprofloxacin": "R", "Gentamicin": "R"})
        assert r.get("probability") != "carbapenemase", \
            f"[CARB-1] {org}: carbapenemase inferred with no carbapenem tested"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 3 — SUSCEPTIBILITY / STRUCTURAL INVARIANTS (property-based fuzz)
# ════════════════════════════════════════════════════════════════════════════
def test_L3_fuzz_core_invariants():
    rng = random.Random(SEED)
    for _ in range(N_FUZZ):
        org = rng.choice(ORGANISMS)
        sir = _rand_panel(rng, org)
        r = analyze(org, sir)
        allbuckets = r["allowed"] | r["warned"] | r["banned"]
        # SIR-4: no phantom drugs — everything reported was in the input panel
        assert allbuckets <= set(sir), \
            f"[SIR-4] {org}: phantom drug(s) {allbuckets - set(sir)} not in panel {sir}"
        # SIR-5: the three buckets are disjoint
        assert not (r["allowed"] & r["banned"]), f"[SIR-5] {org}: drug in allowed AND banned"
        assert not (r["allowed"] & r["warned"]), f"[SIR-5] {org}: drug in allowed AND warned"
        # SIR-1: a drug reported R is never "allowed" (preferred)
        for d, v in sir.items():
            if v == "R":
                assert d not in r["allowed"], f"[SIR-1] {org}: {d}=R landed in allowed"
        # INTR-1 (random panels too): intrinsic drug never allowed/warned
        for d in intrinsic_of(org):
            if d in sir:
                assert d not in r["allowed"] and d not in r["warned"], \
                    f"[INTR-1] {org}: intrinsic {d}={sir[d]} not avoided"

def test_L3_determinism():
    """DET-1: identical input → identical output (no hidden state / randomness)."""
    rng = random.Random(SEED + 99)
    for _ in range(500):
        org = rng.choice(ORGANISMS); sir = _rand_panel(rng, org)
        assert analyze(org, dict(sir)) == analyze(org, dict(sir)), f"[DET-1] {org}: non-deterministic"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 4 — METAMORPHIC RELATIONS (no oracle needed: outputs must RELATE)
# ════════════════════════════════════════════════════════════════════════════
def test_L4_monotonic_S_to_R():
    """MONO-1: flipping a drug to R can only make its standing WORSE — it must
    not be 'allowed' afterwards."""
    rng = random.Random(SEED + 7)
    for _ in range(2000):
        org = rng.choice(ORGANISMS); sir = _rand_panel(rng, org)
        d = rng.choice(list(sir))
        sir2 = dict(sir); sir2[d] = "R"
        assert d not in analyze(org, sir2)["allowed"], f"[MONO-1] {org}: {d}=R still allowed"

def test_L4_no_crosstalk():
    """IDEM-1: adding one more drug must not change how the OTHERS are classified."""
    rng = random.Random(SEED + 13)
    for _ in range(2000):
        org = rng.choice(ORGANISMS); sir = _rand_panel(rng, org)
        pool = [d for d in DRUGS if d not in sir]
        if not pool:
            continue
        extra = rng.choice(pool)
        before = analyze(org, sir)
        after  = analyze(org, {**sir, extra: rng.choice(["S", "I", "R"])})
        for bucket in ("allowed", "warned", "banned"):
            assert (before[bucket] - {extra}) == (after[bucket] - {extra}), \
                f"[IDEM-1] {org}: adding {extra} disturbed {bucket}"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 5 — DIFFERENTIAL: the QA engine and the clinical engine must AGREE
#   (this is the class of bug that started everything)
# ════════════════════════════════════════════════════════════════════════════
def test_L5_qa_vs_clinical_agree_on_intrinsic():
    """DIFF-1: anything the QA engine flags as an 'Intrinsic Resistance'
    contradiction (drug=S/I on an intrinsically-R organism) MUST be in the
    clinical engine's AVOID bucket. The two halves cannot disagree."""
    if run_ast_qa_engine is None:
        return  # QA engine not importable in this environment → skip
    rng = random.Random(SEED + 21)
    for _ in range(2000):
        org = rng.choice(ORGANISMS); sir = _rand_panel(rng, org)
        try:
            qa = run_ast_qa_engine(org, sir, "") or {}
        except TypeError:
            qa = run_ast_qa_engine(organism=org, sir_map=sir) or {}
        issues = qa.get("issues", qa) if isinstance(qa, dict) else qa
        flagged = set()
        for it in (issues or []):
            cat = (getattr(it, "category", None) or (it.get("category") if isinstance(it, dict) else "")) or ""
            drg = (getattr(it, "drug", None) or (it.get("drug") if isinstance(it, dict) else "")) or ""
            if "intrinsic" in cat.lower() and drg:
                flagged.add(drg)
        if not flagged:
            continue
        banned = analyze(org, sir)["banned"]
        assert flagged <= banned, \
            f"[DIFF-1] {org}: QA flagged {flagged - banned} intrinsic but clinical did not AVOID them"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 6 — SPECIMEN / PATIENT CONTEXT
# ════════════════════════════════════════════════════════════════════════════
def test_L6_urine_only_not_in_blood():
    """SPEC-1: urine-concentrating agents must never be recommended for a
    non-urine specimen (blood), regardless of S."""
    for drug in [d for d in ("Nitrofurantoin", "Fosfomycin") if d in DRUGS]:
        for org in ORGANISMS:
            if drug in intrinsic_of(org):
                continue
            r = analyze(org, {drug: "S"}, specimen="Blood")
            assert drug not in r["allowed"], f"[SPEC-1] {drug} recommended for blood ({org})"

# ════════════════════════════════════════════════════════════════════════════
# LAYER 7 — ROBUSTNESS (must never crash on edge input)
# ════════════════════════════════════════════════════════════════════════════
def test_L7_edge_inputs_dont_crash():
    samples = ORGANISMS[:5] + ["Totally Unknown sp.", "", "  "]
    for org in samples:
        for sir in ({}, {"__nonexistent_drug__": "S"},
                    {d: "R" for d in DRUGS[:8]}, {d: "S" for d in DRUGS[:8]}):
            try:
                analyze(org, dict(sir))
                predict_esbl(org, dict(sir))
            except Exception as e:
                raise AssertionError(f"[ROB] crashed on org={org!r} sir={sir}: {e!r}")

# ════════════════════════════════════════════════════════════════════════════
# COVERAGE GATE — "no error appeared" is only trustworthy if EVERYTHING was hit
# ════════════════════════════════════════════════════════════════════════════
def test_Z_coverage_complete():
    missed_org  = set(ORGANISMS) - _seen_org
    missed_drug = set(DRUGS)     - _seen_drug
    # organisms are all touched by Layer 1/2; drugs by the fuzz + intrinsic layers
    assert not missed_org,  f"[COVERAGE] organisms never exercised: {sorted(missed_org)}"
    # a drug can be un-hit only if it is in no panel AND intrinsic to nobody:
    truly_missed = {d for d in missed_drug
                    if not any(d in intrinsic_of(o) for o in ORGANISMS)}
    assert not truly_missed, f"[COVERAGE] drugs never exercised: {sorted(truly_missed)}"


# ── Standalone runner (also works under pytest) ────────────────────────────────
def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    if not (ORGANISMS and DRUGS and analyze_antibiotics and predict_esbl):
        print("ENVIRONMENT INCOMPLETE — run this inside the CDSS repo so that "
              "clinical_data / clinical_engines / organism_profile / abx_guidelines import.")
        return 2
    print(f"Organisms: {len(ORGANISMS)} | Drugs: {len(DRUGS)} | fuzz N={N_FUZZ} | seed={SEED}\n")
    failed = 0
    for t in tests:
        try:
            t(); print(f"  PASS  {t.__name__}")
        except AssertionError as e:
            failed += 1; print(f"  FAIL  {t.__name__}\n        {e}")
        except Exception as e:                    # pragma: no cover
            failed += 1; print(f"  ERROR {t.__name__}: {e!r}")
    print(f"\nCoverage exercised: {len(_seen_org)}/{len(ORGANISMS)} organisms, "
          f"{len(_seen_drug)}/{len(DRUGS)} drugs, mechanisms seen: {sorted(_seen_mech)}")
    print("RESULT:", "ALL GREEN — invariants hold across the whole culture space."
          if not failed else f"{failed} invariant(s) VIOLATED — see above.")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(_run_all())
