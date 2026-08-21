"""Ticket 07: generate_one Evaluate mill — fit, then code knives including swap."""

from __future__ import annotations

import json

from nutrienv.bench.pipeline.generate_one import (
    build_stage_a_prompt,
    build_unfit_rewrite_prompt,
    generate_one,
    make_unfit_rewriter,
)
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.realize import bind_evaluate_reasons
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv
from nutrienv.world.types import LedgerRow


def _food(name, portions, aliases=(), allergen_tags=(), nutrients=None):
    return {
        "name": name,
        "portions": portions,
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
        "nutrients": dict(nutrients or {}),
    }


# Demo-catalog nutrients so Ada dinner bind matches ticket 05 numbers.
_FIT_CATALOG = {
    "chicken_breast": _food(
        "Chicken breast, skinless, cooked",
        {"cup": 140.0, "piece": 172.0},
        ("chicken", "chicken breast"),
        nutrients={
            "kcal": 165.0,
            "protein_g": 31.0,
            "carb_g": 0.0,
            "fat_g": 3.6,
            "fiber_g": 0.0,
            "sodium_mg": 74.0,
        },
    ),
    "white_rice": _food(
        "Rice, white, cooked",
        {"cup": 158.0, "qns": 118.0},
        ("rice", "white rice"),
        nutrients={
            "kcal": 130.0,
            "protein_g": 2.7,
            "carb_g": 28.2,
            "fat_g": 0.3,
            "fiber_g": 0.4,
            "sodium_mg": 1.0,
        },
    ),
    "broccoli": _food(
        "Broccoli, raw",
        {"cup": 91.0},
        ("broccoli",),
        nutrients={
            "kcal": 34.0,
            "protein_g": 2.8,
            "carb_g": 6.6,
            "fat_g": 0.4,
            "fiber_g": 2.6,
            "sodium_mg": 33.0,
        },
    ),
    "olive_oil": _food(
        "Oil, olive, extra virgin",
        {"tbsp": 13.5, "tsp": 4.5},
        ("olive oil", "oil"),
        nutrients={
            "kcal": 884.0,
            "protein_g": 0.0,
            "carb_g": 0.0,
            "fat_g": 100.0,
            "fiber_g": 0.0,
            "sodium_mg": 2.0,
        },
    ),
}

_FIT_MEAL = [
    {"food_id": "chicken_breast", "grams": 130.0},
    {"food_id": "white_rice", "grams": 158.0},
    {"food_id": "broccoli", "grams": 91.0},
    {"food_id": "olive_oil", "grams": 13.5},
]
_FIT_QUERY = (
    "Evaluate this as dinner: 130 g of chicken, 158 g of rice, "
    "91 g of broccoli, and 13.5 g of olive oil."
)


def _fit_expander(_pool, *, persona, family, amount_path=None):
    return {"query": _FIT_QUERY, "foods": [item["food_id"] for item in _FIT_MEAL]}


def _run_eval(expander=_fit_expander, **overrides):
    kwargs = dict(
        catalog=_FIT_CATALOG,
        family="evaluate",
        seed=0,
        person=ROSTER[0],
        amount_path="explicit_grams",
        occasion="dinner",
        expander=expander,
        pool_size=4,
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def test_generate_one_evaluate_fit_accepts_bind_confirmed_plan() -> None:
    result = _run_eval()
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.family == "evaluate"
    assert task.oracle.last_verdict == "accept"
    assert task.oracle.last_plan == _FIT_MEAL
    assert task.oracle.evaluated_plan == _FIT_MEAL
    assert task.oracle.last_reasons == ()
    assert bind_evaluate_reasons(
        task.oracle.evaluated_plan,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    ) == ()
    assert validate_draft(task) == []

    env = NutriEnv()
    env.reset(task.s0)
    out = env.step({"op": "submit_plan", "items": _FIT_MEAL})
    assert out["ok"] is True
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


_PEANUT_BUTTER = _food(
    "Peanut butter, smooth",
    {"tbsp": 16.0, "cup": 258.0},
    ("peanut butter", "pb"),
    ("peanut",),
    nutrients={
        "kcal": 588.0,
        "protein_g": 25.1,
        "carb_g": 20.0,
        "fat_g": 50.4,
        "fiber_g": 6.0,
        "sodium_mg": 430.0,
    },
)


def _allergy_catalog() -> dict:
    return {**_FIT_CATALOG, "peanut_butter": _PEANUT_BUTTER}


def _rewrite_named(foods, *, intent, occasion, amount_path=None):
    parts = [f"{item['grams']:g} g of {item['food_id'].replace('_', ' ')}" for item in foods]
    return {
        "query": f"Evaluate this as {occasion}: {', '.join(parts)}.",
        "foods": [item["food_id"] for item in foods],
    }


def test_generate_one_evaluate_allergy_knife_matches_bind_reasons() -> None:
    result = _run_eval(
        catalog=_allergy_catalog(),
        pool_size=5,
        knife="allergy",
        rewriter=_rewrite_named,
    )
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    named = task.oracle.evaluated_plan
    assert named is not None
    assert any(item["food_id"] == "peanut_butter" for item in named)
    assert "peanut butter" in task.query.lower()
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_plan == []
    expected = bind_evaluate_reasons(
        named,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert task.oracle.last_reasons == expected
    assert "allergy" in task.oracle.last_reasons
    assert validate_draft(task) == []

    env = NutriEnv()
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
    assert Scorer().score(env.state(), task.oracle) == {"passed": True, "tag": "pass"}


# 130 g chicken + cup rice + cup broccoli + 2 tbsp oil ≈ 690 kcal, protein still in.
# Next catalog bump of rice (1.0 cup → 1.5 cup = 237 g) crosses dinner kcal hi.
_OVER_MEAL = [
    {"food_id": "chicken_breast", "grams": 130.0},
    {"food_id": "white_rice", "grams": 158.0},
    {"food_id": "broccoli", "grams": 91.0},
    {"food_id": "olive_oil", "grams": 27.0},
]
_OVER_QUERY = (
    "Evaluate this as dinner: 130 g of chicken, 158 g of rice, "
    "91 g of broccoli, and 27 g of olive oil."
)


def _over_expander(_pool, *, persona, family, amount_path=None):
    return {"query": _OVER_QUERY, "foods": [item["food_id"] for item in _OVER_MEAL]}


def test_generate_one_evaluate_over_slot_bump_fires_hi_reason() -> None:
    result = _run_eval(
        expander=_over_expander,
        knife="over_slot",
        rewriter=_rewrite_named,
    )
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    named = task.oracle.evaluated_plan
    assert named is not None
    assert named != _OVER_MEAL
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_plan == []
    expected = bind_evaluate_reasons(
        named,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert task.oracle.last_reasons == expected
    assert any(code.endswith("_hi") for code in task.oracle.last_reasons)
    before = {item["food_id"]: item["grams"] for item in _OVER_MEAL}
    after = {item["food_id"]: item["grams"] for item in named}
    changed = [food_id for food_id, grams in after.items() if before.get(food_id) != grams]
    assert len(changed) == 1
    assert any(name.replace("_", " ") in task.query.lower() for name in after)
    assert validate_draft(task) == []


def test_generate_one_evaluate_under_slot_step_or_drop_fires_lo_reason() -> None:
    result = _run_eval(knife="under_slot", rewriter=_rewrite_named)
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    named = task.oracle.evaluated_plan
    assert named is not None
    assert named != _FIT_MEAL
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_plan == []
    expected = bind_evaluate_reasons(
        named,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert task.oracle.last_reasons == expected
    assert any(code.endswith("_lo") for code in task.oracle.last_reasons)
    assert named, "under_slot must not empty the plate"
    before = {item["food_id"]: item["grams"] for item in _FIT_MEAL}
    after = {item["food_id"]: item["grams"] for item in named}
    dropped = [food_id for food_id in before if food_id not in after]
    stepped = [
        food_id
        for food_id, grams in after.items()
        if food_id in before and grams < before[food_id]
    ]
    assert len(dropped) + len(stepped) == 1
    assert validate_draft(task) == []


def test_generate_one_evaluate_swap_gold_has_no_kcal_code() -> None:
    result = _run_eval(
        expander=_over_expander,
        knife="swap",
        rewriter=_rewrite_named,
    )
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    named = task.oracle.evaluated_plan
    assert named is not None
    assert task.oracle.last_verdict == "reject"
    assert task.oracle.last_plan == []
    expected = bind_evaluate_reasons(
        named,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert task.oracle.last_reasons == expected
    assert "kcal_hi" not in task.oracle.last_reasons
    assert "kcal_lo" not in task.oracle.last_reasons
    assert "fat_g_hi" in task.oracle.last_reasons or "fiber_g_lo" in task.oracle.last_reasons
    assert validate_draft(task) == []


def test_generate_one_evaluate_fit_with_leftover_ledger_still_accepts() -> None:
    result = _run_eval(
        scene="leftover",
        prior_ledger=[LedgerRow("broccoli", 50.0, "today-lunch")],
    )
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.s0.ledger
    assert task.oracle.last_verdict == "accept"
    assert task.oracle.last_plan == _FIT_MEAL
    assert "leftover_over" not in task.oracle.bound_labels
    assert "leftover_under" not in task.oracle.bound_labels
    assert validate_draft(task) == []


def test_generate_one_evaluate_leftover_over_keeps_ordinary_plate() -> None:
    result = _run_eval(
        scene="leftover",
        prior_ledger=[LedgerRow("white_rice", 965.0, "today-lunch")],
        knife="over_slot",
        rewriter=_rewrite_named,
    )
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.oracle.last_verdict == "reject"
    assert "leftover_over" in task.oracle.bound_labels
    assert task.oracle.evaluated_plan == _FIT_MEAL
    assert "kcal_hi" in task.oracle.last_reasons or any(
        code.endswith("_hi") for code in task.oracle.last_reasons
    )
    expected = bind_evaluate_reasons(
        task.oracle.evaluated_plan,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert task.oracle.last_reasons == expected
    assert validate_draft(task) == []


def _rice_dinner_expander(_pool, *, persona, family, amount_path=None):
    return {
        "query": "Evaluate this as dinner: 430 g of rice.",
        "foods": ["white_rice"],
    }


_LEFTOVER_LUNCH = [LedgerRow("white_rice", 965.0, "today-lunch")]


def test_generate_one_evaluate_leftover_under_only_on_last_meal() -> None:
    earlier = _run_eval(
        expander=_rice_dinner_expander,
        scene="leftover",
        prior_ledger=_LEFTOVER_LUNCH,
        last_meal=False,
    )
    if earlier.accepted is not None:
        assert "leftover_under" not in earlier.accepted.oracle.bound_labels
        assert "draft_only" not in earlier.accepted.situations

    last = _run_eval(
        expander=_rice_dinner_expander,
        scene="leftover",
        prior_ledger=_LEFTOVER_LUNCH,
        last_meal=True,
    )
    assert last.rejected is None
    assert last.accepted is not None
    task = last.accepted
    assert task.oracle.last_verdict == "reject"
    assert "leftover_under" in task.oracle.bound_labels
    assert "draft_only" in task.situations
    assert task.oracle.last_reasons == bind_evaluate_reasons(
        task.oracle.evaluated_plan,
        task.oracle.plan_windows,
        task.s0.catalog,
        task.s0.profile.allergies,
    )
    assert validate_draft(task) == []


def test_generate_one_evaluate_drops_cartoon_portion_step() -> None:
    catalog = {
        "lettuce": _food(
            "Lettuce, raw",
            {"cup": 1800.0},
            ("lettuce",),
            nutrients={
                "kcal": 35.0,
                "protein_g": 1.0,
                "carb_g": 5.0,
                "fat_g": 1.0,
                "fiber_g": 1.0,
                "sodium_mg": 10.0,
            },
        ),
    }

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Evaluate this as dinner: 1800 g of lettuce.",
            "foods": ["lettuce"],
        }

    result = _run_eval(
        expander=expand,
        catalog=catalog,
        pool_size=1,
        knife="over_slot",
        rewriter=_rewrite_named,
    )
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"knife", "cartoon"}


def test_unfit_rewrite_prompt_names_foods_without_window_numbers() -> None:
    prompt = build_unfit_rewrite_prompt(
        (
            {"food_id": "white_rice", "grams": 237.0},
            {"food_id": "chicken_breast", "grams": 130.0},
        ),
        intent="bigger",
        occasion="dinner",
        catalog=_FIT_CATALOG,
    )
    lowered = prompt.lower()
    assert "rice" in lowered
    assert "chicken" in lowered
    assert "237" in prompt or "1.5" in prompt
    assert "bigger" in lowered
    assert "kcal" not in lowered
    assert "protein_g" not in lowered
    assert "544" not in prompt
    assert "726" not in prompt


def test_stage_a_prompt_asks_eatable_plate_not_wisdom() -> None:
    prompt = build_stage_a_prompt(_FIT_MEAL, _FIT_CATALOG)
    lowered = prompt.lower()
    assert "130" in prompt
    assert "chicken" in lowered
    assert "evaluate this as dinner" not in lowered
    assert "kcal" not in lowered
    assert "wise" in lowered or "healthy" in lowered
    assert "eat" in lowered


def test_unfit_rewriter_does_not_send_window_numbers() -> None:
    seen: list[str] = []

    def complete(_model_id, messages):
        seen.append(messages[0]["content"])
        return json.dumps(
            {
                "query": "Evaluate this as dinner: 237 g of rice.",
                "foods": ["white_rice"],
            }
        )

    rewriter = make_unfit_rewriter(complete=complete, catalog=_FIT_CATALOG)
    payload = rewriter(
        [{"food_id": "white_rice", "grams": 237.0}],
        intent="bigger",
        occasion="dinner",
    )
    assert seen
    assert seen[0] == build_unfit_rewrite_prompt(
        [{"food_id": "white_rice", "grams": 237.0}],
        intent="bigger",
        occasion="dinner",
        catalog=_FIT_CATALOG,
    )
    assert "kcal" not in seen[0].lower()
    assert payload["foods"] == ["white_rice"]
