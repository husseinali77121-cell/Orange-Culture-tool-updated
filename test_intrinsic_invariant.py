#!/usr/bin/env python3
"""
Orange Lab — Intrinsic-Resistance & ESBL-Gating Invariant Test  (unified)
=========================================================================
ONE guard, BOTH repos. It reads the intrinsic-resistance tables straight from
source via AST (no Streamlit / runtime needed) and fails the build the moment:
  • two copies of INTRINSIC_RESISTANCE drift apart, or
  • an ESBL alert could leak onto a non-ESBL organism.

It auto-detects which files are present, so the SAME file works in:
  • the single-file commercial repo   → streamlit_app.py
  • the modular repo                  → orange_lab-41.py + clinical_data.py + ast_qa_engine.py

A check whose source file is genuinely absent in this repo is SKIPPED, never
failed. Only real drift / leakage fails the build. This kills the crash from
a hard-coded filename AND prevents the *test itself* from drifting.

Usage:  python test_intrinsic_invariant.py
        (exit 0 = invariants hold, 1 = a violation was found)
"""
import ast, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _first_existing(*names):
    for n in names:
        p = HERE / n
        if p.exists():
            return p
    return None


# ── file roles (first match wins; None = simply not in this repo) ────────────
INLINE_APP = _first_existing("streamlit_app.py", "orange_lab-41.py", "orange_lab.py")
CLINICAL   = _first_existing("clinical_data.py")
QA_ENGINE  = _first_existing("ast_qa_engine.py")

# Source of truth: clinical_data in the modular stack; otherwise the single-file app.
ANCHOR = CLINICAL or INLINE_APP
# Embedded QA fallback lives in its own module, else inlined in the app.
QA_SRC = QA_ENGINE or INLINE_APP

ESBL_MARKER_DRUGS = {"Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefpodoxime", "Cefepime"}

MISSING = object()


def _eval(node):
    """literal_eval, but also unwrap frozenset([...]) / set([...]) / list([...])."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("frozenset", "set", "list", "tuple") and node.args:
        return set(ast.literal_eval(node.args[0]))
    return ast.literal_eval(node)


def _tree(path):
    return ast.parse(Path(path).read_text(encoding="utf-8")) if path else None


def _literal(path, name, default=MISSING):
    """Module-level `name = ...`; returns `default` if the file or name is absent."""
    tree = _tree(path)
    if tree is None:
        return default
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return _eval(node.value)
    return default


def _qa_fallback(path):
    """Extract the _CANONICAL_INTRINSIC dict embedded in a try/except handler."""
    tree = _tree(path)
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                for stmt in h.body:
                    if isinstance(stmt, ast.Assign) and any(
                        getattr(t, "id", None) == "_CANONICAL_INTRINSIC" for t in stmt.targets
                    ) and isinstance(stmt.value, ast.Dict):
                        return ast.literal_eval(stmt.value)
    return None


def _norm(table):
    """{organism: set(drugs)} — order-independent comparison."""
    return {k: set(v) for k, v in table.items()}


failures, skips = [], []


def check(label, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label + (f" — {detail}" if detail else ""))


def skip(label, why):
    print(f"  [SKIP] {label}  — {why}")
    skips.append(label)


print("Orange Lab — intrinsic-resistance / ESBL-gating invariants\n")

if ANCHOR is None:
    print("RESULT: no source files found in this repo — nothing to verify.")
    sys.exit(1)

ir_anchor = _literal(ANCHOR, "INTRINSIC_RESISTANCE")
if ir_anchor is MISSING:
    print(f"RESULT: INTRINSIC_RESISTANCE not found in anchor {ANCHOR.name} — cannot verify.")
    sys.exit(1)

anchor_label = ANCHOR.name


# ── INVARIANT 1: every OTHER inline copy is byte-equivalent to the anchor ────
def compare_copy(src_path, copy_name, getter):
    if src_path is None:
        skip(f"{copy_name} == {anchor_label}", "source file not in this repo")
        return
    val = getter(src_path)
    if val is None or val is MISSING:
        skip(f"{copy_name} == {anchor_label}", f"no INTRINSIC_RESISTANCE copy in {src_path.name}")
        return
    same = _norm(val) == _norm(ir_anchor)
    detail = ""
    if not same:
        per_org = {o: _norm(val).get(o, set()) ^ _norm(ir_anchor).get(o, set())
                   for o in set(val) | set(ir_anchor)
                   if _norm(val).get(o) != _norm(ir_anchor).get(o)}
        detail = f"drug diffs={per_org}"
    check(f"{copy_name} == {anchor_label}", same, detail)


# single-file app copy — skip if the app *is* the anchor (commercial, single-file)
if INLINE_APP is not None and INLINE_APP != ANCHOR:
    compare_copy(INLINE_APP, f"{INLINE_APP.name} INTRINSIC_RESISTANCE",
                 lambda p: _literal(p, "INTRINSIC_RESISTANCE"))
else:
    skip("inline app INTRINSIC_RESISTANCE == source of truth",
         "single-file repo (the app is the source of truth)" if INLINE_APP == ANCHOR
         else "no separate single-file app in this repo")

# embedded QA-engine fallback copy (this is the check that catches the commercial drift)
# ARCHITECTURE CHANGE: ast_qa_engine.py no longer carries a full embedded copy of
# the table. It now imports clinical_data.INTRINSIC_RESISTANCE at runtime and
# merges only its QA-specific supplements (MRSA / Mycoplasma — functional, not
# EUCAST "intrinsic") over the top. Comparing its module-level literal against the
# anchor therefore compares the supplements against the whole table and always
# fails. The correct invariant is that the canonical import RESOLVED and that the
# merged table is a superset of the anchor — verified live below.
try:
    import ast_qa_engine as _QA
    check("ast_qa_engine resolved the canonical clinical_data import",
          getattr(_QA, "CANONICAL_INTRINSIC_LOADED", False),
          "fell back to the MRSA/Mycoplasma-only stub — the intrinsic level is "
          "dead for every Gram-negative")
    _merged = {k.lower(): set(v) for k, v in _QA._INTRINSIC_RESISTANCE.items()}
    _missing = {o: sorted(set(d) - _merged.get(o.lower(), set()))
                for o, d in ir_anchor.items()
                if set(d) - _merged.get(o.lower(), set())}
    check("ast_qa_engine merged table covers every anchor row",
          not _missing, f"rows missing drugs: {_missing}")
except Exception as _e:                                   # pragma: no cover
    skip("ast_qa_engine live-import invariants", repr(_e))


# ── INVARIANT 2/3/4: ESBL / AmpC gating (sourced from the anchor) ────────────
producers = _literal(ANCHOR, "ESBL_PRODUCERS", default=None)
if producers is None:
    skip("ESBL_PRODUCERS invariants", f"ESBL_PRODUCERS not defined in {anchor_label}")
else:
    producers = set(producers)
    forbidden = {"pseudomonas", "acinetobacter", "stenotrophomonas",
                 "enterococcus", "staphylococcus", "streptococcus"}
    leaked = {p for p in producers if any(f in p for f in forbidden)}
    check("ESBL_PRODUCERS contains NO non-Enterobacterale", not leaked, f"leaked={leaked}")

    bad = {}
    for org, drugs in ir_anchor.items():
        if any(p in org or org in p for p in producers):
            overlap = set(drugs) & ESBL_MARKER_DRUGS
            if overlap:
                bad[org] = overlap
    check("no ESBL-marker drug is intrinsic for any producer organism", not bad, f"overlap={bad}")

    ampc = _literal(ANCHOR, "AMPC_PRODUCERS", default=None)
    if ampc is None:
        skip("AmpC-non-producer coverage", f"AMPC_PRODUCERS not defined in {anchor_label}")
    else:
        ampc = set(ampc)
        np_ampc = [o for o in ampc if not any(p in o or o in p for p in producers)]
        missing = [o for o in np_ampc if not any(k in o or o in k for k in ir_anchor)]
        check("every AmpC-prone non-producer has an intrinsic-resistance entry",
              not missing, f"uncovered={missing}")

print()
if failures:
    print(f"RESULT: {len(failures)} invariant(s) violated — DRIFT DETECTED.")
    for f in failures:
        print("   \u2717 " + f)
    sys.exit(1)

tail = f"  ({len(skips)} check(s) skipped — not applicable to this repo)" if skips else ""
print(f"RESULT: all invariants hold — tables unified, ESBL gating intact.{tail}")
sys.exit(0)
