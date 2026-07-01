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
# classify_mdr — smoke / shape
# ─────────────────────────────────────────────────────────────────────────
def test_classify_mdr_returns_shape():
    sir = {"Ceftriaxone": "R", "Ciprofloxacin": "R", "Meropenem": "S"}
    res = E.classify_mdr("Escherichia coli", sir)
    assert isinstance(res, dict)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
