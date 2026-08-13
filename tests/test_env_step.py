"""Env step physics: illegal ids, descriptive logs, partial profile writes."""

from __future__ import annotations

import copy

from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow


def test_illegal_food_id_does_not_mutate() -> None:
    env = NutriEnv()
    s0 = demo_state()
    env.reset(s0)
    before = copy.deepcopy(env.state())

    out = env.step({"op": "log_meal", "food_id": "not_a_minted_food", "grams": 50})

    assert out["ok"] is False
    assert out["error"]["code"] == "unknown_food"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog

    # Episode continues after an Illegal Action.
    cont = env.step({"op": "get_profile"})
    assert cont["ok"] is True
    assert env.state().ledger == before.ledger


def test_log_meal_of_allergen_food_is_allowed() -> None:
    env = NutriEnv()
    s0 = demo_state()
    assert "peanut" in s0.profile.allergies
    assert "peanut" in s0.catalog["peanut_butter"]["allergen_tags"]
    env.reset(s0)

    out = env.step(
        {
            "op": "log_meal",
            "food_id": "peanut_butter",
            "grams": 32,
            "eaten_at": "lunch",
        }
    )

    assert out["ok"] is True
    row = env.state().ledger[-1]
    assert row == LedgerRow(food_id="peanut_butter", grams=32.0, eaten_at="lunch")
    assert env.state().profile.allergies == s0.profile.allergies


def test_update_profile_kcal_only_leaves_allergies_unchanged() -> None:
    env = NutriEnv()
    s0 = demo_state()
    env.reset(s0)

    out = env.step(
        {"op": "update_profile", "patch": {"windows": {"kcal": [2100.0, 2500.0]}}}
    )

    assert out["ok"] is True
    profile = env.state().profile
    assert profile.allergies == s0.profile.allergies
    assert profile.medications == s0.profile.medications
    assert profile.windows["kcal"] == (2100.0, 2500.0)
    assert profile.windows["protein_g"] == s0.profile.windows["protein_g"]
    assert profile.plan_preset == s0.profile.plan_preset
    assert profile.version == s0.profile.version
