"""Ticket 10: generate_one Composite mill — log remainder, dual oracles."""

from __future__ import annotations

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.validator import fitting_plan, validate_draft
from nutrienv.env import NutriEnv
from nutrienv.world.daily_windows import plan_windows_for_meal
from nutrienv.world.types import ledger_totals


def _food(name, portions, aliases=(), allergen_tags=(), nutrients=None):
    return {
        "name": name,
        "portions": dict(portions),
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
        "nutrients": dict(
            nutrients
            or {
                "kcal": 100.0,
                "protein_g": 5.0,
                "carb_g": 10.0,
                "fat_g": 3.0,
                "fiber_g": 2.0,
                "sodium_mg": 40.0,
            }
        ),
    }


def _catalog() -> dict:
    return {
        "oats": _food("Oats, rolled", {"cup": 81.0}, ("oats", "oatmeal")),
        "milk_whole": _food(
            "Milk, whole", {"cup": 244.0, "qns": 244.0}, ("milk",), ("milk",)
        ),
        "banana": _food("Banana, raw", {"piece": 118.0, "qns": 118.0}, ("banana",)),
        "chicken_breast": _food(
            "Chicken, breast, cooked",
            {"cup": 140.0, "piece": 172.0, "qns": 105.0},
            ("chicken",),
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
            ("rice",),
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
            "Broccoli, cooked", {"cup": 156.0, "qns": 156.0}, ("broccoli",)
        ),
        "peanut_butter": _food(
            "Peanut butter, smooth",
            {"tbsp": 16.0},
            ("peanut butter",),
            ("peanut",),
        ),
        "shrimp": _food(
            "Shrimp, cooked",
            {"piece": 25.0, "qns": 100.0},
            ("shrimp",),
            ("shellfish",),
        ),
    }


def _rice_then_dinner(pool, *, persona, family, amount_path=None):
    foods = [food.food_id for food in pool.foods if food.food_id == "white_rice"]
    return {
        "query": "Please log a cup of rice for lunch. What's for dinner?",
        "foods": foods,
    }


def _run(**overrides):
    kwargs = dict(
        catalog=_catalog(),
        family="composite",
        seed=0,
        person=ROSTER[0],
        amount_path="named_measure",
        occasion="lunch",
        expander=_rice_then_dinner,
        pool_size=8,
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def test_log_then_recommend_plan_windows_are_remainder_after_the_log_tail() -> None:
    result = _run()
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.family == "log"
    assert task.oracle.sub_oracles is not None
    log_oracle, rec_oracle = task.oracle.sub_oracles
    assert log_oracle.ledger_tail
    assert rec_oracle.last_plan == []
    assert rec_oracle.plan_must_be_safe is True
    assert rec_oracle.plan_must_fit_windows is True

    after = ledger_totals(
        [*task.s0.ledger, *log_oracle.ledger_tail], task.s0.catalog
    )
    expected = plan_windows_for_meal(task.s0.profile.windows, after, "dinner")
    before = plan_windows_for_meal(
        task.s0.profile.windows,
        ledger_totals(task.s0.ledger, task.s0.catalog),
        "dinner",
    )
    assert expected is not None
    assert rec_oracle.plan_windows == expected
    assert rec_oracle.plan_windows != before
    assert tuple(rec_oracle.ledger) == (
        *task.s0.ledger,
        *log_oracle.ledger_tail,
    )

    env = NutriEnv()
    env.reset(task.s0)
    for row in log_oracle.ledger_tail:
        out = env.step(
            {
                "op": "log_meal",
                "food_id": row.food_id,
                "grams": row.grams,
                "eaten_at": row.eaten_at,
            }
        )
        assert out["ok"] is True
    plan = fitting_plan(
        task.s0.catalog, rec_oracle.plan_windows, task.s0.profile.allergies
    )
    assert plan is not None
    out = env.step({"op": "submit_plan", "items": plan})
    assert out["ok"] is True
    scored = Scorer().score(env.state(), task.oracle)
    assert scored["passed"] is True
    assert scored["tag"] == "pass"
    assert scored["sub_tags"] == ("pass", "pass")
    assert validate_draft(task) == []
