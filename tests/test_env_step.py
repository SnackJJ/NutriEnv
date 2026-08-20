"""Env step physics: illegal ids, descriptive logs, partial profile writes."""

from __future__ import annotations

import copy
from pathlib import Path

from nutrienv.bench.split import load_split
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.types import LedgerRow

V04 = Path("data/splits/v0.4-gold.json")


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


def test_foods_are_found_by_search_not_a_full_listing() -> None:
    env = NutriEnv()
    s0 = demo_state()
    s0.ledger = []
    opening = env.reset(s0)

    assert opening["catalog_size"] == 15
    assert "catalog_ids" not in opening
    assert env.step({"op": "search_foods", "q": "*"})["observation"]["results"] == []
    shrimp = env.step({"op": "search_foods", "q": "prawn"})["observation"]["results"]
    assert shrimp[0]["food_id"] == "shrimp"
    assert env.step({"op": "get_food", "food_id": "shrimp"})["ok"]


def test_wildcard_is_the_only_match_all_query() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    def hits(needle: str) -> int:
        return len(env.step({"op": "search_foods", "q": needle})["observation"]["results"])

    assert hits("*") == 0
    assert hits("oats") == 1
    # A stray character is still a miss, not an accidental catalog dump.
    assert hits("a") == 0
    assert hits("**") == 0


def test_log_meal_rejects_item_above_2000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step({"op": "log_meal", "food_id": "oats", "grams": 2001})

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_submit_plan_rejects_item_above_2000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "oats", "grams": 2001}]}
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_submit_plan_rejects_total_above_4000g() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    before = copy.deepcopy(env.state())

    out = env.step(
        {
            "op": "submit_plan",
            "items": [
                {"food_id": "oats", "grams": 2000},
                {"food_id": "egg", "grams": 2000},
                {"food_id": "banana", "grams": 2000},
            ],
        }
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan
    assert after.catalog == before.catalog


def test_quantity_bounds_are_inclusive() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    logged = env.step({"op": "log_meal", "food_id": "oats", "grams": 2000})
    assert logged["ok"] is True
    assert env.state().ledger[-1].grams == 2000.0

    single = env.step(
        {"op": "submit_plan", "items": [{"food_id": "egg", "grams": 2000}]}
    )
    assert single["ok"] is True
    assert env.state().last_plan == [{"food_id": "egg", "grams": 2000.0}]

    total = env.step(
        {
            "op": "submit_plan",
            "items": [
                {"food_id": "oats", "grams": 2000},
                {"food_id": "egg", "grams": 2000},
            ],
        }
    )
    assert total["ok"] is True
    assert env.state().last_plan == [
        {"food_id": "oats", "grams": 2000.0},
        {"food_id": "egg", "grams": 2000.0},
    ]


def test_zero_kcal_coffee_exploit_is_rejected() -> None:
    task = next(item for item in load_split(V04) if item.id == "v0-rec-conflict-001")
    coffee = task.s0.catalog["2710376"]
    assert coffee["nutrients"]["kcal"] == 0.0
    assert coffee["nutrients"]["protein_g"] > 0

    env = NutriEnv()
    env.reset(task.s0)
    before = copy.deepcopy(env.state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "2710376", "grams": 90909}]}
    )

    assert out["ok"] is False
    assert out["error"]["code"] == "implausible_quantity"
    after = env.state()
    assert after.ledger == before.ledger
    assert after.profile == before.profile
    assert after.last_plan == before.last_plan


def test_nonempty_submit_plan_without_verdict_sets_accept() -> None:
    env = NutriEnv()
    env.reset(demo_state())

    out = env.step(
        {"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]}
    )

    assert out["ok"] is True
    state = env.state()
    assert state.last_verdict == "accept"
    assert state.last_plan == [{"food_id": "egg", "grams": 100.0}]
    assert state.last_reasons == ()


def test_empty_submit_plan_without_verdict_is_silence_not_leftover_accept() -> None:
    env = NutriEnv()
    env.reset(demo_state())
    env.step({"op": "submit_plan", "items": [{"food_id": "egg", "grams": 100}]})
    assert env.state().last_verdict == "accept"

    out = env.step({"op": "submit_plan", "items": []})

    assert out["ok"] is True
    state = env.state()
    assert state.last_verdict is None
    assert state.last_plan == []
    assert state.last_reasons == ()

