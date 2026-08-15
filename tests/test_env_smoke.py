"""Smoke test only. env-verify owns the real suite."""

from dataclasses import replace

from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow


def test_reads_and_writes_apply_now():
    env = NutriEnv()
    obs = env.reset(demo_state())
    assert obs["catalog_size"] == 15

    found = env.step({"op": "search_foods", "q": "prawn"})["observation"]["results"]
    assert [row["food_id"] for row in found] == ["shrimp"]

    spoken = env.step({"op": "search_foods", "q": "chicken breast"})["observation"]["results"]
    assert "chicken_breast" in [row["food_id"] for row in spoken]

    assert env.step({"op": "log_meal", "food_id": "oats", "grams": 60})["ok"]
    assert env.state().ledger == [LedgerRow("oats", 60.0, "now")]
    logged = env.step({"op": "get_ledger"})["observation"]
    oats = demo_state().catalog["oats"]["nutrients"]
    assert logged["ledger"][0]["nutrients"]["kcal"] == oats["kcal"] * 60.0 / 100.0
    assert logged["totals"]["kcal"] == logged["ledger"][0]["nutrients"]["kcal"]

    assert env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})["ok"]
    assert env.state().last_plan == [{"food_id": "egg", "grams": 100.0}]

    shrimp = env.step(
        {"op": "update_profile", "patch": {"allergies": ["peanut", "shrimp"]}}
    )
    assert shrimp["ok"]
    assert env.state().profile.allergies == ("peanut", "shellfish")

    # Only the mentioned window moves; protein_g and version stay at S0.
    patch = {"windows": {"kcal": [2000, 2400]}}
    assert env.step({"op": "update_profile", "patch": patch})["ok"]
    profile = env.state().profile
    assert profile.windows == {"kcal": (2000.0, 2400.0), "protein_g": (90.0, 140.0)}
    assert profile.version == 1

    assert env.step({"op": "update_plan", "patch": {"cuisine": "italian"}})["ok"]
    assert env.state().profile.plan_preset == {"meals_per_day": 3, "cuisine": "italian"}


def test_illegal_actions_leave_the_world_unchanged():
    env = NutriEnv()
    env.reset(demo_state())
    before = replace(env.state().profile)

    for action in (
        {"op": "get_food", "food_id": "unicorn_steak"},
        {"op": "log_meal", "food_id": "oats", "grams": -1},
        {
            "op": "submit_plan",
            "items": [{"food_id": "egg", "grams": 100}, {"food_id": "nope", "grams": 50}],
        },
        {"op": "update_profile", "patch": {"user_id": "someone_else"}},
        {"op": "update_profile", "patch": {"windows": {"kcal": [2400, 2000]}}},
        {"op": "teleport"},
        {"op": "get_profile", "surprise": 1},
    ):
        result = env.step(action)
        assert result["ok"] is False, action
        assert result["error"]["code"]

    assert env.state().profile == before
    assert env.state().ledger == []
    assert env.state().last_plan == []


def test_reset_copies_s0():
    s0 = demo_state()
    env = NutriEnv()
    env.reset(s0)
    env.step({"op": "log_meal", "food_id": "banana", "grams": 120})
    assert s0.ledger == []


def test_allergen_meal_is_a_valid_fact():
    env = NutriEnv()
    env.reset(demo_state())  # allergic to peanut
    assert env.step({"op": "log_meal", "food_id": "peanut_butter", "grams": 30})["ok"]
