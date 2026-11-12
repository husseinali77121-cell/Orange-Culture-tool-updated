"""Public API of the clinical decision logic - Orange Lab Microbiology CDSS.

This file is a FACADE. The logic lives in the `cdss` package, one small module
per responsibility (see cdss/__init__.py); everything the UI, the report
builders, the OCR layer and the test suites import is re-exported from here so
those callers do not need to know the internal layout.

Nothing in this file may contain clinical logic.
"""
import logging
from typing import Dict

from abx_guidelines import ABX_GUIDELINES                          # noqa: F401
from organism_profile import ORGANISM_PROFILE                      # noqa: F401
from clinical_data import INTRINSIC_RESISTANCE                     # noqa: F401

from cdss.util import (build_banned_item, fuzzy_match, get_route_label,   # noqa: F401
                       safe_int, uniq_keep_order)
from cdss.sir import normalize_sir, normalize_sir_map              # noqa: F401
from cdss.organisms import identify as identify_organism          # noqa: F401
from cdss.organisms import intrinsic_drugs, strip_intrinsic        # noqa: F401
from cdss.organisms import canon_org as _canon_org                 # noqa: F401
from cdss.organisms import org_in as _org_in                       # noqa: F401
from cdss.specimens import SPECIMEN_CATEGORIES, classify_specimen  # noqa: F401
from cdss.renal import calc_creatinine_clearance, get_renal_severity  # noqa: F401
from cdss.mechanisms import predict_esbl                           # noqa: F401
from cdss.mdr import classify_mdr                                  # noqa: F401
from cdss.phenotypes import detect_resistance_phenotypes           # noqa: F401
from cdss.disposition import analyze_antibiotics, is_intrinsically_avoided  # noqa: F401
from cdss.pathogenicity import assess_pathogenicity, _parse_cfu, _parse_pus  # noqa: F401
from cdss.severity import suggest_severity                         # noqa: F401
from cdss.regimen_notes import annotate_regimen_note               # noqa: F401
from cdss.duration import get_treatment_duration                   # noqa: F401
from cdss.stewardship import (evaluate_deescalation, evaluate_iv_po_switch,  # noqa: F401
                              get_combination_therapy, get_hepatic_recommendations)
from cdss.qc import compute_qa_confidence, run_ast_qc              # noqa: F401
from cdss.ranking import rank_sensitive_antibiotics                # noqa: F401
from cdss.syndromes import get_infection_syndrome                  # noqa: F401

logger = logging.getLogger("orange_lab.engines")


def _remove_intrinsic_resistance(organism: str, sir_map: Dict[str, str]) -> Dict[str, str]:
    """Back-compat name for cdss.organisms.strip_intrinsic."""
    return strip_intrinsic(organism, sir_map)
