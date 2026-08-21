"""Ticket 07: generate_one Evaluate mill — fit, then code knives including swap."""

from __future__ import annotations

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.realize import bind_evaluate_reasons
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv


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
