"""Run every rule on every drug; the most severe finding decides the list."""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from abx_guidelines import ABX_GUIDELINES

from .alerts import drug_alerts
from .context import Context, DrugCase, build_context
from .findings import BAN, PREG, TAG, WARN, Finding
from .rules_mechanism import rule_ampc_inducible_third_gen, rule_mechanism
from .rules_organism import (rule_d_test, rule_enterococcus_folate,
                             rule_intrinsic_avoided, rule_klebsiella_fosa,
                             rule_mrsa_beta_lactam, rule_staph_penicillinase)
from .rules_patient import (rule_child, rule_nitrofurantoin_renal,
                            rule_pregnancy, rule_renal_adjustment)
from .rules_result import rule_intermediate, rule_not_tested, rule_resistant
from .rules_specimen import rule_urine_only

Rule = Callable[[Context, DrugCase], Optional[Finding]]

# Listing order is ONLY a tie-break: between two findings of EQUAL severity the
# earlier rule supplies the headline reason. It can never demote a more severe
# finding - that is decided by severity alone.
RULES: Sequence[Rule] = (
    rule_resistant,                 # terminal
    rule_intrinsic_avoided,         # terminal
    rule_mrsa_beta_lactam,
    rule_mechanism,
    rule_ampc_inducible_third_gen,
    rule_child,
    rule_d_test,
    rule_staph_penicillinase,
    rule_enterococcus_folate,
    rule_klebsiella_fosa,
    rule_nitrofurantoin_renal,
    rule_renal_adjustment,
    rule_pregnancy,
    rule_urine_only,
    rule_not_tested,
    rule_intermediate,
)


def evaluate_drug(ctx: Context, drug: str) -> Tuple[str, Dict[str, Any], List[Finding]]:
    """-> (bucket, output row, all findings).  bucket is one of
    "allowed" | "warned" | "preg" | "banned"."""
    d = ctx.case(drug)
    findings: List[Finding] = []
    for rule in RULES:
        f = rule(ctx, d)
        if f is None:
            continue
        findings.append(f)
        if f.terminal:
            break

    top = max((f.severity for f in findings), default=TAG)
    primary = next((f for f in findings if f.severity == top), None)
    others = [f for f in findings if f is not primary]
    also = [f.summary() for f in others if f.severity > TAG]
    tags: Dict[str, Any] = {}
    for f in findings:
        if f.severity == TAG:
            tags.update(f.item)

    if top == BAN and primary is not None:
        row = {"name": drug, **primary.item}
        bucket = "banned"
    elif top == PREG and primary is not None:
        row = {"name": drug, **d.info, **tags, **primary.item,
               "sir_category": d.sir or "NT"}
        bucket = "preg"
    elif top == WARN and primary is not None:
        row = {"name": drug, **d.info, **tags, "sir_category": d.sir or "NT",
               **primary.item}
        bucket = "warned"
    else:
        row = {"name": drug, **d.info, "sir_category": d.sir or "NT", **tags}
        bucket = "allowed"

    row["rule"] = primary.code if primary is not None else "allowed"
    if also:
        row["also"] = also
    return bucket, row, findings


def analyze_antibiotics(
    final_drugs: List[str],
    organism_type: str,
    culture_type: str,
    age: int,
    sex: str,
    is_renal: bool,
    cl_cr: float,
    is_preg: bool,
    is_hepatic: bool,
    current_meds: List[str],
    sir_map: Dict[str, str],
    interp_std: str = "EUCAST",
) -> Tuple[List[Dict], List[Dict], List[Dict], List[Dict], List[str]]:
    """Sort the tested drugs into allowed / warned / banned for this patient.

    Returns (allowed, warned, banned, preg_warn_items, alerts) - the same five
    lists, with the same row keys, as before. Each drug lands in exactly one
    list. A row also carries:
        rule   the id of the rule that decided it
        also   other, less severe findings about the same drug (when any)
    """
    ctx = build_context(organism_type, culture_type, age, sex, is_renal, cl_cr,
                        is_preg, is_hepatic, current_meds, sir_map, interp_std)
    buckets: Dict[str, List[Dict]] = {"allowed": [], "warned": [], "preg": [], "banned": []}
    alerts: List[str] = []
    seen = set()
    for drug in final_drugs or []:
        if drug in seen or drug not in ABX_GUIDELINES:
            continue
        seen.add(drug)
        bucket, row, findings = evaluate_drug(ctx, drug)
        buckets[bucket].append(row)
        if not any(f.terminal for f in findings):
            alerts.extend(drug_alerts(ctx, ctx.case(drug)))

    def by_priority(x: Dict) -> Any:
        return x.get("priority", 999)

    return (sorted(buckets["allowed"], key=by_priority),
            sorted(buckets["warned"], key=by_priority),
            buckets["banned"],
            sorted(buckets["preg"], key=by_priority),
            sorted(set(alerts)))
