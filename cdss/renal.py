"""Renal function estimation (Cockcroft-Gault / bedside Schwartz)."""
from __future__ import annotations

from typing import Optional

def calc_creatinine_clearance(age: int, weight: float, scr: float, sex: str,
                              height_cm: Optional[float] = None) -> float:
    """Estimate renal function.

    • Adults (≥18y): Cockcroft-Gault (CrCl, mL/min).
    • Children (<18y): Bedside Schwartz eGFR (mL/min/1.73m²) — the validated
      pediatric equation. Cockcroft-Gault is NOT validated in children and must
      not be used for them. Schwartz needs HEIGHT; if height_cm isn't supplied
      it's estimated from age (rougher — pass a real height whenever possible).
    """
    if scr <= 0:
        return 0.0
    if age < 18:
        # Bedside Schwartz (2009, IDMS-traceable): eGFR = 0.413 × height(cm) / SCr
        h = height_cm if (height_cm and height_cm > 0) else None
        if h is None:
            # Fallback height estimate from age when none is provided.
            h = (50 + age * 25) if age < 1 else (6 * age + 77)
        return (0.413 * float(h)) / scr
    # Adult Cockcroft-Gault
    crcl = ((140 - age) * weight) / (72 * scr)
    if sex == "Female":
        crcl *= 0.85
    return crcl

def get_renal_severity(crcl: float) -> str:
    if crcl >= 60:
        return "Mild"
    if crcl >= 30:
        return "Moderate"
    return "Severe"
