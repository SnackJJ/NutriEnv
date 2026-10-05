"""Profile transactions and meal-scale mass constraints through real Env actions."""

from dataclasses import replace

import pytest

from nutrienv.bench import Scorer, load_exam
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state


@pytest.mark.parametrize("patch", [
    {"weight_kg": 30, "height_cm": 100, "age_y": 100, "phase": "cut"},
    {"weight_kg": 10, "height_cm": 100, "age_y": 100, "phase": "cut"},
    {"weight_kg": 0},
    {"height_cm": -1},
    {"age_y": 0},
])
def test_invalid_profile_action_is_rejected_atomically(patch):
    task = load_exam()[0]
    env = NutriEnv()
    env.reset(task.s0)
    before = env.state().profile
    result = env.step({"op": "update_profile", "patch": {**patch, "allergies": ["soy"]}})
    assert not result["ok"]
    assert result["error"]["message"]
    assert env.state().profile == before
    assert env.step({"op": "get_profile"})["ok"]


def test_jointly_impossible_macro_minima_are_not_committed():
    env = NutriEnv()
    env.reset(demo_state())
    before = env.state().profile
    result = env.step({"op": "update_profile", "patch": {"windows": {
        "kcal": [1000, 1000], "protein_g": [120, 150],
        "carb_g": [100, 200], "fat_g": [20, 50],
    }}})
    assert not result["ok"]
    assert env.state().profile == before


def test_legal_but_unreasonable_cola_snack_cannot_pass():
    task = next(t for t in load_exam() if t.id == "adr29-conv-02")
    items = [{"food_id": "2710542", "grams": 2000},
             {"food_id": "2706311", "grams": 50}]
    # Scorer must enforce the same ruler even if an offline caller supplies a state directly.
    assert not Scorer().score(replace(task.s0, last_plan=items), task.oracle)["passed"]
    env = NutriEnv()
    env.reset(task.s0)
    result = env.step({"op": "submit_plan", "items": items})
    assert not result["ok"]
    assert env.state().last_plan == []


@pytest.mark.parametrize("split_rows", [False, True])
def test_mass_bound_cannot_be_evaded_by_splitting_items(split_rows):
    task = next(t for t in load_exam() if t.id == "adr29-conv-02")
    items = ([{"food_id": "2710542", "grams": 100}] * 6 if split_rows
             else [{"food_id": "2710542", "grams": 600}])
    env = NutriEnv()
    env.reset(task.s0)
    assert not env.step({"op": "submit_plan", "items": items})["ok"]


def test_public_scope_is_immutable_and_limit_is_inclusive():
    state = replace(demo_state(), plan_scope="snack")
    env = NutriEnv()
    opening = env.reset(state)
    assert opening["plan_limits"] == {"scope": "snack", "max_total_grams": 500}
    assert env.step({"op": "get_profile"})["observation"]["plan_limits"] == opening["plan_limits"]
    assert not env.step({"op": "update_profile", "patch": {"plan_scope": "day"}})["ok"]
    assert env.state().plan_scope == "snack"
    assert env.step({"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 500}]})["ok"]
    before = list(env.state().last_plan)
    assert not env.step({"op": "submit_plan", "items": [{"food_id": "white_rice", "grams": 500.01}]})["ok"]
    assert env.state().last_plan == before


def test_main_meal_envelope_keeps_a_high_water_plate():
    env = NutriEnv()
    env.reset(replace(demo_state(), plan_scope="meal"))
    items = [{"food_id": "broccoli", "grams": 1000},
             {"food_id": "white_rice", "grams": 200},
             {"food_id": "chicken_breast", "grams": 150}]
    assert env.step({"op": "submit_plan", "items": items})["ok"]


def test_zero_energy_target_is_not_a_successful_profile_update():
    env = NutriEnv()
    env.reset(demo_state())
    before = env.state().profile
    assert not env.step({"op": "update_profile", "patch": {"windows": {"kcal": [0, 0]}}})["ok"]
    assert env.state().profile == before


def test_energy_only_override_preserves_macros_so_a_low_target_is_rejected():
    """A windows-only override keeps the unmentioned macro windows. Below their energy
    floor the request is truly impossible, so it fails loudly instead of rescaling."""
    env = NutriEnv()
    env.reset(load_exam()[0].s0)
    before = env.state().profile
    floor = sum(
        before.windows[key][0] * factor
        for key, factor in (("protein_g", 4), ("carb_g", 4), ("fat_g", 9))
    )
    target = floor - 50.0
    assert target > 0
    result = env.step(
        {"op": "update_profile", "patch": {"windows": {"kcal": [target, target]}}}
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_profile"
    assert env.state().profile == before
