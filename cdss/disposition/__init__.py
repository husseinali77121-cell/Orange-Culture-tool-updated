"""Per-drug disposition: every tested drug -> allowed / warned / banned.

    context.py    facts about the patient + culture, computed once
    findings.py   the Finding type and severity ordering
    rules_*.py    one small pure function per clinical rule
    engine.py     runs every rule and picks the outcome by SEVERITY

The engine replaces a 700-line first-match-wins `if ... continue` chain. In
that chain the ORDER of the checks decided the outcome, so a mild rule placed
early silently pre-empted a severe one placed later: a renal-dose-adjustment
warning, checked before the pregnancy block, turned gentamicin in a pregnant
patient into "use with dose adjustment". Here every rule is evaluated and the
most severe finding wins, whatever order the rules are listed in.
"""
from .engine import analyze_antibiotics, evaluate_drug  # noqa: F401
from .rules_organism import is_intrinsically_avoided    # noqa: F401
