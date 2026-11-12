"""Specimens, renal, duration, severity, stewardship, pathogenicity, syndromes,
QC, ranking - and the public facade."""
import pytest

import clinical_engines as E
from cdss.duration import _duration_key
from cdss.pathogenicity import _parse_cfu, _parse_pus
from cdss.specimens import SPECIMEN_CATEGORIES, classify_specimen
from clinical_data import TREATMENT_DURATION_DB


# ── specimens ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name,cat", [
    ("Urine", "urine"), ("MSU", "urine"), ("csu", "urine"), ("Urinary catheter", "urine"),
    ("Blood", "blood"), ("Blood culture", "blood"), ("CSF", "csf"),
    ("Sputum", "sputum"), ("BAL", "respiratory"), ("Tracheal aspirate", "respiratory"),
    ("Stool", "stool"), ("Rectal swab", "stool"), ("Throat swab", "throat"),
    ("High vaginal swab", "genital"), ("HVS", "genital"), ("Balanitis swab", "genital"),
    ("Wound Swab", "wound"), ("Pus", "wound"), ("Necrotic tissue", "wound"),
    ("Surgical wound", "wound"), ("Ear swab", "throat"), ("Smear", "other"),
    ("", "other"), (None, "other"), ("Something else", "other"),
])
def test_classify_specimen(name, cat):
    assert classify_specimen(name) == cat
    assert cat in SPECIMEN_CATEGORIES


# ── renal ─────────────────────────────────────────────────────────────────
def test_creatinine_clearance():
    assert E.calc_creatinine_clearance(40, 72, 1.0, "Male") == pytest.approx(100.0)
    assert E.calc_creatinine_clearance(40, 72, 1.0, "Female") == pytest.approx(85.0)
    assert E.calc_creatinine_clearance(40, 72, 0, "Male") == 0.0
    assert E.calc_creatinine_clearance(10, 30, 0.5, "Male", height_cm=140) == pytest.approx(115.64)
    assert E.get_renal_severity(60) == "Mild" and E.get_renal_severity(59.9) == "Moderate"
    assert E.get_renal_severity(29.9) == "Severe"


# ── duration ──────────────────────────────────────────────────────────────
def _key(spec, org="E. coli", synd="", age=30, sex="Female", renal=False,
         mrsa=False, mdr=False, sev="moderate"):
    return _duration_key(spec, org, synd, age, sex, renal, mrsa, mdr, sev)


def test_every_duration_key_the_router_can_return_exists_in_the_db():
    specs = ["Urine", "Sputum", "BAL", "Blood", "CSF", "Wound Swab", "Pus", "Stool",
             "Peritoneal fluid", "Throat swab", "High vaginal swab", ""]
    orgs = ["E. coli", "MRSA", "Staphylococcus aureus", "Enterococcus faecalis",
            "Streptococcus pneumoniae", "Neisseria meningitidis", "H. influenzae",
            "Streptococcus agalactiae", "Listeria monocytogenes", "Pseudomonas aeruginosa", ""]
    seen = set()
    for spec in specs:
        for org in orgs:
            for sev in ("mild", "moderate", "severe"):
                for synd in ("", "pyelonephritis", "VAP", "necrotizing fasciitis", "osteomyelitis"):
                    k = _key(spec, org, synd, sev=sev)
                    if k is not None:
                        assert k in TREATMENT_DURATION_DB, k
                        seen.add(k)
    # ...and no row is dead: every row is reachable from some input.
    assert seen == set(TREATMENT_DURATION_DB)


def test_duration_rows_are_internally_consistent():
    for key, row in TREATMENT_DURATION_DB.items():
        lo, hi = row["days"]
        assert 0 <= lo <= row["standard"] <= hi, key
        assert row["label"] and row["ref"], key


def test_meningitis_duration_is_organism_specific():
    d = lambda org: E.get_treatment_duration("CSF", org, "", 30, "Male", False, [])  # noqa: E731
    assert d("Neisseria meningitidis")["standard_days"] == 7
    assert d("H. influenzae")["standard_days"] == 7
    assert (d("Streptococcus pneumoniae")["min_days"], d("Streptococcus pneumoniae")["max_days"]) == (10, 14)
    assert (d("Streptococcus agalactiae")["min_days"], d("Streptococcus agalactiae")["max_days"]) == (14, 21)
    assert d("Listeria monocytogenes")["min_days"] == 21
    assert d("E. coli")["standard_days"] == 21 and d("Klebsiella pneumoniae")["key"] == "Meningitis_GNB"
    assert d("Staphylococcus aureus")["key"] == "Meningitis_other"


def test_bacteremia_routing():
    assert _key("Blood", "MRSA") == "Bacteremia_MRSA"
    assert _key("Blood", "Staphylococcus aureus") == "Bacteremia_MSSA"
    assert _key("Blood", "Staphylococcus aureus", mrsa=True) == "Bacteremia_MRSA"
    assert _key("Blood", "E. coli") == "Bacteremia_GNB"
    assert _key("Blood", "Enterococcus faecalis") == "Bacteremia_other"
    assert _key("Blood", "Staphylococcus epidermidis") == "Bacteremia_other"


def test_non_wound_swabs_are_not_skin_infections():
    for spec in ("Throat swab", "High vaginal swab", "Something else", ""):
        assert _key(spec) is None
        assert E.get_treatment_duration(spec, "E. coli", "", 30, "Male", False, [])["label"] == "Not matched"
    assert _key("Rectal swab") == "GI_mild"
    assert _key("Wound Swab", sev="mild") == "SSTI_mild"


def test_urine_duration_routing():
    assert _key("Urine", sev="mild") == "UTI_uncomplicated_female"
    assert _key("Urine", sex="Male", sev="mild") == "UTI_complicated"
    assert _key("MSU", sev="severe") == "Pyelonephritis_inpatient"
    assert _key("Urine", synd="Pyelonephritis", sev="mild") == "Pyelonephritis_outpatient"


def test_duration_modifiers_do_not_mutate_the_db():
    before = dict(TREATMENT_DURATION_DB["UTI_complicated"])
    r = E.get_treatment_duration("Urine", "E. coli", "", 80, "Male", True, [{"phenotype": "MDR"}])
    assert "MDR organism" in r["notes"] and r["max_days"] >= 14
    assert TREATMENT_DURATION_DB["UTI_complicated"] == before


# ── severity ──────────────────────────────────────────────────────────────
def test_severity():
    s = lambda **k: E.suggest_severity(**dict(dict(specimen="Urine", age=30, sex="Female",  # noqa: E731
                                               is_preg=False, is_renal=False, cl_cr=90), **k))["suggested"]
    assert s() == "mild"
    assert s(sex="Male") == "moderate" and s(is_preg=True) == "moderate" and s(age=70) == "moderate"
    assert s(host_factors=["Immunosuppressants / Steroids"]) == "severe"
    assert s(host_factors=["Central line / PICC"]) == "severe"
    assert s(specimen="CSF") == "severe" and s(specimen="Blood") == "moderate"
    assert s(specimen="Blood", age=70) == "severe"
    assert s(specimen="MSU", symptoms=["Fever (> 38°C)"]) == "moderate"
    assert s(specimen="Sputum") == "mild"
    assert s(specimen="Sputum", symptoms=["Altered mental status / Confusion"]) == "severe"
    assert s(specimen="Throat swab") == "mild"       # no wound logic for a throat swab


# ── stewardship ───────────────────────────────────────────────────────────
def test_iv_po_switch_matches_exact_drug_only():
    ok = E.evaluate_iv_po_switch("Ciprofloxacin", "", True, True, True, 3)
    assert ok["can_switch"] and ok["bioavail"] == 95
    assert E.evaluate_iv_po_switch("ciprofloxacin", "", True, True, True, 3)["matched_drug"] == "Ciprofloxacin"
    for name in ("Cef", "Cefuroxime sodium", "", "Amox"):
        r = E.evaluate_iv_po_switch(name, "", True, True, True, 3)
        assert r["matched_drug"] == "" and not r["can_switch"], name
    assert E.evaluate_iv_po_switch("Amoxicillin", "", True, True, True, 3)["bioavail"] == 90
    assert not E.evaluate_iv_po_switch("Ciprofloxacin", "Meningitis", True, True, True, 3)["can_switch"]
    assert not E.evaluate_iv_po_switch("Ciprofloxacin", "", True, True, True, 1)["can_switch"]


def test_deescalation():
    allowed = [{"name": "Amoxicillin", "aware": "Access"}, {"name": "Meropenem", "aware": "Watch"}]
    assert not E.evaluate_deescalation(allowed, [], 24, True)["can_deescalate"]
    assert not E.evaluate_deescalation(allowed, [], 72, False)["can_deescalate"]
    assert E.evaluate_deescalation(allowed, [], 72, True)["can_deescalate"]
    assert not E.evaluate_deescalation(allowed, [{"phenotype": "CRE"}], 72, True)["can_deescalate"]


# ── pathogenicity parsers ─────────────────────────────────────────────────
@pytest.mark.parametrize("text,value", [
    ("≥ 10^5 CFU/mL", 100000), (">10^5", 100000), ("10⁵", 100000), ("10^4", 10000),
    ("5 x 10^4", 50000), ("5×10⁴ CFU/ml", 50000), ("1e5", 100000), ("100,000", 100000),
    ("> 100000 CFU/mL", 100000), ("50,000 - 100,000", 100000), ("10^3", 1000),
    ("1000", 1000), ("", 0), (None, 0), ("no growth", 0),
])
def test_parse_cfu(text, value):
    assert _parse_cfu(text) == value


@pytest.mark.parametrize("text,value", [
    ("8-10", 10), ("TNTC", 999), ("nil", 0), ("", None), ("many", None), ("25", 25),
])
def test_parse_pus(text, value):
    assert _parse_pus(text) == value


def _patho(**k):
    base = dict(specimen="Urine", organism="E. coli", colony_count_text="≥ 10^5 CFU/mL",
                culture_purity="Pure growth", symptoms=[], pus_cells_text="20-25",
                urinalysis_result="", gram_stain="", age=30, sex="Female", host_factors=[])
    return E.assess_pathogenicity(**dict(base, **k))


def test_pathogenicity_abu_and_its_exceptions():
    assert "ABU_NO_TREAT" in _patho()["special_flags"]
    assert "ABU_TREAT" in _patho(host_factors=["Pregnant"])["special_flags"]
    assert not _patho(symptoms=["Dysuria / Frequency / Urgency"])["abu_detected"]
    # an infant cannot report symptoms: never "asymptomatic - do not treat"
    infant = _patho(age=1)
    assert not infant["abu_detected"] and "Do NOT Treat" not in infant["verdict"]


def test_pathogenicity_fixed_verdicts_and_score_bounds():
    assert "ALWAYS SIGNIFICANT" in _patho(specimen="CSF")["verdict"]
    r = _patho(specimen="Sputum", sputum_pus_cells="5", sputum_epithelial="30")
    assert "MW_REJECT" in r["special_flags"]
    for spec in ("Urine", "Blood", "Sputum", "Stool", "Wound Swab", "CSF", "Throat swab", ""):
        for org in ("E. coli", "Staphylococcus epidermidis", "", "Salmonella spp."):
            r = _patho(specimen=spec, organism=org)
            assert 0 <= r["score"] <= 100 and r["verdict"]


# ── syndromes ─────────────────────────────────────────────────────────────
def test_infection_syndrome_routing():
    g = lambda spec, **k: E.get_infection_syndrome(spec, "E. coli", k.get("age", 30), False, k.get("cath", False))  # noqa: E731
    assert g("Urine")["sub_type"] == "Uncomplicated UTI"
    assert g("MSU", cath=True)["sub_type"] == "Complicated UTI"
    assert g("BAL")["syndrome"].startswith("Respiratory")
    assert g("Pus")["syndrome"].startswith("Abscess")
    assert g("Wound Swab")["sub_type"] == "SSTI"
    assert g("Rectal swab")["syndrome"].startswith("Gastro")
    for spec in ("Throat swab", "High vaginal swab", "", "Balanitis swab"):
        assert g(spec) is None, spec


# ── QC ────────────────────────────────────────────────────────────────────
def test_qc_runs_on_canonical_organism_identity():
    ids = lambda org, sir: {i["id"].split(":")[0] for i in E.run_ast_qc(org, sir)}  # noqa: E731
    assert "QC007" in ids("Escherichia coli", {"Vancomycin": "S"})
    assert "QC007" in ids("E. coli", {"Vancomycin": "s"})
    assert "QC005" in ids("MRSA", {"Linezolid": "R"})
    assert "QC007" not in ids("", {"Vancomycin": "S"})
    assert E.run_ast_qc("E. coli", {}) == []


def test_qc_confidence_bounds():
    r = E.compute_qa_confidence([], {"A": "S"}, "E. coli")
    assert r["n_tested"] == 1 and 0 <= r["score"] <= 100
    many = [{"severity": "error"}] * 10
    assert E.compute_qa_confidence(many, {}, "E. coli")["score"] == 0
    full = {str(i): "S" for i in range(10)}
    assert E.compute_qa_confidence([], full, "E. coli")["level"] == "High Confidence"


# ── ranking ───────────────────────────────────────────────────────────────
def test_ranking_never_puts_i_above_s():
    allowed = [{"name": "Nitrofurantoin", "aware": "Access", "high_po": True, "priority": 1},
               {"name": "Meropenem", "aware": "Watch", "high_po": False, "priority": 9}]
    ranked = E.rank_sensitive_antibiotics(allowed, "Urine", "E. coli",
                                          {"Nitrofurantoin": "i", "Meropenem": "S"}, [])
    assert [r["name"] for r in ranked] == ["Meropenem", "Nitrofurantoin"]
    assert E.rank_sensitive_antibiotics([], "Urine", "E. coli", {}, []) == []
    assert E.rank_sensitive_antibiotics(None, "Urine", "E. coli", None, None) == []


# ── facade ────────────────────────────────────────────────────────────────
def test_facade_exports_everything_callers_import():
    names = """analyze_antibiotics assess_pathogenicity calc_creatinine_clearance classify_mdr
        classify_specimen compute_qa_confidence detect_resistance_phenotypes evaluate_deescalation
        evaluate_iv_po_switch fuzzy_match get_combination_therapy get_hepatic_recommendations
        get_infection_syndrome get_renal_severity get_route_label get_treatment_duration
        predict_esbl rank_sensitive_antibiotics run_ast_qc safe_int suggest_severity
        uniq_keep_order annotate_regimen_note is_intrinsically_avoided build_banned_item
        _remove_intrinsic_resistance ABX_GUIDELINES ORGANISM_PROFILE""".split()
    for n in names:
        assert hasattr(E, n), n


def test_cdss_package_does_not_import_streamlit():
    import sys
    import cdss  # noqa: F401
    assert "streamlit" not in sys.modules
