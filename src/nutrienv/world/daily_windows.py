"""Mifflin×PAL energy and FDA six-key daily windows (ADR 0014).

Bench imports this. The formula does not live in Bench.
"""

from __future__ import annotations

from .dri import DRI_REFERENCE
from .types import PHASES, Profile

__all__ = [
    "ACTIVITY_PAL",
    "CUT_KCAL_DELTA",
    "MUSCLE_PROTEIN_G_PER_KG",
    "UPDATE_BANDS",
    "derive_daily_windows",
    "derive_profile_windows",
    "estimated_energy_requirement",
    "implicit_windows_pass",
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
UPDATE_BANDS = frozenset({"cut", "fatigue", "muscle"})
_PROTEIN_G_PER_KG = 0.8

_FDA_KCAL = DRI_REFERENCE["kcal"]["reference"]


def estimated_energy_requirement(
    *,
    sex: str,
    age_y: int,
    height_cm: float,
    weight_kg: float,
    activity: str,
) -> float:
    """Mifflin-St Jeor BMR × PAL, kcal/day."""
    pal = ACTIVITY_PAL[activity]
    bmr = 10.0 * weight_kg + 6.25 * height_cm - 5.0 * age_y
    bmr += 5.0 if sex == "male" else -161.0
    return bmr * pal


def implicit_windows_pass(
    band: str,
    windows: dict[str, tuple[float, float]],
    *,
    eer: float,
    weight_kg: float,
    s0_windows: dict[str, tuple[float, float]],
) -> bool:
    """Whether end windows fall in an ADR 0015 implicit-update band."""
    if band not in UPDATE_BANDS or "kcal" not in windows:
        return False
    kcal_lo, kcal_hi = windows["kcal"]
    if band == "cut":
        return eer - 500.0 <= kcal_hi <= eer - 100.0
    if band == "fatigue":
        if "kcal" not in s0_windows:
            return False
        return s0_windows["kcal"][1] < kcal_hi <= eer
    protein_lo = windows.get("protein_g", (0.0, 0.0))[0]
    return protein_lo > _PROTEIN_G_PER_KG * weight_kg and kcal_lo >= eer


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
    eer = estimated_energy_requirement(
        sex=sex,
        age_y=age_y,
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity=activity,
    )
    scale = eer / _FDA_KCAL
    protein_lo = _PROTEIN_G_PER_KG * weight_kg
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


def derive_profile_windows(
    profile: Profile,
) -> dict[str, tuple[float, float]] | None:
    """Derive daily windows from a Profile, or None if the body is incomplete."""
    if (
        profile.sex not in {"male", "female"}
        or profile.age_y is None
        or profile.height_cm is None
        or profile.weight_kg is None
        or profile.activity not in ACTIVITY_PAL
        or profile.phase not in PHASES
    ):
        return None
    return derive_daily_windows(
        sex=profile.sex,
        age_y=profile.age_y,
        height_cm=profile.height_cm,
        weight_kg=profile.weight_kg,
        activity=profile.activity,
        phase=profile.phase,
    )
