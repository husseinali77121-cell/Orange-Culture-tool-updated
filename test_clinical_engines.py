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
    Carbapenems while Imipenem is S. The previous 'any R/I in category' rule
    wrongly produced XDR for this exact isolate; correct Magiorakos scoring is
    MDR. (Enterobacterales panel: the resistant categories are Aminoglycosides,
    Folate PI and Penicillins+BLI — a genuine MDR with 3 closed categories.)"""
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
    # Carbapenems (Imipenem S), FQ (Norflox/Oflox S), Tetracyclines (Doxy S) are
    # all rescued by a susceptible agent. Cephalosporins-3rd-AP is NOT part of
    # the Enterobacterales panel (it is a Pseudomonas concept), so it is absent.
    for cat in ("Carbapenems", "Fluoroquinolones", "Tetracyclines"):
        assert cat in res["susceptible_categories"], f"{cat} should be rescued by its S agent"
    assert "Cephalosporins-3rd-AP" not in res["susceptible_categories"]
    assert "Cephalosporins-3rd-AP" not in res["resistant_categories"]
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
    """A genuinely pan-resistant panel where each resistant category is
    confirmed by ≥2 agents must classify as PDR."""
    sir = {
        "Gentamicin": "R", "Amikacin": "R",                       # Aminoglycosides
        "Ceftriaxone": "R", "Cefotaxime": "R",                    # Ext-Sp Ceph
        "Imipenem/Cilastatin": "R", "Meropenem": "R", "Ertapenem": "R",  # Carbapenems
        "Ciprofloxacin": "R", "Ofloxacin": "R", "Norfloxacin": "R",      # FQ
        "Doxycycline": "R", "Tetracycline": "R",                  # Tetracyclines
        "Piperacillin + Tazobactam": "R",                        # Antipseudomonal (single, ok)
        "Trimethoprim/Sulfamethoxazole": "R",                    # Folate (single, ok)
    }
    res = E.classify_mdr("Klebsiella pneumoniae", sir)
    assert res["level"] == "PDR"


def test_classify_mdr_all_single_drug_pan_resistant_capped_to_mdr():
    """Pan-resistant BUT every category rests on a single agent -> hold at MDR
    with a warning rather than over-calling PDR (thin evidence)."""
    sir = {"Gentamicin": "R", "Ceftriaxone": "R", "Imipenem/Cilastatin": "R",
           "Ciprofloxacin": "R", "Trimethoprim/Sulfamethoxazole": "R",
           "Amoxicillin + Clavulanic acid": "R", "Colistin": "R"}
    res = E.classify_mdr("Klebsiella pneumoniae", sir)
    assert res["level"] == "MDR"
    assert any("thin" in w or "XDR/PDR" in w for w in res["warnings"])


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


# ── AST QC (QC006) must name the ACTUAL resistant 3rd-gen, and never crash ──
def _qc006_msg(sir):
    for i in E.run_ast_qc("Klebsiella spp.", sir):
        if i["id"] == "QC006":
            return i["message"]
    return None


def test_qc006_names_cefotaxime_when_ceftriaxone_absent():
    """REGRESSION (real report, Klebsiella urine, MB 12923265): the panel had
    Cefotaxime-R (no Ceftriaxone tested). The message must name Cefotaxime, not
    a hardcoded 'Ceftriaxone' that never appeared on the AST."""
    sir = {"Cephalexin": "S", "Cefotaxime": "R", "Cefuroxime sodium": "R"}
    msg = _qc006_msg(sir)
    assert msg is not None, "QC006 must fire for Cefotaxime-R + Cephalexin-S"
    assert "Cefotaxime-R" in msg
    assert "Ceftriaxone" not in msg


def test_qc006_still_fires_and_does_not_crash():
    """The message carries {r_drug} + {drugs} placeholders; substitution order
    must not raise KeyError (which previously swallowed the whole rule)."""
    assert "Ceftriaxone-R" in _qc006_msg({"Cephalexin": "S", "Ceftriaxone": "R"})
    both = _qc006_msg({"Cephalexin": "S", "Ceftriaxone": "R", "Cefotaxime": "R"})
    assert "Ceftriaxone" in both and "Cefotaxime" in both


def test_qc006_silent_when_no_third_gen_resistant():
    assert _qc006_msg({"Cephalexin": "S", "Ceftriaxone": "S"}) is None


# ── Ranking must be hierarchical: susceptibility gates everything ────────────
def test_ranking_sensitive_gates_before_intermediate():
    allowed = [
        {"name": "A_I_access_oral", "aware": "Access", "high_po": True, "priority": 1},
        {"name": "B_S_reserve_iv", "aware": "Reserve", "high_po": False, "priority": 5},
    ]
    sir = {"A_I_access_oral": "I", "B_S_reserve_iv": "S"}
    order = [x["name"] for x in
             E.rank_sensitive_antibiotics(allowed, "Urine", "E. coli", sir, [])]
    assert order == ["B_S_reserve_iv", "A_I_access_oral"]


# ── ESBL thin-panel confidence ──────────────────────────────────────────────
def test_esbl_thin_panel_lowers_confidence():
    r = E.predict_esbl("Escherichia coli", {"Ceftriaxone": "R", "Meropenem": "S"})
    assert r["confidence"] <= 45 and r["probability"] == "moderate"


def test_esbl_broad_panel_keeps_confidence():
    r = E.predict_esbl("Escherichia coli",
                       {"Ceftriaxone": "R", "Cefotaxime": "S", "Ceftazidime": "S",
                        "Meropenem": "S"})
    assert r["confidence"] >= 70 and r["probability"] == "high"


# ── Enterococcus + TMP-SMX: in-vitro S but clinically unreliable ─────────────
def test_enterococcus_tmp_smx_banned_despite_S():
    a, w, b, p, i = E.analyze_antibiotics(
        ["Trimethoprim/Sulfamethoxazole", "Ampicillin"], "Enterococcus faecalis",
        "Urine", 40, "Male", False, 90, False, False, [],
        {"Trimethoprim/Sulfamethoxazole": "S", "Ampicillin": "S"})
    banned = {x["name"] for x in b}
    allowed = {x["name"] for x in a}
    assert "Trimethoprim/Sulfamethoxazole" in banned
    assert "Ampicillin" in allowed


# ── Guidelines audit: organism-specific Magiorakos MDR panels ───────────────
def test_mdr_nitrofurantoin_not_counted_for_enterobacterales():
    """Nitrofurantoin is a urinary-only agent, NOT an MDR category in the
    Magiorakos Enterobacteriaceae table -> Nitrofurantoin-R alone must not
    contribute a resistant category for E. coli."""
    res = E.classify_mdr("E. coli", {"Nitrofurantoin": "R",
                                     "Ceftriaxone": "S", "Gentamicin": "S"})
    assert res["level"] is None
    assert "Nitrofurans" not in res.get("resistant_categories", [])


def test_mdr_pseudomonas_uses_monobactam_panel():
    """Pseudomonas panel includes Monobactams (Aztreonam) and excludes
    Ertapenem (intrinsic R)."""
    sir = {"Ceftazidime": "R", "Cefepime": "R", "Meropenem": "R",
           "Ciprofloxacin": "R", "Gentamicin": "R", "Amikacin": "R",
           "Piperacillin + Tazobactam": "R", "Aztreonam": "R", "Colistin": "S"}
    res = E.classify_mdr("Pseudomonas aeruginosa", sir)
    assert res["level"] in ("MDR", "XDR")
    # Aztreonam (Monobactams) participates -> counted
    assert res["total_tested"] >= 8


def test_mdr_acinetobacter_counts_ampicillin_sulbactam():
    """Ampicillin/Sulbactam is a key Acinetobacter agent (Penicillins+BLI)."""
    sir = {"Ampicillin/Sulbactam": "R", "Meropenem": "R", "Ciprofloxacin": "R",
           "Gentamicin": "R", "Trimethoprim/Sulfamethoxazole": "R",
           "Colistin": "S", "Doxycycline": "S"}
    res = E.classify_mdr("Acinetobacter baumannii", sir)
    assert res["level"] == "MDR"


# ── Guidelines audit: expanded intrinsic resistance (EUCAST) ────────────────
def test_intrinsic_pseudomonas_drops_non_antipseudomonal():
    clean = E._remove_intrinsic_resistance(
        "Pseudomonas aeruginosa",
        {"Ampicillin": "S", "Ceftriaxone": "S", "Ciprofloxacin": "S", "Meropenem": "S"})
    assert "Ampicillin" not in clean and "Ceftriaxone" not in clean
    assert "Ciprofloxacin" in clean and "Meropenem" in clean


def test_intrinsic_stenotrophomonas_keeps_only_active():
    clean = E._remove_intrinsic_resistance(
        "Stenotrophomonas maltophilia",
        {"Meropenem": "S", "Gentamicin": "S",
         "Trimethoprim/Sulfamethoxazole": "S", "Levofloxacin": "S"})
    assert "Meropenem" not in clean and "Gentamicin" not in clean
    assert "Trimethoprim/Sulfamethoxazole" in clean and "Levofloxacin" in clean


def test_faecium_ampicillin_S_is_honoured_with_warning():
    """E. faecium ampicillin resistance is acquired (not intrinsic): a genuine S
    result is kept, but a warning is raised."""
    a, w, b, p, i = E.analyze_antibiotics(
        ["Ampicillin"], "Enterococcus faecium", "Urine", 40, "Male", False, 90,
        False, False, [], {"Ampicillin": "S"})
    assert "Ampicillin" in {x["name"] for x in a}
    assert any("faecium" in x for x in i)


# ─────────────────────────────────────────────────────────────────────────
# REGRESSION — specimen classification unification (non-urine review fixes)
# ─────────────────────────────────────────────────────────────────────────
def test_classify_specimen_dropdown_specimens():
    """The 7 dropdown specimens must map to their intended categories."""
    assert E.classify_specimen("Urine") == "urine"
    assert E.classify_specimen("Blood") == "blood"
    assert E.classify_specimen("Sputum") == "sputum"
    assert E.classify_specimen("Wound Swab") == "wound"
    assert E.classify_specimen("Pus") == "wound"
    assert E.classify_specimen("Stool") == "stool"
    assert E.classify_specimen("CSF") == "csf"


def test_classify_specimen_swab_precedence():
    """A bare 'swab' must not hijack site-specific specimens."""
    assert E.classify_specimen("Rectal swab") == "stool"
    assert E.classify_specimen("Throat swab") == "throat"
    assert E.classify_specimen("High vaginal swab") == "genital"
    assert E.classify_specimen("Endocervical swab") == "genital"
    # only a true wound/pus/tissue swab is a wound
    assert E.classify_specimen("Wound swab") == "wound"
    assert E.classify_specimen("Pus swab") == "wound"


def test_classify_specimen_lower_respiratory_vs_sputum():
    """Expectorated sputum → 'sputum' (M-W); BAL/bronchial/tracheal →
    'respiratory' (no M-W)."""
    assert E.classify_specimen("Sputum") == "sputum"
    assert E.classify_specimen("BAL") == "respiratory"
    assert E.classify_specimen("Bronchial washing") == "respiratory"
    assert E.classify_specimen("Tracheal aspirate") == "respiratory"


def test_bal_scored_without_murray_washington():
    """BAL must NOT be rejected by Murray-Washington: passing no WBC/epi counts
    (as the UI does for respiratory) must not trigger MW_REJECT, and BAL should
    still score as a real respiratory infection for a recognised pathogen."""
    res = E.assess_pathogenicity(
        "BAL", "Klebsiella pneumoniae", "", "Pure growth",
        ["Productive cough / Purulent sputum", "Fever (> 38°C)"],
        "", "", "WBCs + Gram Negative Rods", 55, "Male", [],
        # respiratory path passes NO sputum_pus_cells / sputum_epithelial
    )
    assert "MW_REJECT" not in res["special_flags"]
    assert res["score"] >= 50


def test_throat_swab_not_scored_as_wound():
    """A throat swab must fall to generic scoring, never the wound branch."""
    res = E.assess_pathogenicity(
        "Throat swab", "Streptococcus pneumoniae", "", "Pure growth",
        ["Sore throat"], "", "", "مش متعملة", 20, "Male", [],
        wound_type="Deep tissue / Abscess",  # must be ignored for a throat swab
    )
    # wound-type bonus (+15 surgical / +10 chronic) must NOT be applied
    assert not any("wound" in f.lower() for f in res["factors_pos"])


# ─────────────────────────────────────────────────────────────────────────
# REGRESSION — unified engine return contracts (no None / complete dicts)
# ─────────────────────────────────────────────────────────────────────────
def test_predict_esbl_always_full_dict():
    for org, sir in [("Escherichia coli", {}),                 # empty
                     ("Staphylococcus aureus", {"Ceftriaxone": "R"}),  # non-producer
                     ("Escherichia coli", {"Gentamicin": "S"})]:       # 'low'
        r = E.predict_esbl(org, sir)
        for k in ("probability", "confidence", "mechanism", "markers_R",
                  "detail", "action"):
            assert k in r, f"predict_esbl missing key {k} for {org}/{sir}"


def test_classify_mdr_always_full_dict():
    for org, sir in [("Escherichia coli", {}),
                     ("Escherichia coli", {"Ceftriaxone": "S"}),
                     ("Escherichia coli", {"Ceftriaxone": "R", "Ciprofloxacin": "R",
                                           "Gentamicin": "R"})]:
        r = E.classify_mdr(org, sir)
        for k in ("level", "resistant_categories", "susceptible_categories",
                  "total_tested", "resistant_count", "single_drug_categories",
                  "reliable", "warnings", "gram"):
            assert k in r, f"classify_mdr missing key {k} for {org}/{sir}"


# ─────────────────────────────────────────────────────────────────────────
# REGRESSION — pediatric CrCl uses Schwartz, not Cockcroft-Gault
# ─────────────────────────────────────────────────────────────────────────
def test_crcl_child_uses_schwartz():
    """For a child, the estimate must follow bedside Schwartz (0.413·ht/SCr),
    which is independent of Cockcroft-Gault's (140−age)·wt term."""
    age, scr, height = 5, 0.4, 110.0
    expected = 0.413 * height / scr
    got = E.calc_creatinine_clearance(age, 18, scr, "Male", height_cm=height)
    assert abs(got - expected) < 0.5
    # adult path stays Cockcroft-Gault
    adult = E.calc_creatinine_clearance(40, 80, 1.0, "Male")
    assert abs(adult - ((140 - 40) * 80) / (72 * 1.0)) < 0.5


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
