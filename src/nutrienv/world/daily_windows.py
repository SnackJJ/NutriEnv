"""Mifflin×PAL energy and six-key daily windows: AMDR macros, FDA DV fiber/sodium (ADR 0014).

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
    "BAND_WINDOW_KEYS",
    "MEAL_ENERGY_SHARE",
    "AMDR_ENERGY_SHARE",
    "SIX_WINDOW_KEYS",
    "TARGET_CEILING_KEYS",
    "TARGET_CEILING_SLACK",
    "judged_ceiling",
    "derive_daily_windows",
    "derive_profile_windows",
    "estimated_energy_requirement",
    "implicit_windows_pass",
    "plan_windows_for_meal",
    "meal_slot_and_remainder",
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
MUSCLE_PROTEIN_MAX_G_PER_KG = 2.2
# Benchmark definition of a requested high-protein meal, not a medical safety limit.
HIGH_PROTEIN_ENERGY_SHARE = 0.20
HIGH_PROTEIN_MIN_GRAMS = 10.0


def high_protein_pass(totals: dict[str, float]) -> bool:
    """Explicit meal rubric; the gram floor excludes trace-protein low-energy items."""
    energy = totals.get("kcal", 0.0)
    protein = totals.get("protein_g", 0.0)
    return (
        energy > 0
        and protein >= HIGH_PROTEIN_MIN_GRAMS - 1e-8
        and 4.0 * protein >= HIGH_PROTEIN_ENERGY_SHARE * energy - 1e-8
    )
UPDATE_BANDS = frozenset({"cut", "fatigue", "muscle"})
BAND_WINDOW_KEYS: dict[str, frozenset[str]] = {
    "cut": frozenset({"kcal", "protein_g", "carb_g", "fat_g", "fiber_g"}),
    "fatigue": frozenset({"kcal", "protein_g", "carb_g", "fat_g", "fiber_g"}),
    "muscle": frozenset({"kcal", "protein_g"}),
}
_PROTEIN_G_PER_KG = 0.8

_FDA_KCAL = DRI_REFERENCE["kcal"]["reference"]

# ADR 0014 meal energy share (中国居民膳食指南 2022). Snack carries no
# prescribed share: the slot imposes no floor and caps at the day.
MEAL_ENERGY_SHARE: dict[str, tuple[float, float]] = {
    "breakfast": (0.25, 0.30),
    "lunch": (0.30, 0.40),
    "dinner": (0.30, 0.40),
    "snack": (0.0, 1.0),
}
SIX_WINDOW_KEYS: tuple[str, ...] = (
    "kcal",
    "protein_g",
    "carb_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
)

# Acceptable Macronutrient Distribution Ranges (IOM 2005, adults): each macro's share of the
# target energy, as (lo, hi) share and kcal per gram. Ordinary protein also meets the RDA;
# muscle uses a separate 1.6–2.2 g/kg target range, not a toxicity threshold.
AMDR_ENERGY_SHARE: dict[str, tuple[float, float, float]] = {
    "protein_g": (0.10, 0.35, 4.0),
    "carb_g": (0.45, 0.65, 4.0),
    "fat_g": (0.20, 0.35, 9.0),
}

# The daily fiber hi is a scaled FDA Daily Value: a reference intake, not a limit, so going
# slightly over it is not a nutrition error and a plan's fiber ceiling is judged with this slack.
# The AMDR ceilings are the edge of a range and sodium's is a health limit, so they stay exact, as
# does kcal's (the meal-share band is its give) and every floor.
TARGET_CEILING_KEYS = frozenset({"fiber_g"})
TARGET_CEILING_SLACK = 0.15


def judged_ceiling(key: str, hi: float) -> float:
    """The ceiling a plan is judged against for ``key``'s published ``hi``."""
    if key in TARGET_CEILING_KEYS:
        return hi * (1.0 + TARGET_CEILING_SLACK)
    return hi


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
    """Daily (lo, hi) windows from body facts, PAL, AMDR and the FDA DV template."""
    eer = estimated_energy_requirement(
        sex=sex,
        age_y=age_y,
        height_cm=height_cm,
        weight_kg=weight_kg,
        activity=activity,
    )
    protein_lo = _PROTEIN_G_PER_KG * weight_kg
    kcal_lo = eer
    kcal_hi = eer
    if phase == "cut":
        kcal_lo = eer - CUT_KCAL_DELTA
        kcal_hi = eer - CUT_KCAL_DELTA
    elif phase == "muscle":
        protein_lo = MUSCLE_PROTEIN_G_PER_KG * weight_kg

    if kcal_lo <= 0:
        raise ValueError(f"target energy must be positive, got {kcal_lo} kcal/day")
    scale = kcal_hi / _FDA_KCAL
    def amdr(key: str) -> tuple[float, float]:
        share_lo, share_hi, kcal_per_g = AMDR_ENERGY_SHARE[key]
        return kcal_lo * share_lo / kcal_per_g, kcal_hi * share_hi / kcal_per_g

    amdr_lo, protein_hi = amdr("protein_g")
    protein_lo = max(amdr_lo, protein_lo)
    if phase == "muscle":
        protein_lo = MUSCLE_PROTEIN_G_PER_KG * weight_kg
        protein_hi = MUSCLE_PROTEIN_MAX_G_PER_KG * weight_kg
    if protein_lo > protein_hi:
        raise ValueError(
            f"protein requirement {protein_lo} g exceeds target ceiling {protein_hi} g"
        )
    return {
        "kcal": (kcal_lo, kcal_hi),
        "protein_g": (protein_lo, protein_hi),
        "carb_g": amdr("carb_g"),
        "fat_g": amdr("fat_g"),
        "fiber_g": (
            DRI_REFERENCE["fiber_g"]["reference"] * scale,
            DRI_REFERENCE["fiber_g"]["reference"] * scale,
        ),
        "sodium_mg": (0.0, 2300.0),
    }


def meal_slot_and_remainder(
    daily: dict[str, tuple[float, float]],
    eaten: dict[str, float],
    occasion: str,
) -> tuple[dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    """Slot windows and ledger remainder, before intersection."""
    if occasion not in MEAL_ENERGY_SHARE:
        raise ValueError(f"unknown occasion {occasion!r}")
    share_lo, share_hi = MEAL_ENERGY_SHARE[occasion]
    slot: dict[str, tuple[float, float]] = {}
    remainder: dict[str, tuple[float, float]] = {}
    # ADR 0014: judged intervals for ALL SIX catalog nutrients. A caller
    # with a partial window dict fails loudly here instead of silently
    # widening the judged keys.
    for key in SIX_WINDOW_KEYS:
        daily_lo, daily_hi = daily[key]
        used = float(eaten.get(key, 0.0))
        remainder[key] = (
            round(max(0.0, daily_lo - used), 2),
            round(max(0.0, daily_hi - used), 2),
        )
        if key == "kcal":
            slot[key] = (
                round(daily_lo * share_lo, 2),
                round(daily_hi * share_hi, 2),
            )
        else:
            slot[key] = (0.0, round(daily_hi, 2))
    return slot, remainder


def plan_windows_for_meal(
    daily: dict[str, tuple[float, float]],
    eaten: dict[str, float],
    occasion: str,
    *,
    last_meal: bool = False,
) -> dict[str, tuple[float, float]] | None:
    """Meal-slot ∩ remainder over the six catalog nutrients (ADR 0014).

    Energy share applies to kcal. Breakfast/lunch do not take the full-day
    protein/fiber floor, even as last_meal. Remainder lo binds on other keys
    only when ``last_meal``. Remainder hi always caps. Empty intersection
    (any key lo > hi) returns None so the mill can drop it.
    """
    slot, remainder = meal_slot_and_remainder(daily, eaten, occasion)
    out: dict[str, tuple[float, float]] = {}
    for key in SIX_WINDOW_KEYS:
        slot_lo, slot_hi = slot[key]
        rem_lo, rem_hi = remainder[key]
        hi = min(slot_hi, rem_hi)
        apply_rem_lo = last_meal and not (
            key in {"protein_g", "fiber_g"} and occasion in {"breakfast", "lunch"}
        )
        lo = max(slot_lo, rem_lo) if apply_rem_lo else slot_lo
        if lo > hi:
            return None
        out[key] = (lo, hi)
    return out


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
