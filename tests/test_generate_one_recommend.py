"""Ticket 08: generate_one Recommend mill — template shells, timeline leftover."""

from __future__ import annotations

import pytest

from nutrienv.bench.pipeline.generate_one import generate_one
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.validator import validate_draft
from nutrienv.env import NutriEnv
from nutrienv.world.types import LedgerRow


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
        ),
        "white_rice": _food(
            "Rice, white, cooked", {"cup": 158.0, "qns": 118.0}, ("rice",)
        ),
        "broccoli": _food("Broccoli, cooked", {"cup": 156.0, "qns": 156.0}, ("broccoli",)),
        "peanut_butter": _food(
            "Peanut butter, smooth",
            {"tbsp": 16.0},
            ("peanut butter",),
            ("peanut",),
        ),
        "shrimp": _food(
            "Shrimp, cooked", {"piece": 25.0, "qns": 100.0}, ("shrimp",), ("shellfish",)
        ),
    }


def _run(**overrides):
    kwargs = dict(
        catalog=_catalog(),
        family="recommend",
        seed=0,
        person=ROSTER[0],
        occasion="dinner",
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def test_recommend_dinner_query_is_the_agreed_shell_verbatim() -> None:
    result = _run()
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.query == "What's for dinner?"


def test_recommend_breakfast_and_lunch_shells_are_verbatim() -> None:
    breakfast = _run(occasion="breakfast")
    assert breakfast.rejected is None
    assert breakfast.accepted.query == "What's for breakfast?"

    lunch = _run(occasion="lunch")
    assert lunch.rejected is None
    assert lunch.accepted.query == "What should I eat for lunch?"


def test_recommend_occasion_shell_fills_the_slot() -> None:
    result = _run(shell="rec-occasion", occasion="lunch")
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.query == "What's for lunch?"


@pytest.mark.parametrize("occasion", ["breakfast", "lunch", "dinner"])
def test_recommend_query_never_recaps_leftover_or_allergy(occasion) -> None:
    prior = [LedgerRow("white_rice", 158.0, "today-lunch")]
    result = _run(
        occasion=occasion,
        scene="leftover",
        prior_ledger=prior,
        person=ROSTER[0],
    )
    assert result.rejected is None
    lowered = result.accepted.query.lower()
    assert "already" not in lowered
    assert "ate" not in lowered
    assert "left" not in lowered
    assert "allergic" not in lowered
    assert "peanut" not in lowered


def test_empty_ledger_breakfast_recommend_is_generable_and_passable() -> None:
    result = _run(occasion="breakfast")
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.family == "recommend"
    assert task.s0.ledger == []
    oracle = task.oracle
    assert oracle.last_plan == []
    assert oracle.plan_must_be_safe is True
    assert oracle.plan_must_fit_windows is True
    assert oracle.plan_windows is not None
    assert oracle.profile.allergies == ("peanut",)

    env = NutriEnv()
    env.reset(task.s0)
    from nutrienv.bench.validator import fitting_plan

    plan = fitting_plan(task.s0.catalog, oracle.plan_windows, task.s0.profile.allergies)
    assert plan is not None
    out = env.step({"op": "submit_plan", "items": plan})
    assert out["ok"] is True
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}
    assert validate_draft(task) == []


def test_leftover_ledger_copies_prior_log_tails_without_shadow_meals() -> None:
    breakfast_log = generate_one(
        catalog=_catalog(),
        family="log",
        seed=1,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=lambda pool, **_: {
            "query": "Please log a cup of oats and a cup of milk for breakfast.",
            "foods": [
                food.food_id
                for food in pool.foods
                if food.food_id in {"oats", "milk_whole"}
            ],
        },
        occasion="breakfast",
    )
    assert breakfast_log.accepted is not None
    lunch_log = generate_one(
        catalog=_catalog(),
        family="log",
        seed=2,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=lambda pool, **_: {
            "query": "Please log a cup of rice and a cup of chicken for lunch.",
            "foods": [
                food.food_id
                for food in pool.foods
                if food.food_id in {"white_rice", "chicken_breast"}
            ],
        },
        occasion="lunch",
    )
    assert lunch_log.accepted is not None

    tails = [
        breakfast_log.accepted.oracle.ledger_tail,
        lunch_log.accepted.oracle.ledger_tail,
    ]
    rec = _run(scene="leftover", prior_ledger=[row for tail in tails for row in tail])
    assert rec.rejected is None
    assert rec.accepted is not None
    assert tuple(rec.accepted.s0.ledger) == tuple(
        row for tail in tails for row in tail
    )


def test_dropping_parent_log_drops_dependent_leftover_draft() -> None:
    dropped = generate_one(
        catalog=_catalog(),
        family="log",
        seed=3,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=lambda pool, **_: {
            "query": "Please log a slice of milk for lunch.",
            "foods": ["milk_whole"],
        },
        occasion="lunch",
    )
    assert dropped.accepted is None
    assert dropped.rejected is not None

    accepted = generate_one(
        catalog=_catalog(),
        family="log",
        seed=1,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=lambda pool, **_: {
            "query": "Please log a cup of oats for breakfast.",
            "foods": ["oats"],
        },
        occasion="breakfast",
    )
    assert accepted.accepted is not None

    only_survivors = _run(
        scene="leftover",
        prior_ledger=list(accepted.accepted.oracle.ledger_tail),
    )
    assert only_survivors.accepted is not None
    assert tuple(only_survivors.accepted.s0.ledger) == tuple(
        accepted.accepted.oracle.ledger_tail
    )

    all_parents_dropped = _run(scene="leftover", prior_ledger=None)
    assert all_parents_dropped.accepted is None
    assert all_parents_dropped.rejected is not None
    assert all_parents_dropped.rejected.reason == "no_ledger"


def test_named_dish_trap_does_not_say_allergic() -> None:
    result = _run(shell="rec-named-dish", slots={"dish": "peanut_butter"})
    assert result.rejected is None
    assert result.accepted is not None
    task = result.accepted
    assert task.query == (
        "Thinking of peanut butter tonight — what should I eat?"
    )
    lowered = task.query.lower()
    assert "allergic" not in lowered
    assert "allergy" not in lowered
    assert task.s0.profile.allergies == ("peanut",)
    assert validate_draft(task) == []


def test_named_dish_requires_an_allergic_person() -> None:
    clean = ROSTER[3]
    result = _run(person=clean, shell="rec-named-dish", slots={"dish": "shrimp"})
    assert result.accepted is None
    assert result.rejected is not None
