"""Mechanism inference, MDR classification, named phenotypes."""
import pytest

from cdss.mdr import classify_mdr
from cdss.mechanisms import predict_esbl
from cdss.phenotypes import detect_resistance_phenotypes

ECOLI = "E. coli"


def _p(org, sir):
    r = predict_esbl(org, sir)
    return r["probability"], r["betalactam_policy"]


# ── mechanisms ────────────────────────────────────────────────────────────
def test_no_panel_or_unknown_organism_gives_no_call():
    assert _p(ECOLI, {}) == (None, None)
    assert _p("", {"Ceftriaxone": "R", "Cefotaxime": "R"}) == (None, None)
    assert _p("Staphylococcus aureus", {"Ceftriaxone": "R", "Cefotaxime": "R"}) == (None, None)
    assert _p("Acinetobacter baumannii", {"Ceftazidime": "R", "Meropenem": "R"}) == (None, None)


def test_esbl_tiers():
    assert _p(ECOLI, {"Ceftriaxone": "R", "Cefotaxime": "R"}) == ("high", "esbl")
    assert _p(ECOLI, {"Ceftriaxone": "R", "Ceftazidime": "S", "Meropenem": "S"}) == ("high", "esbl")
    # one marker tested, one R: thin panel -> moderate, no restriction
    assert _p(ECOLI, {"Ceftriaxone": "R", "Meropenem": "S"}) == ("moderate", None)
    assert _p(ECOLI, {"Cefuroxime": "R", "Cefixime": "R"}) == ("moderate", None)
    assert _p(ECOLI, {"Ceftriaxone": "S", "Ciprofloxacin": "R"}) == ("low", None)


def test_results_are_normalised_before_inference():
    assert _p(ECOLI, {"Ceftriaxone": "r", "Cefotaxime": "Resistant"}) == ("high", "esbl")


def test_ampc_only_in_ampc_enterobacterales():
    assert _p("Enterobacter cloacae", {"Ceftriaxone": "R", "Cefepime": "S"}) == ("ampc", "ampc")
    assert _p("Klebsiella aerogenes", {"Ceftriaxone": "R", "Ceftazidime": "R"}) == ("ampc", "ampc")
    assert _p("Citrobacter koseri", {"Ceftriaxone": "R", "Cefotaxime": "R"}) == ("high", "esbl")


def test_esbl_and_ampc_labels_never_reach_pseudomonas():
    assert _p("Pseudomonas aeruginosa", {"Ceftazidime": "R", "Cefepime": "R"}) == ("low", None)
    # intrinsic ceftriaxone/cefotaxime R must not look like ESBL
    assert _p("Pseudomonas aeruginosa", {"Ceftriaxone": "R", "Cefotaxime": "R"}) == ("low", None)


def test_pseudomonas_carbapenem_resistance_is_not_a_carbapenemase_call():
    r = predict_esbl("Pseudomonas aeruginosa",
                     {"Meropenem": "R", "Imipenem/Cilastatin": "R", "Ceftazidime": "S"})
    assert r["probability"] == "cr_pseudomonas" and r["betalactam_policy"] is None
    assert r["still_susceptible_betalactams"] == ["Ceftazidime"]
    # a carbapenem "I" alone used to be labelled carbapenemase here
    assert _p("Pseudomonas aeruginosa", {"Meropenem": "I", "Ceftazidime": "S"}) == ("low", None)


def test_carbapenem_tiers_in_enterobacterales():
    assert _p(ECOLI, {"Meropenem": "R", "Imipenem/Cilastatin": "R"}) == ("carbapenemase", "cre")
    assert predict_esbl(ECOLI, {"Meropenem": "R", "Ertapenem": "R"})["confidence"] == 92
    assert _p(ECOLI, {"Meropenem": "R"}) == ("carbapenemase", "cre")
    assert predict_esbl(ECOLI, {"Meropenem": "R"})["confidence"] == 55
    # ertapenem-only resistance: possible, not established
    assert _p(ECOLI, {"Ertapenem": "R", "Meropenem": "S"}) == ("carbapenemase", "cre_possible")
    assert predict_esbl(ECOLI, {"Ertapenem": "R", "Meropenem": "S"})["confidence"] == 62
    assert _p(ECOLI, {"Ertapenem": "R"}) == ("carbapenemase", "cre_possible")
    assert _p(ECOLI, {"Meropenem": "I"}) == ("carbapenemase", "cre_possible")
    # ertapenem R + imipenem R is two signals
    assert _p(ECOLI, {"Ertapenem": "R", "Imipenem/Cilastatin": "R", "Meropenem": "S"}) == ("carbapenemase", "cre")


@pytest.mark.parametrize("org", ["Proteus mirabilis", "Morganella morganii", "Providencia spp."])
def test_imipenem_alone_is_not_a_signal_in_morganellaceae(org):
    assert _p(org, {"Imipenem/Cilastatin": "R", "Meropenem": "S", "Ceftazidime": "S"})[1] is None
    assert _p(org, {"Imipenem/Cilastatin": "I", "Meropenem": "S"})[1] is None
    # ...but meropenem resistance still is
    assert _p(org, {"Imipenem/Cilastatin": "R", "Meropenem": "R"}) == ("carbapenemase", "cre")


def test_every_result_has_the_keys_the_ui_reads():
    for org, sir in ((ECOLI, {}), (ECOLI, {"Ceftriaxone": "R", "Cefotaxime": "R"}),
                     ("Pseudomonas aeruginosa", {"Meropenem": "R"}), ("", {"Meropenem": "R"})):
        r = predict_esbl(org, sir)
        for k in ("probability", "confidence", "mechanism", "markers_R", "detail",
                  "action", "betalactam_policy"):
            assert k in r, (org, k)


# ── MDR ───────────────────────────────────────────────────────────────────
def test_mdr_empty_and_shape():
    r = classify_mdr(ECOLI, {})
    assert r["level"] is None and r["reliable"] is False
    r = classify_mdr("", {"Ciprofloxacin": "R"})
    assert r["level"] is None


def test_mdr_needs_three_categories():
    two = {"Ciprofloxacin": "R", "Gentamicin": "R", "Ceftriaxone": "S", "Meropenem": "S"}
    assert classify_mdr(ECOLI, two)["level"] is None
    three = dict(two, **{"Trimethoprim/Sulfamethoxazole": "R"})
    assert classify_mdr(ECOLI, three)["level"] == "MDR"


def test_mdr_i_is_non_susceptible_under_clsi_only():
    sir = {"Ciprofloxacin": "I", "Gentamicin": "I", "Trimethoprim/Sulfamethoxazole": "I",
           "Ceftriaxone": "S", "Meropenem": "S"}
    assert classify_mdr(ECOLI, sir, "CLSI")["level"] == "MDR"
    assert classify_mdr(ECOLI, sir, "EUCAST")["level"] is None
    assert classify_mdr(ECOLI, sir)["level"] == "MDR"          # default = as published


def test_mdr_ignores_intrinsic_resistance():
    # P. aeruginosa: every R below is intrinsic -> nothing acquired -> not MDR
    sir = {"Ceftriaxone": "R", "Ertapenem": "R", "Trimethoprim/Sulfamethoxazole": "R",
           "Doxycycline": "R", "Nitrofurantoin": "R", "Ceftazidime": "S", "Meropenem": "S"}
    assert classify_mdr("Pseudomonas aeruginosa", sir)["level"] is None


def test_xdr_pdr_are_capped_on_thin_panels():
    thin = {"Ciprofloxacin": "R", "Gentamicin": "R", "Trimethoprim/Sulfamethoxazole": "R"}
    r = classify_mdr(ECOLI, thin)
    assert r["level"] == "MDR" and any("too thin" in w for w in r["warnings"])


def test_pdr_requires_no_susceptible_agent_anywhere():
    full_r = {"Gentamicin": "R", "Amikacin": "R", "Piperacillin + Tazobactam": "R",
              "Ceftriaxone": "R", "Cefotaxime": "R", "Meropenem": "R", "Imipenem/Cilastatin": "R",
              "Ciprofloxacin": "R", "Levofloxacin": "R", "Trimethoprim/Sulfamethoxazole": "R",
              "Amoxicillin + Clavulanic acid": "R", "Ampicillin/Sulbactam": "R",
              "Colistin": "R", "Fosfomycin": "R", "Doxycycline": "R", "Tetracycline": "R"}
    assert classify_mdr(ECOLI, full_r)["level"] == "PDR"
    assert classify_mdr(ECOLI, dict(full_r, Colistin="S"))["level"] == "XDR"
    # one S agent inside an otherwise-resistant category: XDR, never PDR
    assert classify_mdr(ECOLI, dict(full_r, Amikacin="S"))["level"] == "XDR"


def test_mdr_level_is_monotonic_when_an_s_becomes_r():
    base = {"Gentamicin": "R", "Ciprofloxacin": "R", "Trimethoprim/Sulfamethoxazole": "S",
            "Ceftriaxone": "S", "Meropenem": "S", "Piperacillin + Tazobactam": "S"}
    rank = {None: 0, "MDR": 1, "XDR": 2, "PDR": 3}
    before = rank[classify_mdr(ECOLI, base)["level"]]
    for d in [k for k, v in base.items() if v == "S"]:
        after = rank[classify_mdr(ECOLI, dict(base, **{d: "R"}))["level"]]
        assert after >= before, d


# ── phenotypes ────────────────────────────────────────────────────────────
def _ph(org, sir):
    return [p["phenotype"] for p in detect_resistance_phenotypes(org, sir)]


def test_mrsa_from_either_marker_or_from_the_name():
    assert _ph("Staphylococcus aureus", {"Cefoxitin": "R"}) == ["MRSA"]
    assert _ph("Staphylococcus aureus", {"Oxacillin": "R"}) == ["MRSA"]
    assert _ph("MRSA", {"Vancomycin": "S"}) == ["MRSA"]
    assert _ph("Staphylococcus aureus", {"Oxacillin": "S", "Vancomycin": "S"}) == []
    assert _ph("E. coli", {"Cefoxitin": "R"}) == []


def test_possible_mrsa_fallback():
    assert _ph("Staphylococcus aureus", {"Cephalexin": "R", "Vancomycin": "S"}) == ["Possible MRSA"]


def test_vre():
    assert _ph("Enterococcus faecalis", {"Vancomycin": "R"}) == ["VRE"]
    assert _ph("Enterococcus faecalis", {"Vancomycin": "S"}) == []
    assert _ph("VRE", {"Linezolid": "S"}) == ["VRE"]


def test_cre_covers_all_enterobacterales_but_not_imipenem_only_proteus():
    for org in ("E. coli", "Klebsiella oxytoca", "Morganella morganii", "Salmonella spp."):
        assert _ph(org, {"Meropenem": "R"}) == ["CRE"], org
    assert _ph("Proteus mirabilis", {"Imipenem/Cilastatin": "R", "Meropenem": "S"}) == []
    assert _ph("E. coli", {"Imipenem/Cilastatin": "R"}) == ["CRE"]
    assert _ph("Pseudomonas aeruginosa", {"Meropenem": "R"}) == ["CRPA"]


def test_crpa_means_carbapenem_resistance():
    assert _ph("Pseudomonas aeruginosa",
               {"Piperacillin + Tazobactam": "R", "Ceftazidime": "R",
                "Meropenem": "S", "Imipenem/Cilastatin": "S"}) == []
    assert _ph("Pseudomonas aeruginosa", {"Imipenem/Cilastatin": "R"}) == ["CRPA"]
    assert _ph("Acinetobacter baumannii", {"Meropenem": "R"}) == ["CRAB"]


def test_phenotypes_empty_inputs():
    assert _ph("E. coli", {}) == [] and _ph("", {"Meropenem": "R"}) == []
