"""Ticket 08: generate_one Recommend mill — template shells, timeline leftover."""

from __future__ import annotations

import pytest

from nutrienv.bench.pipeline.generate_one import (
    drop_orphan_leftovers,
    generate_one,
    leftover_parent_ids,
)
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.scorer import Scorer
from nutrienv.bench.validator import fitting_plan
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
    parent = _parent_log(
        4,
        "lunch",
        "Please log a cup of rice for lunch.",
        {"white_rice"},
    )
    result = _run(
        occasion=occasion,
        scene="leftover",
        prior_logs=[parent],
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
    plan = fitting_plan(task.s0.catalog, oracle.plan_windows, task.s0.profile.allergies)
    assert plan is not None
    out = env.step({"op": "submit_plan", "items": plan})
    assert out["ok"] is True
    assert Scorer().score(env.state(), oracle) == {"passed": True, "tag": "pass"}
    assert validate_draft(task) == []


def _parent_log(seed, occasion, query, foods, person=ROSTER[0]):
    result = generate_one(
        catalog=_catalog(),
        family="log",
        seed=seed,
        person=person,
        amount_path="named_measure",
        expander=lambda pool, **_: {
            "query": query,
            "foods": [
                food.food_id for food in pool.foods if food.food_id in foods
            ],
        },
        occasion=occasion,
    )
    assert result.accepted is not None
    return result.accepted


def test_leftover_ledger_copies_prior_log_tails_without_shadow_meals() -> None:
    breakfast_log = _parent_log(
        1,
        "breakfast",
        "Please log a cup of oats and a cup of milk for breakfast.",
        {"oats", "milk_whole"},
    )
    lunch_log = _parent_log(
        2,
        "lunch",
        "Please log a cup of rice and a cup of chicken for lunch.",
        {"white_rice", "chicken_breast"},
    )

    rec = _run(scene="leftover", prior_logs=[breakfast_log, lunch_log])
    assert rec.rejected is None
    assert rec.accepted is not None
    expected = tuple(breakfast_log.oracle.ledger_tail) + tuple(
        lunch_log.oracle.ledger_tail
    )
    assert tuple(rec.accepted.s0.ledger) == expected
    assert leftover_parent_ids(rec.accepted) == (breakfast_log.id, lunch_log.id)


def test_foreign_parent_log_is_rejected() -> None:
    ada_log = _parent_log(
        1,
        "lunch",
        "Please log a cup of rice for lunch.",
        {"white_rice"},
    )
    foreign = _run(
        scene="leftover",
        prior_logs=[ada_log],
        person=ROSTER[1],
        shell="rec-occasion",
    )
    assert foreign.accepted is None
    assert foreign.rejected is not None
    assert foreign.rejected.reason == "foreign_log"

    not_a_log_source = _run(occasion="dinner")
    assert not_a_log_source.accepted is not None
    not_a_log = _run(
        scene="leftover", prior_logs=[not_a_log_source.accepted]
    )
    assert not_a_log.accepted is None
    assert not_a_log.rejected is not None
    assert not_a_log.rejected.reason == "foreign_log"


def test_dropping_parent_log_drops_dependent_leftover_draft() -> None:
    survivor = _parent_log(
        1,
        "breakfast",
        "Please log a cup of oats for breakfast.",
        {"oats"},
    )
    dropped_parent = _parent_log(
        2,
        "lunch",
        "Please log a cup of rice and a cup of chicken for lunch.",
        {"white_rice", "chicken_breast"},
    )

    draft = _run(
        scene="leftover", prior_logs=[survivor, dropped_parent], seed=7
    )
    assert draft.accepted is not None

    kept = drop_orphan_leftovers(
        [draft.accepted], live_log_ids={survivor.id, dropped_parent.id}
    )
    assert [task.id for task in kept] == [draft.accepted.id]

    after_drop = drop_orphan_leftovers(
        [draft.accepted], live_log_ids={survivor.id}
    )
    assert after_drop == ()

    plain_rec = _run(occasion="dinner")
    assert plain_rec.accepted is not None
    untouched = drop_orphan_leftovers(
        [plain_rec.accepted], live_log_ids=frozenset()
    )
    assert [task.id for task in untouched] == [plain_rec.accepted.id]

    all_parents_dropped = _run(scene="leftover", prior_logs=[])
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


def test_snack_occasion_selects_the_rec_snack_shell_and_passable_windows() -> None:
    result = _run(occasion="snack")
    assert result.rejected is None
    task = result.accepted
    assert task.query == "I need a snack."
    assert task.oracle.plan_windows is not None
    kcal = task.oracle.plan_windows["kcal"]
    assert kcal[0] == 0.0
    assert kcal[1] > 0.0
    plan = fitting_plan(task.s0.catalog, task.oracle.plan_windows, ())
    assert plan is not None


def test_occasion_pinned_shell_conflicting_with_occasion_is_rejected() -> None:
    result = _run(shell="rec-breakfast", occasion="dinner")
    assert result.accepted is None
    assert result.rejected is not None


def test_generic_shells_inherit_the_sampled_occasion() -> None:
    eat = _run(shell="rec-occasion-eat", occasion="lunch", scene="empty")
    assert eat.rejected is None
    assert eat.accepted.query == "What should I eat?"
