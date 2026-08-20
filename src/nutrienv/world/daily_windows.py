"""Mifflin×PAL energy and FDA six-key daily windows (ADR 0014).

Bench imports this. The formula does not live in Bench.
"""

from __future__ import annotations

from .dri import DRI_REFERENCE

__all__ = [
    "ACTIVITY_PAL",
    "CUT_KCAL_DELTA",
    "MUSCLE_PROTEIN_G_PER_KG",
    "derive_daily_windows",
]


ACTIVITY_PAL: dict[str, float] = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Canonical cut lands in ADR 0015's [EER−500, EER−100] kcal-hi band.
CUT_KCAL_DELTA = 300.0
# Hypertrophy protein floor: above the 0.8 g/kg maintain lo (ADR 0015).
MUSCLE_PROTEIN_G_PER_KG = 1.6

_FDA_KCAL = DRI_REFERENCE["kcal"]["reference"]


def derive_daily_windows(
    *,
    sex: str,
    age_y: int,
    height_cm: float,
    weight_kg: float,
    activity: str,
    phase: str = "maintain",
) -> dict[str, tuple[float, float]]:
    """Daily (lo, hi) windows from body facts, PAL, and the FDA DV template."""
    pal = ACTIVITY_PAL[activity]
    bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_y
    if sex == "male":
        bmr += 5.0
    else:
        bmr -= 161.0
    eer = bmr * pal
    scale = eer / _FDA_KCAL
    protein_lo = 0.8 * weight_kg
    protein_dv = DRI_REFERENCE["protein_g"]["reference"] * scale
    protein_hi = max(protein_dv, protein_lo)
    kcal_lo = eer
    kcal_hi = eer
    if phase == "cut":
        kcal_lo = eer - CUT_KCAL_DELTA
        kcal_hi = eer - CUT_KCAL_DELTA
    elif phase == "muscle":
        protein_lo = MUSCLE_PROTEIN_G_PER_KG * weight_kg
        protein_hi = max(protein_hi, protein_lo)
    return {
        "kcal": (kcal_lo, kcal_hi),
        "protein_g": (protein_lo, protein_hi),
        "carb_g": (
            DRI_REFERENCE["carb_g"]["reference"] * scale,
            DRI_REFERENCE["carb_g"]["reference"] * scale,
        ),
        "fat_g": (
            DRI_REFERENCE["fat_g"]["reference"] * scale,
            DRI_REFERENCE["fat_g"]["reference"] * scale,
        ),
        "fiber_g": (
            DRI_REFERENCE["fiber_g"]["reference"] * scale,
            DRI_REFERENCE["fiber_g"]["reference"] * scale,
        ),
        "sodium_mg": (0.0, 2300.0),
    }
