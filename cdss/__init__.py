"""Orange Lab Microbiology CDSS - pure clinical logic.

Layout (each module is small, has no Streamlit dependency, and has its own
test file under tests/):

    sir            S/I/R normalisation at the engine boundary
    organisms      ONE organism resolver (identity, groups, intrinsic lookup)
    drugs          typed drug facts (family, beta-lactam?, urine-only?)
    specimens      ONE specimen classifier
    renal          creatinine clearance
    mechanisms     ESBL / AmpC / carbapenemase inference
    mdr            MDR / XDR / PDR (Magiorakos 2012)
    phenotypes     MRSA / VRE / CRE / CRAB / CRPA
    disposition/   per-drug rules -> allowed / warned / banned
    ranking, duration, severity, stewardship, syndromes, pathogenicity, qc

`clinical_engines.py` at the repo root re-exports the public API so the UI and
report code keep importing from one place.
"""
__version__ = "2.0.0"
