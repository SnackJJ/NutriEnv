"""Ticket 06: generate_one Log mill — roster world, {query, foods}, speech bind."""

from __future__ import annotations

import inspect

from nutrienv.bench.pipeline.generate_one import (
    build_log_system_prompt,
    generate_one,
)
from nutrienv.bench.pipeline.roster import ROSTER
from nutrienv.bench.realize import GOLD_WINDOWS
from nutrienv.world.daily_windows import derive_profile_windows


def _food(name, portions, aliases=(), allergen_tags=()):
    return {
        "name": name,
        "portions": portions,
        "aliases": list(aliases),
        "allergen_tags": list(allergen_tags),
    }


def _catalog() -> dict:
    return {
        "milk_whole": _food(
            "Milk, whole", {"cup": 244.0, "fl_oz": 30.5}, ("milk", "whole milk"), ("milk",)
        ),
        "apple": _food("Apple, raw", {"piece": 182.0, "cup": 125.0}, ("apple", "apples")),
        "banana": _food("Banana, raw", {"piece": 118.0, "cup": 150.0}, ("banana",)),
        "egg": _food("Egg, whole", {"piece": 50.0}, ("egg", "eggs"), ("egg",)),
        "white_rice": _food(
            "Rice, white, cooked",
            {"cup": 158.0, "qns": 118.0},
            ("rice", "white rice"),
        ),
        "orange": _food("Orange, raw", {"piece": 131.0}, ("orange",)),
        "oats": _food("Oats, rolled", {"cup": 81.0}, ("oats", "oatmeal")),
        "broccoli": _food("Broccoli, cooked", {"cup": 156.0}, ("broccoli",)),
        "chicken_breast": _food(
            "Chicken, NS as to part, cooked",
            {"cup": 140.0, "qns": 105.0},
            ("chicken",),
        ),
    }


def _cup_expander(pool, *, persona, family):
    for food in pool.foods:
        if any(alt.key == "cup" and alt.quantity == 1.0 for alt in food.alternatives):
            name = food.aliases[0] if food.aliases else food.name.split(",")[0]
            return {
                "query": f"Please log a cup of {name} for lunch.",
                "foods": [food.food_id],
            }
    return {"query": "", "foods": []}


def test_generate_one_roster_s0_uses_world_derived_windows() -> None:
    person = ROSTER[0]
    result = generate_one(
        catalog=_catalog(),
        family="log",
        seed=0,
        person=person,
        amount_path="named_measure",
        expander=_cup_expander,
    )
    assert result.rejected is None
    assert result.accepted is not None
    profile = result.accepted.s0.profile
    derived = derive_profile_windows(profile)
    assert derived is not None
    assert profile.windows == derived
    assert profile.windows != GOLD_WINDOWS
    assert profile.sex == person.sex
    assert profile.age_y == person.age_y
    assert profile.height_cm == person.height_cm
    assert profile.weight_kg == person.weight_kg
    assert profile.activity == person.activity
    assert profile.phase == person.phase
    assert profile.user_id == person.user_id


def _run(expander, **overrides):
    kwargs = dict(
        catalog=_catalog(),
        family="log",
        seed=0,
        person=ROSTER[0],
        amount_path="named_measure",
        expander=expander,
        pool_size=8,
    )
    kwargs.update(overrides)
    return generate_one(**kwargs)


def test_generate_one_binds_grams_from_speech_not_expander_json() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.rejected is None
    assert result.accepted is not None
    row = result.accepted.oracle.ledger_tail[0]
    assert row.food_id == "milk_whole"
    assert row.grams == 244.0


def test_generate_one_rejects_grams_field_in_expander_json() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole"],
            "grams": 999.0,
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "schema"


def test_generate_one_rejects_old_items_expression_schema() -> None:
    def expand(_pool, *, persona, family):
        return {
            "items": [{"food": "milk_whole", "expression": "a cup"}],
            "query": "Please log a cup of milk for lunch.",
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "schema"


def test_generate_one_rejects_extra_keys_beside_query_and_foods() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole"],
            "items": [{"food": "milk_whole", "expression": "a cup"}],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "schema"


def test_generate_one_foods_must_be_pool_ids_not_spoken_names() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "not_in_pool"


def test_generate_one_rejects_food_id_absent_from_pool() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["tofu"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "not_in_pool"


def test_generate_one_rejects_unresolvable_speech() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a slice of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "unresolvable"


def test_generate_one_explicit_grams_path_may_contain_150_g() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log 150 g of chicken for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, amount_path="explicit_grams", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    assert "150 g" in result.accepted.query
    assert result.accepted.oracle.ledger_tail[0].food_id == "chicken_breast"
    assert result.accepted.oracle.ledger_tail[0].grams == 150.0


def test_generate_one_unspecified_bowl_of_rice_binds_qns_not_cup() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a bowl of rice for lunch.",
            "foods": ["white_rice"],
        }

    result = _run(expand, amount_path="unspecified")
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 118.0


def test_unspecified_amount_path_does_not_teach_a_serving_of() -> None:
    prompt = build_log_system_prompt(amount_path="unspecified")
    assert "a serving of" not in prompt.lower()
    explicit = build_log_system_prompt(amount_path="explicit_grams")
    assert "150 g" in explicit


def test_generate_one_does_not_hide_solid_cup() -> None:
    catalog = {
        "oats": _food("Oats, rolled", {"cup": 81.0}, ("oats", "oatmeal")),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
    }

    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a cup of oats for lunch.",
            "foods": ["oats"],
        }

    result = _run(expand, catalog=catalog, pool_size=2)
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 81.0


def test_generate_one_excludes_or_rejects_small_gram_so_band_cannot_pass_double() -> None:
    """±10 g is absolute; a 10 g piece would treat 0–20 g as a pass (2×)."""
    catalog = {
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
        "shrimp": _food("Shrimp, cooked", {"piece": 10.0}, ("shrimp",)),
    }

    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a piece of shrimp for lunch.",
            "foods": ["shrimp"],
        }

    result = _run(expand, catalog=catalog, pool_size=2)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"small_grams", "not_in_pool"}


def test_generate_one_rejects_naked_cut_noun_not_as_gold_pass() -> None:
    catalog = {
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
        "chicken_breast": _food(
            "Chicken breast, skinless, cooked",
            {"cup": 140.0, "qns": 105.0},
            ("chicken", "chicken breast"),
        ),
    }

    def expand(_pool, *, persona, family):
        return {
            "query": "Please log a chicken breast for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, catalog=catalog, pool_size=2)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"unresolvable", "cut_noun"}


def test_generate_one_has_no_skip_hard_bind_flag() -> None:
    names = inspect.signature(generate_one).parameters
    assert "skip_gram_backresolve" not in names
    assert "skip_hard_bind" not in names


def test_generate_one_cannot_skip_bind_to_admit_unresolvable_speech() -> None:
    def expand(_pool, *, persona, family):
        return {
            "query": "Please log some milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "unresolvable"


def test_generate_one_passes_amount_path_when_expander_accepts_it() -> None:
    seen: dict[str, str] = {}

    def expand(_pool, *, persona, family, amount_path):
        seen["amount_path"] = amount_path
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand, amount_path="explicit_grams")
    assert result.accepted is not None
    assert seen["amount_path"] == "explicit_grams"


def test_roster_is_twenty_adults() -> None:
    assert len(ROSTER) == 20
    assert all(19 <= person.age_y <= 75 for person in ROSTER)
    sexes = {person.sex for person in ROSTER}
    assert sexes == {"male", "female"}
    assert len({person.user_id for person in ROSTER}) == 20
