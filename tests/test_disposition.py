"""The drug-disposition engine: each rule on its own, then the engine as a whole."""
import itertools
import random

import pytest

from abx_guidelines import ABX_GUIDELINES
from ast_reportability import check_reportability
from organism_profile import ORGANISM_PROFILE
from cdss import drugs as D
from cdss.disposition import analyze_antibiotics, engine, is_intrinsically_avoided
from cdss.disposition.context import build_context
from cdss.disposition.findings import BAN, PREG, WARN

ALL_DRUGS = list(ABX_GUIDELINES)
SPECIMENS = ["Urine", "Blood", "Sputum", "Wound Swab", "Pus", "Stool", "CSF"]


def run(sir, org="E. coli", spec="Urine", age=30, sex="Female", renal=False,
        crcl=90.0, preg=False, hepatic=False, meds=(), std="CLSI", drugs=None):
    a, w, b, p, alerts = analyze_antibiotics(
        list(drugs if drugs is not None else sir), org, spec, age, sex, renal, crcl,
        preg, hepatic, (list(meds) if meds is not None else None), sir, std)
    where = {}
    for name, rows in (("allowed", a), ("warned", w), ("banned", b), ("preg", p)):
        for r in rows:
            assert r["name"] not in where, f"{r['name']} is in two lists"
            where[r["name"]] = (name, r)
    return where, alerts


def bucket(where, drug):
    return where[drug][0]


def rule(where, drug):
    return where[drug][1]["rule"]


# ── result rules ──────────────────────────────────────────────────────────
def test_resistant_is_banned_whatever_the_spelling():
    for v in ("R", "r", "Resistant", " R "):
        w, _ = run({"Ciprofloxacin": v})
        assert bucket(w, "Ciprofloxacin") == "banned" and rule(w, "Ciprofloxacin") == "resistant"


def test_intrinsic_r_is_tagged_apart_from_acquired_r():
    w, _ = run({"Clindamycin": "R", "Ciprofloxacin": "R"})
    assert w["Clindamycin"][1]["category"] == "intrinsic"
    assert w["Ciprofloxacin"][1]["category"] == "resistant"


def test_untested_drug_is_never_an_option():
    w, _ = run({}, drugs=["Ciprofloxacin"])
    assert bucket(w, "Ciprofloxacin") == "warned" and rule(w, "Ciprofloxacin") == "not_tested"


def test_unknown_drug_names_are_ignored_and_duplicates_collapse():
    w, _ = run({"Ciprofloxacin": "S"}, drugs=["Ciprofloxacin", "Ciprofloxacin", "Nosuchdrug"])
    assert list(w) == ["Ciprofloxacin"]


def test_intermediate_depends_on_the_standard():
    w, _ = run({"Ciprofloxacin": "I"}, std="EUCAST")
    assert bucket(w, "Ciprofloxacin") == "allowed"
    assert w["Ciprofloxacin"][1]["sir_note"] == "increased_exposure"
    w, _ = run({"Ciprofloxacin": "I"}, std="CLSI")
    assert bucket(w, "Ciprofloxacin") == "warned"
    assert w["Ciprofloxacin"][1]["warning_reason"] == "intermediate_culture"
    assert w["Ciprofloxacin"][1]["sir_category"] == "I"


# ── organism rules ────────────────────────────────────────────────────────
def test_profile_avoid_list_is_matched_exactly_not_by_substring():
    # "Ampicillin" on the avoid list must not take Ampicillin/Sulbactam with it
    assert is_intrinsically_avoided("H. influenzae", "Ampicillin")
    assert not is_intrinsically_avoided("H. influenzae", "Ampicillin/Sulbactam")
    assert is_intrinsically_avoided("Moraxella catarrhalis", "Amoxicillin")
    assert not is_intrinsically_avoided("Moraxella catarrhalis", "Amoxicillin + Clavulanic acid")
    # ...and an inhibitor combination on the list must not take the plain drug
    assert is_intrinsically_avoided("VRE", "Ampicillin/Sulbactam")
    assert not is_intrinsically_avoided("VRE", "Ampicillin")
    # "Ampicillin (alone)" means ampicillin
    assert is_intrinsically_avoided("Klebsiella spp.", "Ampicillin")


def test_profile_class_words_cover_the_whole_class():
    for d in ("Ceftriaxone", "Cefoperazone + Sulbactam", "Cefoxitin"):
        assert is_intrinsically_avoided("Listeria monocytogenes", d), d
    for d in ("Amoxicillin + Clavulanic acid", "Meropenem", "Aztreonam", "Cefepime"):
        assert is_intrinsically_avoided("Mycoplasma spp.", d), d
    assert is_intrinsically_avoided("Proteus mirabilis", "Doxycycline")
    assert not is_intrinsically_avoided("Mycoplasma spp.", "Doxycycline")


def test_empty_organism_bans_nothing_by_intrinsic():
    w, _ = run({"Ampicillin": "S", "Ceftriaxone": "S"}, org="")
    assert bucket(w, "Ampicillin") == "allowed" and bucket(w, "Ceftriaxone") == "allowed"


def test_engine_agrees_with_qc_on_expected_resistance():
    """Whatever ast_reportability calls intrinsic, the engine must never offer."""
    for org in ORGANISM_PROFILE:
        for value in ("S", "I"):
            sir = {d: value for d in ALL_DRUGS}
            qc = set()
            for r in check_reportability(org, sir):
                if r["category"] == "intrinsic":
                    qc.update(r["drugs"])
            w, _ = run(sir, org=org, spec="Blood", std="EUCAST")
            leaked = sorted(d for d in qc if bucket(w, d) != "banned")
            assert not leaked, (org, value, leaked)


def test_qc_does_not_condemn_working_drugs():
    def intrinsic(org, drug):
        return any(r["category"] == "intrinsic"
                   for r in check_reportability(org, {drug: "S"}))
    assert not intrinsic("Stenotrophomonas maltophilia", "Levofloxacin")
    assert intrinsic("Stenotrophomonas maltophilia", "Ofloxacin")
    assert not intrinsic("Staphylococcus aureus", "Fusidic acid")
    assert not intrinsic("MRSA", "Fusidic acid")
    assert intrinsic("Enterococcus faecalis", "Fusidic acid")
    assert not intrinsic("Klebsiella spp.", "Amoxicillin + Clavulanic acid")
    assert intrinsic("Klebsiella spp.", "Ampicillin")
    assert intrinsic("E. coli", "Vancomycin")


def test_qc_rule_texts_are_strings():
    import ast_reportability as R
    for table in ("INTRINSIC_RULES", "NO_BREAKPOINT_RULES", "INEFFECTIVE_INVIVO_RULES"):
        for r in getattr(R, table):
            for k in ("reason_ar", "reason_en", "reference"):
                assert isinstance(r[k], str), (r["id"], k)


@pytest.mark.parametrize("org,sir", [
    ("MRSA", {}), ("Staphylococcus aureus", {"Cefoxitin": "R"}),
    ("Staphylococcus aureus", {"Oxacillin": "R"}),
])
def test_mrsa_bans_every_beta_lactam_including_inhibitor_combinations(org, sir):
    beta = [d for d in ALL_DRUGS if D.is_beta_lactam(d)]
    panel = dict({d: "S" for d in beta}, **sir, Vancomycin="S")
    w, _ = run(panel, org=org, spec="Blood")
    assert [d for d in beta if bucket(w, d) != "banned"] == []
    assert bucket(w, "Vancomycin") == "allowed"


def test_mssa_keeps_its_beta_lactams():
    w, _ = run({"Oxacillin": "S", "Cefoxitin": "S", "Cefazolin": "S"},
               org="Staphylococcus aureus", spec="Blood")
    assert bucket(w, "Cefazolin") == "allowed" and bucket(w, "Oxacillin") == "allowed"


def test_d_test():
    base = {"Clindamycin": "S", "Erythromycin": "R"}
    w, _ = run(base, org="Staphylococcus aureus", spec="Wound Swab")
    assert bucket(w, "Clindamycin") == "banned" and rule(w, "Clindamycin") == "d_test_inducible"
    w, _ = run(dict(base, **{"D-test": "Negative"}), org="Staphylococcus aureus", spec="Wound Swab")
    assert bucket(w, "Clindamycin") == "allowed"
    w, _ = run(dict(base, **{"D-test": "Positive"}), org="Staphylococcus aureus", spec="Wound Swab")
    assert "Positive" in w["Clindamycin"][1]["reason_short_en"]
    w, _ = run({"Clindamycin": "S", "Erythromycin": "S"}, org="Staphylococcus aureus", spec="Wound Swab")
    assert bucket(w, "Clindamycin") == "allowed"


def test_enterococcus_tmpsmx_and_klebsiella_fosfomycin():
    w, _ = run({"Trimethoprim/Sulfamethoxazole": "S"}, org="Enterococcus faecalis")
    assert bucket(w, "Trimethoprim/Sulfamethoxazole") == "banned"
    w, _ = run({"Fosfomycin": "S"}, org="Klebsiella spp.")
    assert bucket(w, "Fosfomycin") == "warned" and rule(w, "Fosfomycin") == "intrinsic_fosa"
    w, _ = run({"Fosfomycin": "S"}, org="E. coli")
    assert bucket(w, "Fosfomycin") == "allowed"


# ── mechanism rules ───────────────────────────────────────────────────────
ESBL = {"Ceftriaxone": "R", "Cefotaxime": "R"}
OTHER_BL = ["Amoxicillin + Clavulanic acid", "Piperacillin + Tazobactam",
            "Cefoperazone + Sulbactam", "Cefepime", "Cefoxitin", "Aztreonam", "Ampicillin/Sulbactam"]


def test_esbl_outside_urine_keeps_only_carbapenems():
    sir = dict(ESBL, Meropenem="S", Ertapenem="S", Amikacin="S", **{d: "S" for d in OTHER_BL})
    w, _ = run(sir, spec="Blood")
    for d in OTHER_BL:
        assert bucket(w, d) == "banned" and rule(w, d) == "mechanism_beta_lactam", d
    assert bucket(w, "Meropenem") == "allowed" and bucket(w, "Ertapenem") == "allowed"
    assert bucket(w, "Amikacin") == "allowed"


def test_esbl_in_urine_reports_as_tested_with_a_cystitis_only_caution():
    sir = dict(ESBL, Meropenem="S", **{d: "S" for d in OTHER_BL})
    w, _ = run(sir, spec="Urine")
    for d in OTHER_BL:
        assert bucket(w, d) == "warned", d
        assert w[d][1]["warning_reason"] == "esbl_bli_uti_only" and w[d][1]["esbl_note_en"]
    assert bucket(w, "Meropenem") == "allowed"


def test_ampc_keeps_cefepime_and_carbapenems():
    sir = {"Ceftriaxone": "R", "Cefepime": "S", "Meropenem": "S", "Piperacillin + Tazobactam": "S"}
    w, _ = run(sir, org="Enterobacter cloacae", spec="Blood")
    assert bucket(w, "Cefepime") == "allowed" and bucket(w, "Meropenem") == "allowed"
    assert bucket(w, "Piperacillin + Tazobactam") == "banned"


def test_ampc_high_risk_organism_with_susceptible_third_generation():
    w, _ = run({"Ceftriaxone": "S", "Cefepime": "S"}, org="Enterobacter cloacae", spec="Blood")
    assert bucket(w, "Ceftriaxone") == "warned" and rule(w, "Ceftriaxone") == "ampc_inducible"
    assert bucket(w, "Cefepime") == "allowed"
    w, _ = run({"Ceftriaxone": "S"}, org="E. coli", spec="Blood")
    assert bucket(w, "Ceftriaxone") == "allowed"


def test_cre_bans_all_beta_lactams():
    sir = {"Meropenem": "R", "Imipenem/Cilastatin": "R", "Ertapenem": "S",
           "Ceftazidime": "S", "Piperacillin + Tazobactam": "S", "Aztreonam": "S", "Colistin": "S"}
    w, _ = run(sir, org="Klebsiella spp.", spec="Blood")
    assert bucket(w, "Ertapenem") == "banned" and rule(w, "Ertapenem") == "carbapenemase_carbapenem"
    assert bucket(w, "Ceftazidime") == "banned" and bucket(w, "Piperacillin + Tazobactam") == "banned"
    assert bucket(w, "Aztreonam") == "warned" and rule(w, "Aztreonam") == "cre_aztreonam"
    assert bucket(w, "Colistin") == "allowed"


def test_ertapenem_only_resistance_keeps_susceptible_meropenem_with_a_warning():
    w, _ = run({"Ertapenem": "R", "Meropenem": "S", "Amikacin": "S"}, org="Klebsiella spp.", spec="Blood")
    assert bucket(w, "Ertapenem") == "banned" and rule(w, "Ertapenem") == "resistant"
    assert bucket(w, "Meropenem") == "warned" and rule(w, "Meropenem") == "carbapenem_confirm"


def test_proteus_imipenem_r_does_not_remove_working_drugs():
    sir = {"Imipenem/Cilastatin": "R", "Meropenem": "S", "Ceftriaxone": "S"}
    w, _ = run(sir, org="Proteus mirabilis", spec="Urine")
    assert bucket(w, "Meropenem") == "allowed" and bucket(w, "Ceftriaxone") == "allowed"


def test_cr_pseudomonas_keeps_susceptible_beta_lactams():
    sir = {"Meropenem": "R", "Imipenem/Cilastatin": "R", "Ceftazidime": "S", "Cefepime": "S"}
    w, _ = run(sir, org="Pseudomonas aeruginosa", spec="Sputum")
    assert bucket(w, "Ceftazidime") == "allowed" and bucket(w, "Cefepime") == "allowed"


# ── patient rules ─────────────────────────────────────────────────────────
def test_child_rules():
    sir = {"Ciprofloxacin": "S", "Doxycycline": "S", "Amoxicillin": "S"}
    w, _ = run(sir, org="Streptococcus pneumoniae", spec="Sputum", age=5)
    assert bucket(w, "Ciprofloxacin") == "banned" and bucket(w, "Doxycycline") == "banned"
    assert bucket(w, "Amoxicillin") == "allowed"
    w, _ = run(sir, org="Streptococcus pneumoniae", spec="Sputum", age=12)
    assert bucket(w, "Ciprofloxacin") == "banned" and bucket(w, "Doxycycline") == "allowed"
    w, _ = run(sir, org="Streptococcus pneumoniae", spec="Sputum", age=18)
    assert bucket(w, "Ciprofloxacin") == "allowed"


def test_renal_rules():
    w, _ = run({"Nitrofurantoin": "S"}, renal=True, crcl=30)
    assert bucket(w, "Nitrofurantoin") == "banned" and w["Nitrofurantoin"][1]["category"] == "renal"
    w, _ = run({"Nitrofurantoin": "S"}, renal=True, crcl=60)
    assert bucket(w, "Nitrofurantoin") == "allowed"
    w, _ = run({"Ciprofloxacin": "S"}, renal=True, crcl=20)
    assert bucket(w, "Ciprofloxacin") == "warned"
    assert w["Ciprofloxacin"][1]["warning_reason"] == "renal_adjustment"
    w, _ = run({"Ciprofloxacin": "S"}, renal=False, crcl=20)
    assert bucket(w, "Ciprofloxacin") == "allowed"


def test_pregnancy_bans_do_not_depend_on_other_findings():
    """The defect that motivated the engine: a renal warning checked first used
    to pre-empt the pregnancy ban."""
    for drug, org in (("Gentamicin", "E. coli"), ("Amikacin", "E. coli"),
                      ("Trimethoprim/Sulfamethoxazole", "E. coli"),
                      ("Clarithromycin", "Streptococcus pneumoniae")):
        w, _ = run({drug: "S"}, org=org, spec="Sputum", preg=True, renal=True, crcl=20)
        assert bucket(w, drug) == "banned" and w[drug][1]["category"] == "pregnancy", drug
        assert any(x["code"] == "renal_adjustment" for x in w[drug][1].get("also", [])), drug
    w, _ = run({"Doxycycline": "S"}, org="Staphylococcus aureus", spec="Wound Swab", preg=True)
    assert bucket(w, "Doxycycline") == "banned"


def test_pregnancy_cautions():
    w, _ = run({"Ciprofloxacin": "S", "Nitrofurantoin": "S", "Aztreonam": "S",
                "Cephalexin": "S", "Vancomycin": "S"}, preg=True)
    assert bucket(w, "Ciprofloxacin") == "preg" and bucket(w, "Nitrofurantoin") == "preg"
    assert bucket(w, "Aztreonam") == "preg"          # preg_status "Caution"
    assert bucket(w, "Cephalexin") == "allowed"
    assert w["Ciprofloxacin"][1]["preg_note"]
    # caution outranks a dose-adjustment warning but keeps it attached
    w, _ = run({"Ciprofloxacin": "S"}, preg=True, renal=True, crcl=20)
    assert bucket(w, "Ciprofloxacin") == "preg"
    assert [x["code"] for x in w["Ciprofloxacin"][1]["also"]] == ["renal_adjustment"]


def test_no_pregnancy_rules_when_not_pregnant():
    w, _ = run({"Gentamicin": "S", "Doxycycline": "S"}, org="Staphylococcus aureus",
               spec="Wound Swab", preg=False)
    assert bucket(w, "Gentamicin") == "allowed" and bucket(w, "Doxycycline") == "allowed"


# ── specimen rule ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("spec", ["Urine", "MSU", "Mid-stream urine", "CSU", "Urinary catheter sample"])
def test_urine_agents_allowed_for_every_spelling_of_urine(spec):
    w, _ = run({"Nitrofurantoin": "S", "Fosfomycin": "S", "Norfloxacin": "S"}, spec=spec)
    assert all(bucket(w, d) == "allowed" for d in w)


def test_urine_agents_banned_elsewhere_even_for_a_pregnancy_caution_drug():
    for spec in ("Blood", "Sputum", "Wound Swab", "CSF", "Throat swab", "High vaginal swab", ""):
        w, _ = run({"Nitrofurantoin": "S", "Fosfomycin": "S", "Norfloxacin": "S"}, spec=spec, preg=True)
        assert all(bucket(w, d) == "banned" for d in w), spec
    w, _ = run({"Nitrofurantoin": "S", "Norfloxacin": "S"}, spec="Stool")
    assert bucket(w, "Nitrofurantoin") == "banned" and bucket(w, "Norfloxacin") == "allowed"


# ── alerts ────────────────────────────────────────────────────────────────
def test_alerts():
    _, alerts = run({"Ciprofloxacin": "S"}, meds=["Antacids (مضادات الحموضة)"])
    assert any("Ciprofloxacin" in a for a in alerts)
    _, alerts = run({"Ciprofloxacin": "R"}, meds=["Antacids (مضادات الحموضة)"])
    assert alerts == []                              # no alert for a drug already out
    _, alerts = run({"Oxacillin": "S"}, org="Staphylococcus aureus", spec="Blood")
    assert any("Cefazolin" in a for a in alerts)
    _, alerts = run({"Ampicillin": "S"}, org="Enterococcus faecium", spec="Blood")
    assert any("faecium" in a for a in alerts)


# ── engine-level properties ───────────────────────────────────────────────
def test_output_rows_carry_what_the_renderers_read():
    sir = {d: random.Random(i).choice("SIR") for i, d in enumerate(ALL_DRUGS)}
    for org in ("E. coli", "MRSA", "Pseudomonas aeruginosa"):
        for preg in (False, True):
            a, w, b, p, _ = analyze_antibiotics(ALL_DRUGS, org, "Urine", 30, "Female",
                                                True, 25.0, preg, False, [], sir, "CLSI")
            for r in b:
                for k in ("name", "category", "reason_short", "reason_detail",
                          "reason_short_en", "reason_detail_en", "rule"):
                    assert r.get(k), (org, r["name"], k)
            for r in w:
                assert r["warning_reason"] and r["warning_text"] and r["warning_text_en"]
                assert "class" in r and "aware" in r
            for r in p:
                assert r["preg_note"]
            for r in a:
                assert r["sir_category"] in ("S", "I") and "class" in r


def _sweep_cases(n=1500, seed=11):
    rnd = random.Random(seed)
    orgs = list(ORGANISM_PROFILE) + ["Enterobacter cloacae", "Klebsiella pneumoniae", ""]
    for _ in range(n):
        panel = rnd.sample(ALL_DRUGS, rnd.randint(2, 18))
        yield dict(sir={d: rnd.choices("SIR", weights=(5, 1, 4))[0] for d in panel},
                   org=rnd.choice(orgs), spec=rnd.choice(SPECIMENS),
                   age=rnd.choice([0, 1, 7, 8, 12, 17, 18, 40, 80]),
                   renal=rnd.random() < .4, crcl=rnd.choice([10.0, 30.0, 45.0, 60.0, 100.0]),
                   preg=rnd.random() < .3, std=rnd.choice(["CLSI", "EUCAST"]))


def test_invariants_over_random_cultures():
    for c in _sweep_cases():
        w, _ = run(**c)
        assert set(w) == set(c["sir"])
        for d, (where, row) in w.items():
            fam, v = D.family(d), c["sir"][d]
            if v == "R":
                assert where == "banned", (c, d)
            if where == "allowed":
                assert v in ("S", "I") and not (v == "I" and c["std"] == "CLSI"), (c, d)
            if c["preg"] and (fam in (D.TETRACYCLINE, D.AMINOGLYCOSIDE)
                              or ABX_GUIDELINES[d].get("preg_status") == "Banned"):
                assert where == "banned", (c, d)
            if c["preg"] and ABX_GUIDELINES[d].get("preg_status") in ("Warn", "Caution"):
                assert where in ("preg", "banned"), (c, d)
            if c["age"] < 18 and fam == D.FLUOROQUINOLONE:
                assert where == "banned", (c, d)
            if c["age"] < 8 and fam == D.TETRACYCLINE:
                assert where == "banned", (c, d)
            if d in D.URINE_ONLY and c["spec"] != "Urine" and not (
                    c["spec"] == "Stool" and d in D.URINE_ONLY_EXCEPT_GI):
                assert where == "banned", (c, d)


def test_adding_a_risk_factor_never_makes_a_drug_look_safer():
    order = {"allowed": 0, "warned": 1, "preg": 2, "banned": 3}
    for c in _sweep_cases(n=400, seed=3):
        base = dict(c, preg=False, renal=False, age=40)
        w0, _ = run(**base)
        for change in ({"preg": True}, {"renal": True, "crcl": 10.0}, {"age": 5}):
            w1, _ = run(**dict(base, **change))
            for d in w0:
                assert order[bucket(w1, d)] >= order[bucket(w0, d)], (base, change, d)


def test_outcome_does_not_depend_on_rule_order(monkeypatch):
    """Severity decides the list. Shuffling the non-terminal rules must not
    move any drug to a different list."""
    cases = list(_sweep_cases(n=300, seed=5))
    reference = [{d: b for d, (b, _) in run(**c)[0].items()} for c in cases]
    head, tail = list(engine.RULES[:2]), list(engine.RULES[2:])
    for seed in range(5):
        shuffled = tail[:]
        random.Random(seed).shuffle(shuffled)
        monkeypatch.setattr(engine, "RULES", tuple(head + shuffled))
        for c, ref in zip(cases, reference):
            assert {d: b for d, (b, _) in run(**c)[0].items()} == ref


def test_outcome_does_not_depend_on_panel_order_and_is_deterministic():
    for c in _sweep_cases(n=200, seed=9):
        ref = {d: b for d, (b, _) in run(**c)[0].items()}
        rev = dict(reversed(list(c["sir"].items())))
        assert {d: b for d, (b, _) in run(**dict(c, sir=rev))[0].items()} == ref
        assert {d: b for d, (b, _) in run(**c)[0].items()} == ref


def test_bad_inputs_do_not_crash():
    for kwargs in (dict(org=None, spec=None), dict(age=None), dict(crcl=None),
                   dict(sex=None), dict(std=None), dict(meds=None), dict(age="x")):
        run({"Ciprofloxacin": "S", "Gentamicin": None, "Meropenem": "??"}, **kwargs)
    assert analyze_antibiotics(None, "E. coli", "Urine", 30, "Male", False, 90, False,
                               False, None, None) == ([], [], [], [], [])


def test_severity_constants_are_ordered():
    assert WARN < PREG < BAN


def test_context_is_built_once_with_normalised_inputs():
    ctx = build_context("mrsa", "MSU", "34", "Female", 1, "55.5", 0, 0, None,
                        {"Oxacillin": "r"}, "eucast")
    assert ctx.is_mrsa and ctx.specimen == "urine" and ctx.age == 34
    assert ctx.cl_cr == 55.5 and ctx.interp_std == "EUCAST" and ctx.sir == {"Oxacillin": "R"}


def test_class_level_pregnancy_bans_survive_a_data_entry_slip(monkeypatch):
    """Tetracyclines and aminoglycosides are banned by CLASS: marking one
    "Safe" in abx_guidelines by mistake must not let it through."""
    for drug, org, spec in (("Gentamicin", "E. coli", "Blood"),
                            ("Doxycycline", "Staphylococcus aureus", "Wound Swab")):
        monkeypatch.setitem(ABX_GUIDELINES[drug], "preg_status", "Safe")
        w, _ = run({drug: "S"}, org=org, spec=spec, preg=True)
        assert bucket(w, drug) == "banned" and w[drug][1]["category"] == "pregnancy", drug
