#!/usr/bin/env python3
"""
Orange Lab — Intrinsic-Resistance & ESBL-Gating Invariant Test
==============================================================
Run in CI. It fails the build the moment the four copies of intrinsic-resistance
knowledge drift apart, or the moment an ESBL alert can leak onto a non-ESBL
organism. This is the guard that makes "everything stays unified" true
BY CONSTRUCTION instead of by discipline.

Usage:  python test_intrinsic_invariant.py
        (exit code 0 = all invariants hold, 1 = a violation was found)

It reads the tables straight from source via AST, so it needs no heavy imports
and no Streamlit/runtime environment.
"""
import ast, sys, os

HERE = os.path.dirname(os.path.abspath(__file__))
# REPO-AGNOSTIC. This suite is shared by two repos that do NOT hold the same
# files: the commercial single-file build ships streamlit_app.py, the Orange Lab
# modular build does not. Hard-coding the commercial path made this test die with
# FileNotFoundError on the modular repo before a single invariant ran. Absent
# files are SKIPPED and reported; a file that exists is always checked.
def _first_existing(*names):
    for n in names:
        p = os.path.join(HERE, n)
        if os.path.exists(p):
            return p
    return None

COMMERCIAL = _first_existing("streamlit_app.py")      # inline copy (single-file deploy)
CLINICAL   = os.path.join(HERE, "clinical_data.py")   # source of truth (modular stack)
QA_ENGINE  = os.path.join(HERE, "ast_qa_engine.py")   # embedded standalone fallback

# ESBL markers and the set of organisms allowed to carry an ESBL result.
ESBL_MARKER_DRUGS = {"Ceftriaxone", "Cefotaxime", "Ceftazidime", "Cefpodoxime", "Cefepime"}


def _eval(node):
    """literal_eval, but also unwrap frozenset([...]) / set([...]) / list([...])."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("frozenset", "set", "list", "tuple") and node.args:
        return set(ast.literal_eval(node.args[0]))
    return ast.literal_eval(node)


def _literal(path, name):
    """Return the value of a module-level assignment `name = ...`."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == name for t in node.targets
        ):
            return _eval(node.value)
    raise AssertionError(f"{name} not found in {os.path.basename(path)}")


def _norm(table):
    """{organism: set(drugs)} — order-independent comparison."""
    return {k: set(v) for k, v in table.items()}


failures = []


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label + (f" — {detail}" if detail else ""))


print("Orange Lab — intrinsic-resistance / ESBL-gating invariants\n")

# ── INVARIANT 1: the two independent copies are byte-equivalent ──────────────
ir_clin = _literal(CLINICAL,  "INTRINSIC_RESISTANCE")
ir_comm = _literal(COMMERCIAL, "INTRINSIC_RESISTANCE") if COMMERCIAL else None
if ir_comm is None:
    print("  [SKIP] commercial INTRINSIC_RESISTANCE == clinical_data "
          "— streamlit_app.py not in this repo (modular build)")
    ir_comm = ir_clin          # neutral value; the two checks below become no-ops
same = _norm(ir_comm) == _norm(ir_clin)
diff = ""
if not same:
    only_c = set(_norm(ir_comm)) - set(_norm(ir_clin))
    only_m = set(_norm(ir_clin)) - set(_norm(ir_comm))
    per_org = {o: _norm(ir_comm).get(o, set()) ^ _norm(ir_clin).get(o, set())
               for o in set(ir_comm) | set(ir_clin)
               if _norm(ir_comm).get(o) != _norm(ir_clin).get(o)}
    diff = f"orgs only in commercial={only_c}, only in clinical={only_m}, drug diffs={per_org}"
check("commercial INTRINSIC_RESISTANCE == clinical_data INTRINSIC_RESISTANCE", same, diff)
check("both tables cover the same organism set",
      set(ir_comm) == set(ir_clin), f"symdiff={set(ir_comm) ^ set(ir_clin)}")

# ── INVARIANT 1b: QA-engine embedded standalone fallback == clinical_data ────
def _qa_fallback(path):
    """Extract the _CANONICAL_INTRINSIC dict embedded in ast_qa_engine's except."""
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                for stmt in h.body:
                    if isinstance(stmt, ast.Assign) and any(
                        getattr(t, "id", None) == "_CANONICAL_INTRINSIC" for t in stmt.targets
                    ) and isinstance(stmt.value, ast.Dict):
                        return ast.literal_eval(stmt.value)
    return None
def _qa_import_raises(path):
    """True if the except branch RAISES instead of degrading to an empty table.

    Two designs are legitimate and this invariant accepts both:
      * commercial single-file build -> embeds a full copy (checked for drift)
      * modular build                -> refuses to start without clinical_data
    What is NEVER acceptable is the third option that actually shipped:
    `_CANONICAL_INTRINSIC = {}`, which silently disables every intrinsic check.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for h in node.handlers:
                if any(isinstance(st, ast.Raise) for st in ast.walk(h)):
                    return True
    return False

qa_fb = _qa_fallback(QA_ENGINE)
if qa_fb is None and _qa_import_raises(QA_ENGINE):
    check("ast_qa_engine refuses to start without clinical_data (no silent-empty table)",
          True)
else:
    check("ast_qa_engine embedded fallback == clinical_data (standalone safety)",
          qa_fb is not None and _norm(qa_fb) == _norm(ir_clin),
          "QA fallback missing, drifted, or silently empty")

# ── INVARIANT 2: ESBL_PRODUCERS is Enterobacterales-only (no non-fermenters) ─
producers = set(_literal(CLINICAL, "ESBL_PRODUCERS"))
forbidden = {"pseudomonas", "acinetobacter", "stenotrophomonas",
             "enterococcus", "staphylococcus", "streptococcus"}
leaked = {p for p in producers if any(f in p for f in forbidden)}
check("ESBL_PRODUCERS contains NO non-Enterobacterale", not leaked, f"leaked={leaked}")

# ── INVARIANT 3: for a PRODUCER, its intrinsic drugs are not ESBL markers ────
# (else resistance you already expect would be read as an ESBL signal)
bad = {}
for org, drugs in ir_clin.items():
    if any(p in org or org in p for p in producers):
        overlap = set(drugs) & ESBL_MARKER_DRUGS
        # Ceftazidime is an anti-pseudomonal marker; it is legitimately intrinsic
        # for a few Gram-positives but those are not producers, so any overlap on
        # a producer is a real problem.
        if overlap:
            bad[org] = overlap
check("no ESBL-marker drug is intrinsic for any producer organism", not bad, f"overlap={bad}")

# ── INVARIANT 4: every AmpC-prone NON-producer must be intrinsic-listed so its
#    expected cephalosporin resistance can never be mistaken for a mechanism ──
ampc = set(_literal(CLINICAL, "AMPC_PRODUCERS"))
np_ampc = [o for o in ampc if not any(p in o or o in p for p in producers)]
missing_cov = [o for o in np_ampc
               if not any(k in o or o in k for k in ir_clin)]
check("every AmpC-prone non-producer has an intrinsic-resistance entry",
      not missing_cov, f"uncovered={missing_cov}")

print()
if failures:
    print(f"RESULT: {len(failures)} invariant(s) violated — DRIFT DETECTED.")
    for f in failures:
        print("   ✗ " + f)
    sys.exit(1)
print("RESULT: all invariants hold — tables unified, ESBL gating intact.")
sys.exit(0)
