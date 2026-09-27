"""Daily windows are derived in the world from body facts × PAL (ADR 0014)."""

import pytest

from nutrienv.world.daily_windows import (
    derive_daily_windows,
    implicit_windows_pass,
    plan_windows_for_meal,
)


_ADA = dict(
    sex="female",
    age_y=34,
    height_cm=165.0,
    weight_kg=62.0,
)


def test_female_light_maintain_uses_mifflin_pal_and_fda_six_keys() -> None:
    """Ada: female, 34 y, 165 cm, 62 kg, light. Literals are the Mifflin arithmetic.

    BMR = 10·62 + 6.25·165 − 5·34 − 161 = 1320.25
    EER = 1320.25 × 1.375 = 1815.34375
    scale = EER / 2000
    protein lo = 0.8 × 62 = 49.6 (not the scaled 50 g DV)
    sodium hi stays 2300
    """
    windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    assert set(windows) == {
        "kcal",
        "protein_g",
        "carb_g",
        "fat_g",
        "fiber_g",
        "sodium_mg",
    }
    eer = 1815.34375
    assert windows["kcal"] == (eer, eer)
    assert windows["protein_g"] == (49.6, 49.6)
    assert windows["carb_g"] == (249.609765625, 249.609765625)
    assert windows["fat_g"] == (70.79840625, 70.79840625)
    assert windows["fiber_g"] == (25.4148125, 25.4148125)
    assert windows["sodium_mg"] == (0.0, 2300.0)


def test_male_same_body_uses_mifflin_plus_five() -> None:
    """Same Ada body as male: BMR = 1486.25, EER = 1486.25 × 1.375 = 2043.59375."""
    windows = derive_daily_windows(
        sex="male",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    eer = 2043.59375
    assert windows["kcal"] == (eer, eer)
    assert windows["protein_g"][0] == 49.6
    assert windows["carb_g"] == (280.994140625, 280.994140625)
    assert windows["sodium_mg"] == (0.0, 2300.0)


@pytest.mark.parametrize(
    "activity, eer",
    [
        ("sedentary", 1584.3),
        ("light", 1815.34375),
        ("moderate", 2046.3875),
        ("active", 2277.43125),
        ("very_active", 2508.475),
    ],
)
def test_pal_scales_energy_and_leaves_sodium_hi_at_2300(
    activity: str, eer: float
) -> None:
    """Ada BMR 1320.25 × each PAL. Sodium hi is the 2300 cap, not scaled."""
    windows = derive_daily_windows(activity=activity, phase="maintain", **_ADA)
    assert windows["kcal"] == (eer, eer)
    assert windows["sodium_mg"] == (0.0, 2300.0)
    assert windows["protein_g"][0] == 49.6


def test_cut_phase_puts_kcal_hi_in_the_published_deficit_band() -> None:
    """maintain → cut: kcal hi in [EER−500, EER−100] (ADR 0015). Ada EER 1815.34375."""
    eer = 1815.34375
    windows = derive_daily_windows(activity="light", phase="cut", **_ADA)
    kcal_lo, kcal_hi = windows["kcal"]
    assert eer - 500.0 <= kcal_hi <= eer - 100.0
    assert kcal_lo <= kcal_hi
    assert windows["sodium_mg"] == (0.0, 2300.0)
    assert windows["protein_g"][0] == 49.6


def test_muscle_phase_raises_protein_lo_and_keeps_kcal_lo_at_least_eer() -> None:
    """→ muscle: protein lo > 0.8 g/kg, kcal lo ≥ maintain EER (ADR 0015)."""
    eer = 1815.34375
    windows = derive_daily_windows(activity="light", phase="muscle", **_ADA)
    assert windows["protein_g"][0] > 49.6
    assert windows["kcal"][0] >= eer
    assert windows["kcal"][0] <= windows["kcal"][1]
    assert windows["sodium_mg"] == (0.0, 2300.0)


@pytest.mark.parametrize(
    "kcal_hi, ok",
    [
        (1315.34375, True),   # EER − 500
        (1715.34375, True),   # EER − 100
        (1315.34374, False),
        (1715.34376, False),
    ],
)
def test_cut_band_edges_are_the_published_eer_offsets(kcal_hi: float, ok: bool) -> None:
    eer = 1815.34375
    windows = {"kcal": (kcal_hi, kcal_hi)}
    assert (
        implicit_windows_pass(
            "cut", windows, eer=eer, weight_kg=62.0, s0_windows={}
        )
        is ok
    )


def test_fatigue_band_is_strictly_above_s0_and_at_most_maintain_eer() -> None:
    eer = 1815.34375
    s0 = {"kcal": (1515.34375, 1515.34375)}
    assert implicit_windows_pass(
        "fatigue",
        {"kcal": (1650.0, 1650.0)},
        eer=eer,
        weight_kg=62.0,
        s0_windows=s0,
    )
    assert implicit_windows_pass(
        "fatigue",
        {"kcal": (eer, eer)},
        eer=eer,
        weight_kg=62.0,
        s0_windows=s0,
    )
    assert not implicit_windows_pass(
        "fatigue", s0, eer=eer, weight_kg=62.0, s0_windows=s0
    )
    assert not implicit_windows_pass(
        "fatigue",
        {"kcal": (eer + 0.01, eer + 0.01)},
        eer=eer,
        weight_kg=62.0,
        s0_windows=s0,
    )


def test_muscle_band_needs_protein_above_rda_and_kcal_lo_at_eer() -> None:
    eer = 1815.34375
    assert implicit_windows_pass(
        "muscle",
        {"kcal": (eer, eer), "protein_g": (49.61, 99.2)},
        eer=eer,
        weight_kg=62.0,
        s0_windows={},
    )
    assert not implicit_windows_pass(
        "muscle",
        {"kcal": (eer, eer), "protein_g": (49.6, 49.6)},
        eer=eer,
        weight_kg=62.0,
        s0_windows={},
    )
    assert not implicit_windows_pass(
        "muscle",
        {"kcal": (eer - 0.01, eer), "protein_g": (99.2, 99.2)},
        eer=eer,
        weight_kg=62.0,
        s0_windows={},
    )


def test_dinner_slot_on_empty_ledger_is_thirty_to_forty_percent_of_eer() -> None:
    daily = derive_daily_windows(activity="light", phase="maintain", **_ADA)
    windows = plan_windows_for_meal(daily, {}, "dinner")
    assert windows is not None
    assert windows["kcal"] == (544.6, 726.14)
    assert windows["protein_g"][0] == 0.0
    assert windows["fiber_g"][0] == 0.0
    assert windows["sodium_mg"][1] == 2300.0


def test_last_meal_empty_ledger_dinner_is_an_empty_intersection() -> None:
    daily = derive_daily_windows(activity="light", phase="maintain", **_ADA)
    assert plan_windows_for_meal(daily, {}, "dinner", last_meal=True) is None


def test_breakfast_last_meal_does_not_take_protein_fiber_floor() -> None:
    daily = derive_daily_windows(activity="light", phase="maintain", **_ADA)
    windows = plan_windows_for_meal(
        daily, {"kcal": 1300.0}, "breakfast", last_meal=True
    )
    assert windows is not None
    assert windows["protein_g"][0] == 0.0
    assert windows["fiber_g"][0] == 0.0
