"""Foundations: result normalisation, organism identity, drug facts."""
import pytest

from abx_guidelines import ABX_GUIDELINES
from clinical_data import INTRINSIC_RESISTANCE
from organism_profile import ORGANISM_PROFILE
from cdss import drugs as D
from cdss.organisms import (identify, intrinsic_drugs, intrinsic_table_keys,
                            is_intrinsic, matches_any, org_in, strip_intrinsic)
from cdss.sir import normalize_sir, normalize_sir_map


# ── sir ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [
    ("S", "S"), ("s", "S"), (" r ", "R"), ("Resistant", "R"), ("SENSITIVE", "S"),
    ("Intermediate", "I"), ("SDD", "I"), ("مقاوم", "R"), ("حساس", "S"),
    ("", None), (None, None), ("Positive", None), ("X", None), (3, None),
])
def test_normalize_sir(raw, expected):
    assert normalize_sir(raw) == expected


def test_normalize_sir_map_keeps_non_sir_observations_and_drops_blanks():
    out = normalize_sir_map({"Ciprofloxacin": "r", "D-test": " Negative ",
                             "Amikacin": "", "Cefepime": None, " ": "S"})
    assert out == {"Ciprofloxacin": "R", "D-test": "Negative"}
    assert normalize_sir_map(None) == {}


# ── organisms ─────────────────────────────────────────────────────────────
def test_empty_and_unknown_organisms_belong_to_no_group():
    for name in ("", None, "   ", "Unknown bug"):
        org = identify(name)
        assert org.groups == frozenset()
        assert intrinsic_drugs(name or "") == frozenset()
    assert not identify("").known


@pytest.mark.parametrize("name,key", [
    ("E. coli", "escherichia coli"), ("Escherichia coli", "escherichia coli"),
    ("  e.COLI ", "escherichia coli"), ("MRSA", "staphylococcus aureus"),
    ("MSSA", "staphylococcus aureus"), ("H. influenzae", "haemophilus influenzae"),
    ("Klebsiella aerogenes", "enterobacter aerogenes"),
    ("Anaerobes (لاهوائيات)", "anaerobes"), ("VRE", "enterococcus spp."),
])
def test_canonical_key(name, key):
    assert identify(name).key == key


def test_groups():
    assert identify("MRSA").is_("name_mrsa") and identify("MRSA").is_("s_aureus")
    assert not identify("Staphylococcus aureus").is_("name_mrsa")
    assert identify("Methicillin-resistant Staphylococcus aureus").is_("name_mrsa")
    assert identify("VRE").is_("name_vre") and identify("VRE").is_("enterococcus")
    assert identify("Proteus mirabilis").is_("morganellaceae")
    assert identify("E. coli").is_("esbl_capable") and not identify("E. coli").is_("ampc_inducible")
    assert identify("Pseudomonas aeruginosa").is_("ampc_inducible")
    assert not identify("Pseudomonas aeruginosa").is_("esbl_capable")
    assert not identify("Citrobacter koseri").is_("ampc_inducible")
    for n in ("Enterobacter cloacae", "Klebsiella aerogenes", "Citrobacter freundii"):
        assert identify(n).is_("ampc_high_risk"), n
    assert not identify("Serratia marcescens").is_("ampc_high_risk")
    assert identify("Enterococcus faecium").is_("e_faecium")
    assert identify("Salmonella spp.").is_("enterobacterales")
    assert not identify("Salmonella spp.").is_("esbl_capable")


@pytest.mark.parametrize("name,gram", [
    ("E. coli", "negative"), ("Acinetobacter baumannii", "negative"),
    ("Staphylococcus aureus", "positive"), ("MRSA", "positive"), ("VRE", "positive"),
    ("Listeria monocytogenes", "positive"), ("Mycoplasma spp.", None),
    ("Anaerobes (لاهوائيات)", None), ("", None),
])
def test_gram(name, gram):
    assert identify(name).gram == gram


def test_every_ui_organism_is_identified():
    for name in ORGANISM_PROFILE:
        assert identify(name).known, name


def test_intrinsic_lookup_is_exact_not_substring():
    # species row
    assert is_intrinsic("Klebsiella pneumoniae", "Ampicillin")
    assert not is_intrinsic("Klebsiella pneumoniae", "Amoxicillin + Clavulanic acid")
    # K. aerogenes is an AmpC organism, not a penicillinase-only Klebsiella
    assert is_intrinsic("Klebsiella aerogenes", "Amoxicillin + Clavulanic acid")
    assert is_intrinsic("Klebsiella aerogenes", "Cefoxitin")
    # genus-only name uses the genus row, not the union of every species
    assert intrinsic_table_keys("Proteus") == ("proteus spp.",)
    assert not is_intrinsic("Proteus", "Cefazolin")          # P. vulgaris-only
    assert is_intrinsic("Proteus vulgaris", "Cefazolin")
    # names the table spells differently
    assert is_intrinsic("MRSA", "Aztreonam")
    assert is_intrinsic("Salmonella spp.", "Gentamicin")
    assert is_intrinsic("VRE", "Vancomycin")
    assert is_intrinsic("Staphylococcus epidermidis", "Colistin")
    # Acinetobacter / sulbactam asymmetry
    assert is_intrinsic("Acinetobacter baumannii", "Amoxicillin + Clavulanic acid")
    assert not is_intrinsic("Acinetobacter baumannii", "Ampicillin/Sulbactam")
    # Serratia tetracycline nuance
    assert is_intrinsic("Serratia marcescens", "Doxycycline")
    assert not is_intrinsic("Serratia marcescens", "Tigecycline")
    # wild-type E. coli has no intrinsic resistance in the table
    assert intrinsic_drugs("E. coli") == frozenset()


def test_every_table_row_is_reachable_by_its_own_name():
    for key, drugs in INTRINSIC_RESISTANCE.items():
        assert set(drugs) <= set(intrinsic_drugs(key)), key


def test_strip_intrinsic_copies():
    sir = {"Ampicillin": "R", "Meropenem": "S"}
    out = strip_intrinsic("Klebsiella spp.", sir)
    assert out == {"Meropenem": "S"} and "Ampicillin" in sir
    assert strip_intrinsic("", sir) == sir


def test_matches_any():
    assert matches_any("Escherichia coli", ["E. coli"])
    assert matches_any("Klebsiella pneumoniae", ["Klebsiella spp."])
    assert matches_any("MRSA", ["Staphylococcus aureus"])
    assert not matches_any("Klebsiella pneumoniae", ["Klebsiella oxytoca"])
    assert not matches_any("", ["E. coli"])
    assert not matches_any("Pseudomonas aeruginosa", ["E. coli", "Proteus mirabilis"])


def test_org_in_never_matches_empty():
    assert org_in("E. coli", ["Escherichia coli"])
    assert not org_in("", ["", "Escherichia coli"])


# ── drugs ─────────────────────────────────────────────────────────────────
def test_every_formulary_drug_has_an_explicit_family():
    missing = set(ABX_GUIDELINES) - set(D.DRUG_FAMILY)
    assert not missing, f"add these to cdss.drugs.DRUG_FAMILY: {sorted(missing)}"
    stale = set(D.DRUG_FAMILY) - set(ABX_GUIDELINES)
    assert not stale, f"not in the formulary any more: {sorted(stale)}"


def test_inhibitor_combinations_are_beta_lactams():
    for d in ("Amoxicillin + Clavulanic acid", "Ampicillin/Sulbactam",
              "Piperacillin + Tazobactam", "Cefoperazone + Sulbactam"):
        assert D.is_beta_lactam(d) and D.is_bli_combination(d), d
    assert D.family("Cefoperazone + Sulbactam") == D.CEPHALOSPORIN_BLI
    assert D.family("Cefoxitin") == D.CEPHAMYCIN
    assert D.family("Aztreonam") == D.MONOBACTAM and D.is_beta_lactam("Aztreonam")
    assert not D.is_beta_lactam("Ciprofloxacin")
    assert D.is_carbapenem("Ertapenem") and not D.is_carbapenem("Cefepime")


def test_family_agrees_with_class_label_where_the_label_is_informative():
    for drug in ABX_GUIDELINES:
        inferred = D._infer_family(drug)
        if inferred != D.OTHER:
            assert inferred == D.family(drug), drug


def test_special_sets_only_name_formulary_drugs():
    for s in (D.URINE_ONLY, D.URINE_ONLY_EXCEPT_GI, D.THIRD_GEN_CEPHALOSPORINS):
        assert s <= set(ABX_GUIDELINES)
    assert D.URINE_ONLY_EXCEPT_GI <= D.URINE_ONLY
