"""
Unit tests for Orange Lab Microbiology CDSS — clinical engines + auth.

Run:   pytest -v
These tests import the REAL data modules (abx_guidelines, organism_profile,
specimen_organism_map). If an antibiotic/organism name below is spelled
differently in your data, adjust the constants at the top of each test.

WHY THIS MATTERS: in a CDSS a wrong output can harm a patient. These tests
pin down the highest-stakes clinical rules so that future edits (new drugs,
D-test logic, etc.) can't silently break them (regression safety).
"""

import pytest

import clinical_engines as E
from auth_utils import hash_password, verify_password


# ─────────────────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────────────────
def test_password_roundtrip():
    h = hash_password("OrangeLab#2026")
    assert verify_password("OrangeLab#2026", h) is True
    assert verify_password("wrong-password", h) is False


def test_password_hashes_are_salted():
    # same password → different hashes (random salt)
    assert hash_password("abc") != hash_password("abc")


def test_verify_rejects_garbage():
    assert verify_password("x", "not-a-valid-hash") is False
    assert verify_password("x", "") is False


# ─────────────────────────────────────────────────────────────────────────
# predict_esbl — resistance mechanism inference
# ─────────────────────────────────────────────────────────────────────────
def test_esbl_high_probability_on_3gc_resistance():
    sir = {"Ceftriaxone": "R", "Cefotaxime": "R", "Ceftazidime": "R",
           "Meropenem": "S", "Ertapenem": "S"}
    res = E.predict_esbl("Escherichia coli", sir)
    assert res["probability"] == "high"


def test_oxa48_fingerprint():
    # Classic OXA-48: Ertapenem R, Meropenem S/I → carbapenemase suspicion
    sir = {"Ertapenem": "R", "Meropenem": "S", "Ceftriaxone": "R"}
    res = E.predict_esbl("Klebsiella pneumoniae", sir)
    assert res["probability"] == "carbapenemase"


def test_two_carbapenems_resistant_is_carbapenemase():
    sir = {"Meropenem": "R", "Ertapenem": "R"}
    res = E.predict_esbl("Klebsiella pneumoniae", sir)
    assert res["probability"] == "carbapenemase"
    assert res["confidence"] >= 90


def test_non_producer_returns_none():
    res = E.predict_esbl("Staphylococcus aureus", {"Ceftriaxone": "R"})
    assert res["probability"] is None


def test_empty_sir_map_is_safe():
    assert E.predict_esbl("Escherichia coli", {})["probability"] is None


# ─────────────────────────────────────────────────────────────────────────
# analyze_antibiotics — the core suppression rules
# ─────────────────────────────────────────────────────────────────────────
def _names(items):
    return {i["name"] for i in items}


def test_mrsa_suppresses_all_beta_lactams():
    # Oxacillin/Cefoxitin R on S. aureus == MRSA → every beta-lactam must fail,
    # even if the AST card reports a cephalosporin as S.
    sir = {"Oxacillin": "R", "Cefoxitin": "R", "Vancomycin": "S", "Ceftriaxone": "S"}
    allowed, warned, banned, preg, inter = E.analyze_antibiotics(
        ["Oxacillin", "Cefoxitin", "Vancomycin", "Ceftriaxone"],
        "Staphylococcus aureus", "Blood", 40, "male",
        False, 90.0, False, False, [], sir,
    )
    assert "Vancomycin" in _names(allowed)
    assert "Ceftriaxone" not in _names(allowed)   # suppressed despite S
    assert "Oxacillin" in _names(banned)


def test_esbl_suppresses_cephalosporins_even_if_reported_S():
    sir = {"Ceftriaxone": "R", "Cefotaxime": "R", "Ceftazidime": "R",
           "Meropenem": "S", "Nitrofurantoin": "S", "Ciprofloxacin": "R"}
    allowed, warned, banned, preg, inter = E.analyze_antibiotics(
        ["Ceftriaxone", "Meropenem", "Nitrofurantoin", "Ciprofloxacin"],
        "Escherichia coli", "Urine", 55, "female",
        False, 80.0, False, False, [], sir,
    )
    assert "Meropenem" in _names(allowed)
    assert "Ceftriaxone" not in _names(allowed)
    assert "Ciprofloxacin" in _names(banned)      # reported R


def test_resistant_drug_is_always_banned():
    sir = {"Ciprofloxacin": "R"}
    allowed, warned, banned, preg, inter = E.analyze_antibiotics(
        ["Ciprofloxacin"], "Escherichia coli", "Urine", 30, "male",
        False, 90.0, False, False, [], sir,
    )
    assert "Ciprofloxacin" in _names(banned)
    assert "Ciprofloxacin" not in _names(allowed)


# ─────────────────────────────────────────────────────────────────────────
# classify_mdr — Magiorakos category logic
# ─────────────────────────────────────────────────────────────────────────
def test_classify_mdr_returns_shape():
    sir = {"Ceftriaxone": "R", "Ciprofloxacin": "R", "Meropenem": "S"}
    res = E.classify_mdr("Escherichia coli", sir)
    assert isinstance(res, dict)


def test_classify_mdr_category_rescued_by_susceptible_agent():
    """REGRESSION (real patient report, MB-34817/12931819, E. coli urine):
    a category must NOT be flagged non-susceptible when another tested agent
    in that SAME category is Susceptible — e.g. Ertapenem I does not condemn
    Carbapenems while Imipenem is S; Cefoperazone R does not condemn
    Cephalosporins-3rd-AP while Cefoperazone/Sulbactam is S. The previous
    'any R/I in category' rule wrongly produced XDR for this exact isolate;
    correct Magiorakos scoring is MDR (3 truly closed categories)."""
    sir = {
        "Imipenem/Cilastatin": "S", "Piperacillin + Tazobactam": "S", "Doxycycline": "S",
        "Norfloxacin": "S", "Ofloxacin": "S", "Cefoperazone + Sulbactam": "S",
        "Cefaclor": "S", "Ceftriaxone": "S",
        "Ciprofloxacin": "I", "Ertapenem": "I",
        "Tetracycline": "R", "Trimethoprim/Sulfamethoxazole": "R", "Gentamicin": "R",
        "Amoxicillin + Clavulanic acid": "R", "Cefoperazone": "R",
    }
    res = E.classify_mdr("E. coli", sir)
    assert res["level"] == "MDR", f"expected MDR, got {res['level']}"
    assert res["resistant_count"] == 3
    for cat in ("Carbapenems", "Fluoroquinolones", "Tetracyclines", "Cephalosporins-3rd-AP"):
        assert cat in res["susceptible_categories"], f"{cat} should be rescued by its S agent"
    for cat in ("Aminoglycosides", "Folate PI", "Penicillins+BLI"):
        assert cat in res["resistant_categories"]


def test_classify_mdr_true_xdr_still_detected():
    """A genuinely closed panel (non-susceptible to every tested agent in all
    but 2 categories) must still classify as XDR — the fix must not blunt
    real XDR detection."""
    sir = {
        "Gentamicin": "R", "Amikacin": "R",
        "Piperacillin + Tazobactam": "R",
        "Ceftriaxone": "R", "Cefotaxime": "R",
        "Imipenem/Cilastatin": "R", "Meropenem": "R", "Ertapenem": "R",
        "Ciprofloxacin": "R", "Ofloxacin": "R", "Norfloxacin": "R",
        "Trimethoprim/Sulfamethoxazole": "R",
        "Amoxicillin + Clavulanic acid": "R",
        "Doxycycline": "R", "Tetracycline": "R",
        "Colistin": "S", "Fosfomycin": "S",
    }
    res = E.classify_mdr("Klebsiella pneumoniae", sir)
    assert res["level"] == "XDR"
    assert set(res["susceptible_categories"]) == {"Polymyxins", "Fosfomycins"}


def test_classify_mdr_true_pdr_still_detected():
    sir = {"Gentamicin": "R", "Ceftriaxone": "R", "Imipenem/Cilastatin": "R",
           "Ciprofloxacin": "R", "Trimethoprim/Sulfamethoxazole": "R",
           "Amoxicillin + Clavulanic acid": "R", "Colistin": "R"}
    res = E.classify_mdr("Klebsiella pneumoniae", sir)
    assert res["level"] == "PDR"


def test_classify_mdr_fully_sensitive_is_none():
    sir = {"Ceftriaxone": "S", "Gentamicin": "S", "Ciprofloxacin": "S"}
    res = E.classify_mdr("E. coli", sir)
    assert res["level"] is None


# ─────────────────────────────────────────────────────────────────────────
# REGRESSION — bug fixes (non-urine logic review)
# ─────────────────────────────────────────────────────────────────────────
def _pscore(specimen, organism):
    """assess_pathogenicity score for a fully-significant scenario."""
    return E.assess_pathogenicity(
        specimen, organism, ">100,000", "Pure", ["Fever (> 38°C)"],
        "20", "", "", 40, "Male", [],
        ">25", "<10", ["fever"], "peripheral", "deep",
    )["score"]


def test_bug1_abbreviated_names_recognised_as_pathogens():
    """BUG-1: the app passes short names (E. coli, MRSA, Klebsiella spp.) but the
    engine's inline lists use Latin binomials. Before the fix, `organism in LIST`
    silently failed and every organism fell through to the generic penalty.
    A recognised pathogen must now score strictly higher than an unknown organism
    in the *same* scenario (this depends only on clinical_engines, so it is stable
    regardless of the clinical_data thresholds)."""
    unknown = _pscore("Urine", "Foobacter xyz")
    for specimen, known in [
        ("Urine", "E. coli"),
        ("Sputum", "MRSA"),
        ("Sputum", "H. influenzae"),
        ("Blood", "Klebsiella spp."),
        ("Blood", "VRE"),
        ("Stool", "Campylobacter jejuni"),
        ("Stool", "Salmonella spp."),
    ]:
        assert _pscore(specimen, known) > _pscore(specimen, "Foobacter xyz"), (
            f"{known} was not recognised as a pathogen in {specimen}"
        )
    # sanity: the unknown organism in urine is only the small 'occasional' bump
    assert unknown < _pscore("Urine", "E. coli")


def _abx_specimen(specimen):
    """Return (allowed names, banned-as-'specimen' names) for the urine-only agents."""
    drugs = ["Nitrofurantoin", "Fosfomycin", "Norfloxacin", "Ceftriaxone"]
    sir = {d: "S" for d in drugs}
    allowed, warned, banned, preg, inter = E.analyze_antibiotics(
        drugs, "Escherichia coli", specimen, 40, "Male",
        False, 90.0, False, False, [], sir,
    )
    spec_banned = {b["name"] for b in banned if b.get("category") == "specimen"}
    return _names(allowed), spec_banned


def test_bug2_urine_only_agents_blocked_in_systemic_specimens():
    """BUG-2: Nitrofurantoin / Fosfomycin / Norfloxacin reach therapeutic levels
    only in urine. They must NOT appear as usable options for blood/sputum/wound/
    pus/CSF — they are relocated to 'banned' with a specimen reason."""
    for specimen in ("Blood", "Sputum", "Wound Swab", "Pus", "CSF"):
        allowed, spec_banned = _abx_specimen(specimen)
        for d in ("Nitrofurantoin", "Fosfomycin", "Norfloxacin"):
            assert d not in allowed, f"{d} leaked into allowed for {specimen}"
            assert d in spec_banned, f"{d} not banned (specimen) for {specimen}"


def test_bug2_urine_keeps_urine_only_agents():
    """In urine these agents are first-line — the specimen filter must not touch them."""
    allowed, spec_banned = _abx_specimen("Urine")
    for d in ("Nitrofurantoin", "Fosfomycin", "Norfloxacin"):
        assert d not in spec_banned
        assert d in allowed


def test_bug2_stool_keeps_norfloxacin_only():
    """Stool: Nitrofurantoin + Fosfomycin are useless (no gut levels) but
    Norfloxacin retains a GI indication."""
    allowed, spec_banned = _abx_specimen("Stool")
    assert "Nitrofurantoin" in spec_banned
    assert "Fosfomycin" in spec_banned
    assert "Norfloxacin" not in spec_banned


def test_bug3_pneumococcus_not_confused_with_klebsiella_pneumoniae():
    """BUG-3(b): a bare `"pneumoniae" in org` test also matched *Klebsiella*
    pneumoniae, routing GNB meningitis to the pneumococcal duration. The DB is
    patched here so the assertion is deterministic and independent of clinical_data."""
    saved = E.TREATMENT_DURATION_DB
    E.TREATMENT_DURATION_DB = {
        "Meningitis_pneumococcal": {"label": "PNEUMO", "days": (10, 14),
                                    "standard": 14, "notes": "", "ref": ""},
        "Meningitis_GNB": {"label": "GNB", "days": (21, 21),
                           "standard": 21, "notes": "", "ref": ""},
    }
    try:
        pneumo = E.get_treatment_duration(
            "CSF", "Streptococcus pneumoniae", "", 40, "Male", False, [], "moderate")
        kleb = E.get_treatment_duration(
            "CSF", "Klebsiella pneumoniae", "", 40, "Male", False, [], "moderate")
        assert pneumo["label"] == "PNEUMO"
        assert kleb["label"] == "GNB"   # must NOT be treated as pneumococcal
    finally:
        E.TREATMENT_DURATION_DB = saved


def test_bug3_missing_duration_key_does_not_crash():
    """BUG-3(a): a missing key must fall back safely instead of raising KeyError."""
    saved = E.TREATMENT_DURATION_DB
    E.TREATMENT_DURATION_DB = {}
    try:
        r = E.get_treatment_duration(
            "CSF", "Streptococcus pneumoniae", "", 40, "Male", False, [], "moderate")
        assert r["label"] == "Not matched"
    finally:
        E.TREATMENT_DURATION_DB = saved


# ─────────────────────────────────────────────────────────────────────────
# COMPLETENESS — data-module cross-consistency + new organisms
# ─────────────────────────────────────────────────────────────────────────
def test_data_modules_cross_validate_clean():
    """Every antibiotic referenced by an organism exists in ABX_GUIDELINES, every
    organism referenced by the specimen map / abx guidelines exists in the profile,
    and every specimen key is known. Guards the whole data layer against typos."""
    import abx_guidelines as A
    import organism_profile as O
    import specimen_organism_map as M
    abx = set(A.ABX_GUIDELINES)
    orgs = set(O.ORGANISM_PROFILE)
    specs = set(M.SPECIMEN_ORDER)
    assert A.validate_abx_guidelines(known_organisms=orgs, known_specimens=specs) == []
    assert O.validate_organism_profile(known_antibiotics=abx) == []
    assert M.validate_specimen_organism_map(known_organisms=orgs) == []


def test_new_organisms_present_and_mapped():
    """N. meningitidis / Listeria / Moraxella were added to close CSF & sputum gaps."""
    import organism_profile as O
    import specimen_organism_map as M
    for org in ("Neisseria meningitidis", "Listeria monocytogenes", "Moraxella catarrhalis"):
        assert org in O.ORGANISM_PROFILE, f"{org} missing from profile"
        assert O.ORGANISM_PROFILE[org]["first_line"], f"{org} has no first-line drug"
    assert "Neisseria meningitidis" in M.SPECIMEN_ORGANISM_MAP["CSF"]
    assert "Listeria monocytogenes" in M.SPECIMEN_ORGANISM_MAP["CSF"]
    assert "Moraxella catarrhalis" in M.SPECIMEN_ORGANISM_MAP["Sputum"]
    # Listeria is intrinsically cephalosporin-resistant → must be flagged to avoid
    assert any("ephalosporin" in a for a in O.ORGANISM_PROFILE["Listeria monocytogenes"]["avoid"])


# ── Empiric-regimen note must be reconciled with the patient's AST ──────────
def test_regimen_note_flags_resistant_and_untested():
    """A guideline note quoting TMP-SMX / Nitrofurantoin must not contradict the
    antibiogram: resistant agents get an R flag, untested agents a not-tested
    flag, and agents with a sensitive option are left clean."""
    sir = {
        "Trimethoprim/Sulfamethoxazole": "R",   # resistant in this culture
        "Norfloxacin": "S", "Ofloxacin": "S", "Ciprofloxacin": "I",  # FQ has an S
        # Nitrofurantoin deliberately absent -> not tested
    }
    note = "3d TMP-SMX | 5d Nitrofurantoin | 3-7d FQ (not preferred)"
    out = E.annotate_regimen_note(note, sir, lang="en")
    assert "TMP-SMX ⚠️[R" in out          # resistant flagged
    assert "Nitrofurantoin [not tested]" in out   # untested flagged
    assert "FQ ⚠️" not in out and "FQ [" not in out  # FQ clean (an S exists)


def test_regimen_note_untouched_without_sir():
    note = "3d TMP-SMX | 5d Nitrofurantoin"
    assert E.annotate_regimen_note(note, {}) == note
    assert E.annotate_regimen_note(note, None) == note


def test_regimen_note_class_all_resistant_flagged():
    out = E.annotate_regimen_note(
        "3-7d FQ", {"Ciprofloxacin": "R", "Ofloxacin": "R", "Norfloxacin": "R"}, lang="en")
    assert "FQ ⚠️[R" in out


def test_regimen_note_sensitive_left_clean():
    out = E.annotate_regimen_note(
        "3d TMP-SMX", {"Trimethoprim/Sulfamethoxazole": "S"})
    assert out == "3d TMP-SMX"          # sensitive -> no flag


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
