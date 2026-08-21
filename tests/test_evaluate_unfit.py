"""Ticket 05: constructed Evaluate-fit/unfit Tasks. Seams: realize_evaluate, Env step, Scorer, validate_draft."""

import json

import pytest

from nutrienv.bench.pipeline.freezer import task_to_item
from nutrienv.bench.realize import (
    Oracle,
    Task,
    compose_oracles,
    leftover_bound_labels,
    realize_evaluate,
)
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.split import load_split
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_fixture import demo_state
from nutrienv.world.daily_windows import derive_daily_windows
from nutrienv.world.types import LedgerRow, Profile

# Ada: female 34 y, 165 cm, 62 kg, light. Mifflin×PAL EER = 1815.34375.
# Dinner energy share 30–40% → kcal (544.6, 726.14) with empty ledger, not last meal.
_DINNER_KCAL = (544.6, 726.14)

# Chicken 130 g + rice 158 g + broccoli 91 g + olive oil 13.5 g.
# Totals: kcal 570.18, protein 47.114 — inside dinner slot, not a meal±margin window.
_FIT_MEAL = [
    {"food_id": "chicken_breast", "grams": 130.0},
    {"food_id": "white_rice", "grams": 158.0},
    {"food_id": "broccoli", "grams": 91.0},
    {"food_id": "olive_oil", "grams": 13.5},
]
_FIT_QUERY = (
    "Evaluate this as dinner: 130 g chicken, a cup of rice, "
    "a cup of broccoli, and a tablespoon of olive oil."
)


def _ada_state():
    state = demo_state()
    windows = derive_daily_windows(
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    state.profile = Profile(
        user_id="roster-ada",
        allergies=("peanut",),
        windows=windows,
        sex="female",
        age_y=34,
        height_cm=165.0,
        weight_kg=62.0,
        activity="light",
        phase="maintain",
    )
    return state


def test_fit_evaluate_uses_slot_remainder_windows_not_meal_margin() -> None:
    task = realize_evaluate(
        task_id="ev-fit-dinner",
        query=_FIT_QUERY,
        items=_FIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    assert task.family == "evaluate"
    assert task.oracle.last_verdict == "accept"
    assert task.oracle.last_plan == _FIT_MEAL
    assert task.oracle.evaluated_plan == _FIT_MEAL
    assert task.oracle.last_reasons == ()
    assert task.oracle.plan_must_fit_windows is False
    windows = task.oracle.plan_windows
    assert windows is not None
    assert set(windows) == {
        "kcal",
        "protein_g",
        "carb_g",
        "fat_g",
        "fiber_g",
        "sodium_mg",
    }
    assert windows["kcal"] == _DINNER_KCAL
    # Old evaluate_windows would be meal kcal 570 ± 150 → roughly (420, 730), not the slot.
    assert windows["kcal"] != (420.0, 730.0)

    env = NutriEnv()
    env.reset(task.s0)
    out = env.step({"op": "submit_plan", "items": _FIT_MEAL})
    assert out["ok"] is True
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


_UNFIT_MEAL = [{"food_id": "peanut_butter", "grams": 25.0}]
_UNFIT_QUERY = "Is 25 g of peanut butter okay for dinner?"


def test_unfit_evaluate_rejects_empty_plan_and_env_does_not_adopt_the_meal() -> None:
    task = realize_evaluate(
        task_id="ev-unfit-pb",
        query=_UNFIT_QUERY,
        items=_UNFIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_plan == []
    assert task.oracle.evaluated_plan == _UNFIT_MEAL
    assert task.oracle.last_reasons == ("allergy", "kcal_lo")
    assert task.oracle.plan_must_fit_windows is False
    assert task.oracle.allow_empty_plan is False

    env = NutriEnv()
    env.reset(task.s0)
    adopted = env.step({"op": "submit_plan", "items": _UNFIT_MEAL})
    assert adopted["ok"] is True
    assert env.state().last_plan == _UNFIT_MEAL
    assert Scorer().score(env.state(), task.oracle)["passed"] is False

    env.reset(task.s0)
    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": list(task.oracle.last_reasons),
        }
    )
    assert out["ok"] is True
    assert env.state().last_plan == []
    assert env.state().last_verdict == "reject"
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


def test_swap_fixture_fires_fat_hi_without_kcal_code() -> None:
    # 80 g olive oil: 707.2 kcal (inside dinner slot) and 80 g fat (over Ada fat hi 70.8).
    meal = [{"food_id": "olive_oil", "grams": 80.0}]
    task = realize_evaluate(
        task_id="ev-swap-oil",
        query="Evaluate this as dinner: 80 g of olive oil.",
        items=meal,
        s0=_ada_state(),
        occasion="dinner",
    )
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_reasons == ("fat_g_hi",)
    assert "kcal_hi" not in task.oracle.last_reasons
    assert "kcal_lo" not in task.oracle.last_reasons
    windows = task.oracle.plan_windows
    assert windows is not None
    assert windows["kcal"][0] <= 707.2 <= windows["kcal"][1]
    env = NutriEnv()
    env.reset(task.s0)
    out = env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": ["fat_g_hi"],
        }
    )
    assert out["ok"] is True
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


def test_leftover_over_label_matches_remainder_hi_leg() -> None:
    s0 = _ada_state()
    s0.ledger = [LedgerRow("white_rice", 900.0, "today-lunch")]
    meal = [{"food_id": "olive_oil", "grams": 76.0}]  # 671.84 kcal
    task = realize_evaluate(
        task_id="ev-leftover-over",
        query="Evaluate this as dinner: 76 g of olive oil.",
        items=meal,
        s0=s0,
        occasion="dinner",
    )
    assert "leftover_over" in task.oracle.bound_labels
    assert "kcal_hi" in task.oracle.last_reasons
    env = NutriEnv()
    env.reset(task.s0)
    env.step(
        {
            "op": "submit_plan",
            "items": [],
            "verdict": "reject",
            "reasons": list(task.oracle.last_reasons),
        }
    )
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


def test_leftover_under_label_matches_remainder_lo_leg() -> None:
    s0 = _ada_state()
    s0.ledger = [LedgerRow("white_rice", 900.0, "today-lunch")]
    meal = [{"food_id": "white_rice", "grams": 430.0}]  # 559 kcal
    task = realize_evaluate(
        task_id="ev-leftover-under",
        query="Evaluate this as dinner: 430 g of rice.",
        items=meal,
        s0=s0,
        occasion="dinner",
        last_meal=True,
    )
    assert "leftover_under" in task.oracle.bound_labels
    assert "kcal_lo" in task.oracle.last_reasons


def test_slot_outside_is_not_leftover() -> None:
    labels = leftover_bound_labels(
        [{"food_id": "white_rice", "grams": 500.0}],
        {"kcal": _DINNER_KCAL},
        {"kcal": (600.48, 600.48)},
        _ada_state().catalog,
        last_meal=True,
    )
    # 650 kcal is above slot hi 726.14? 500 g rice = 650, slot hi 726.14, rem 600.48
    # 650 is inside slot and above rem hi → leftover_over, not under.
    assert "leftover_under" not in labels


def test_validator_names_evaluated_foods_and_empty_plan_only_if_reject() -> None:
    fit = realize_evaluate(
        task_id="ev-fit-dinner",
        query=_FIT_QUERY,
        items=_FIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    assert validate_draft(fit) == []

    unfit = realize_evaluate(
        task_id="ev-unfit-pb",
        query=_UNFIT_QUERY,
        items=_UNFIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    assert validate_draft(unfit) == []

    silent_query = realize_evaluate(
        task_id="ev-unfit-unnamed",
        query="Is this okay for dinner?",
        items=_UNFIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    issues = validate_draft(silent_query)
    assert any("not mentioned" in item for item in issues)

    accept_empty = Task(
        "bad-empty-accept",
        "evaluate",
        _FIT_QUERY,
        fit.s0,
        Oracle(
            profile=fit.s0.profile,
            last_plan=[],
            last_verdict="accept",
            evaluated_plan=_FIT_MEAL,
            plan_windows=fit.oracle.plan_windows,
            ledger=tuple(fit.s0.ledger),
        ),
    )
    assert any("empty" in item for item in validate_draft(accept_empty))


def test_empty_intersection_is_not_admitted() -> None:
    with pytest.raises(ValueError, match="empty plan_windows intersection"):
        realize_evaluate(
            task_id="ev-empty",
            query=_FIT_QUERY,
            items=_FIT_MEAL,
            s0=_ada_state(),
            occasion="dinner",
            last_meal=True,
        )


def test_validator_rejects_evaluate_unfit_paired_with_recommend_substitute() -> None:
    s0 = _ada_state()
    unfit = realize_evaluate(
        task_id="ev-unfit-pb",
        query=_UNFIT_QUERY,
        items=_UNFIT_MEAL,
        s0=s0,
        occasion="dinner",
    )
    recommend = Oracle(
        profile=s0.profile,
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        ledger=tuple(s0.ledger),
    )
    task = Task(
        "comp-unfit-sub",
        "evaluate",
        "I was going to eat peanut butter; what instead?",
        s0,
        compose_oracles(unfit.oracle, recommend),
    )
    issues = validate_draft(task)
    assert any("unfit" in item and "substitute" in item for item in issues)


def test_evaluated_plan_survives_freeze_load(tmp_path) -> None:
    task = realize_evaluate(
        task_id="ev-unfit-pb",
        query=_UNFIT_QUERY,
        items=_UNFIT_MEAL,
        s0=_ada_state(),
        occasion="dinner",
    )
    dest = tmp_path / "split.json"
    dest.write_text(json.dumps({"items": [task_to_item(task)]}), encoding="utf-8")
    loaded = load_split(dest, catalog=task.s0.catalog)[0]
    assert loaded.oracle.evaluated_plan == _UNFIT_MEAL
    assert loaded.oracle.last_plan == []
    assert loaded.oracle.last_verdict == "reject"
