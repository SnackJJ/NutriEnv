"""Ticket 06: generate_one Log mill — roster world, {query, foods}, speech bind."""

from __future__ import annotations

import inspect
import json

from nutrienv.bench.pipeline.generate_one import (
    build_log_system_prompt,
    generate_one,
    make_log_expander,
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


def _cup_expander(pool, *, persona, family, amount_path=None):
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
    def expand(_pool, *, persona, family, amount_path=None):
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
    def expand(_pool, *, persona, family, amount_path=None):
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
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "items": [{"food": "milk_whole", "expression": "a cup"}],
            "query": "Please log a cup of milk for lunch.",
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "schema"


def test_generate_one_rejects_extra_keys_beside_query_and_foods() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
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
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "not_in_pool"


def test_generate_one_rejects_repeated_speech_of_the_same_food() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk and another cup of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "repeat"


def test_generate_one_rejects_duplicate_food_ids() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole", "milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "duplicate"


def test_generate_one_rejects_food_id_absent_from_pool() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["tofu"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "not_in_pool"


def test_generate_one_rejects_overlapping_rice_aliases() -> None:
    catalog = {
        "rice_nfs": _food("Paddy rice", {"cup": 160.0}, ("rice",)),
        "white_rice": _food(
            "White rice, cooked", {"cup": 158.0, "qns": 118.0}, ("white rice",)
        ),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
    }

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of white rice for lunch.",
            "foods": ["white_rice", "rice_nfs"],
        }

    result = _run(expand, catalog=catalog, pool_size=3)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "ambiguous"


def test_generate_one_rejects_ambiguous_shared_mention() -> None:
    catalog = {
        "coffee_ns": _food("Coffee, NS as to type", {"cup": 240.0}, ("coffee",)),
        "coffee_brewed": _food("Coffee, brewed", {"cup": 248.0}, ("coffee",)),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
    }

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of coffee for lunch.",
            "foods": ["coffee_ns", "coffee_brewed"],
        }

    result = _run(expand, catalog=catalog, pool_size=3)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "ambiguous"


def test_generate_one_rejects_out_of_pool_food_named_in_query() -> None:
    catalog = {
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
        "oats": _food("Oats, rolled", {"cup": 81.0}, ("oats",)),
        "tofu": _food("Tofu, firm", {}, ("tofu",)),
    }

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk and a cup of tofu for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand, catalog=catalog, pool_size=2)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"omitted_food", "unresolvable", "not_in_pool"}


def test_generate_one_accepts_milk_when_catalog_has_many_milk_names() -> None:
    catalog = _catalog()
    for index in range(67):
        catalog[f"milk_other_{index}"] = _food("Milk, NFS", {}, ("milk",))

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand, catalog=catalog, pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].food_id == "milk_whole"
    assert result.accepted.oracle.ledger_tail[0].grams == 244.0


def test_generate_one_rejects_query_food_omitted_from_foods_json() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of milk and a cup of rice for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand, pool_size=12)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"omitted_food", "unresolvable"}


def test_generate_one_rejects_unresolvable_speech() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a slice of milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "unresolvable"


def test_generate_one_rejects_grams_over_world_cap() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log 99999 g of chicken for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, amount_path="explicit_grams", pool_size=12)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "over_cap"


def test_generate_one_explicit_grams_path_may_contain_150_g() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
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


def test_generate_one_unspecified_rejects_named_cup() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of rice for lunch.",
            "foods": ["white_rice"],
        }

    result = _run(expand, amount_path="unspecified")
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"amount_path", "unresolvable"}


def test_generate_one_named_measure_rejects_explicit_grams() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log 150 g of chicken for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, amount_path="named_measure", pool_size=12)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"amount_path", "unresolvable"}


def test_generate_one_binds_each_food_from_its_local_phrase() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of chicken and two cups of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    result = _run(expand, amount_path="named_measure", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    rows = {row.food_id: row.grams for row in result.accepted.oracle.ledger_tail}
    assert rows["chicken_breast"] == 140.0
    assert rows["white_rice"] == 316.0


def test_generate_one_splits_speech_clauses_on_with() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of chicken with two cups of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    result = _run(expand, amount_path="named_measure", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    rows = {row.food_id: row.grams for row in result.accepted.oracle.ledger_tail}
    assert rows["chicken_breast"] == 140.0
    assert rows["white_rice"] == 316.0


def test_generate_one_keeps_one_and_a_half_as_one_quantity() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log one and a half cups of rice for lunch.",
            "foods": ["white_rice"],
        }

    result = _run(expand, amount_path="named_measure", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 237.0


def test_generate_one_keeps_hyphenated_one_and_a_half_as_one_quantity() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log one-and-a-half cups of rice for lunch.",
            "foods": ["white_rice"],
        }

    result = _run(expand, amount_path="named_measure", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 237.0


def test_generate_one_keeps_thousands_comma_in_spoken_grams() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log 1,500 g of chicken for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, amount_path="explicit_grams", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 1500.0


def test_generate_one_splits_speech_clauses_on_plus_and_ampersand() -> None:
    def expand_plus(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of chicken plus two cups of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    plus = _run(expand_plus, amount_path="named_measure", pool_size=12)
    assert plus.rejected is None
    assert plus.accepted is not None
    rows = {row.food_id: row.grams for row in plus.accepted.oracle.ledger_tail}
    assert rows["chicken_breast"] == 140.0
    assert rows["white_rice"] == 316.0

    def expand_amp(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of chicken & two cups of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    amp = _run(expand_amp, amount_path="named_measure", pool_size=12)
    assert amp.rejected is None
    assert amp.accepted is not None
    rows = {row.food_id: row.grams for row in amp.accepted.oracle.ledger_tail}
    assert rows["chicken_breast"] == 140.0
    assert rows["white_rice"] == 316.0


def test_generate_one_mixed_cup_and_bowl_does_not_freeze_rice_as_cup() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a cup of chicken and a bowl of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    result = _run(expand, amount_path="unspecified", pool_size=12)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"amount_path", "unresolvable"}


def test_generate_one_unspecified_two_bowls_bind_qns_not_cup() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a bowl of chicken and a bowl of rice for lunch.",
            "foods": ["chicken_breast", "white_rice"],
        }

    result = _run(expand, amount_path="unspecified", pool_size=12)
    assert result.rejected is None
    assert result.accepted is not None
    rows = {row.food_id: row.grams for row in result.accepted.oracle.ledger_tail}
    assert rows["chicken_breast"] == 105.0
    assert rows["white_rice"] == 118.0


def test_generate_one_unspecified_bowl_on_cup_only_food_does_not_bind_cup() -> None:
    catalog = {
        "oats": _food("Oats, rolled", {"cup": 81.0}, ("oats", "oatmeal")),
        "milk_whole": _food("Milk, whole", {"cup": 244.0}, ("milk",)),
    }

    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log a bowl of oats for lunch.",
            "foods": ["oats"],
        }

    result = _run(expand, catalog=catalog, amount_path="unspecified", pool_size=2)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason in {"unresolvable", "amount_path"}


def test_generate_one_unspecified_bowl_of_rice_binds_qns_not_cup() -> None:
    def expand(_pool, *, persona, family, amount_path=None):
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

    def expand(_pool, *, persona, family, amount_path=None):
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

    def expand(_pool, *, persona, family, amount_path=None):
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

    def expand(_pool, *, persona, family, amount_path=None):
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
    def expand(_pool, *, persona, family, amount_path=None):
        return {
            "query": "Please log some milk for lunch.",
            "foods": ["milk_whole"],
        }

    result = _run(expand)
    assert result.accepted is None
    assert result.rejected is not None
    assert result.rejected.reason == "unresolvable"


def test_generate_one_always_passes_amount_path_to_expander() -> None:
    seen: dict[str, str] = {}

    def expand(_pool, *, persona, family, amount_path):
        seen["amount_path"] = amount_path
        return {
            "query": "Please log 150 g of chicken for lunch.",
            "foods": ["chicken_breast"],
        }

    result = _run(expand, amount_path="explicit_grams", pool_size=12)
    assert result.accepted is not None
    assert seen["amount_path"] == "explicit_grams"


def test_generate_one_mill_expander_uses_amount_path_system_prompt() -> None:
    seen: list[str] = []

    def complete(_model_id, messages):
        seen.append(messages[0]["content"])
        return json.dumps(
            {
                "query": "Please log a cup of milk for lunch.",
                "foods": ["milk_whole"],
            }
        )

    result = _run(
        make_log_expander(complete=complete),
        amount_path="named_measure",
        pool_size=12,
        person=ROSTER[0],
    )
    assert seen
    assert seen[0] == build_log_system_prompt(
        amount_path="named_measure", persona=ROSTER[0].persona
    )
    assert result.accepted is not None
    assert result.accepted.oracle.ledger_tail[0].grams == 244.0


def test_roster_is_twenty_adults() -> None:
    assert len(ROSTER) == 20
    assert all(19 <= person.age_y <= 75 for person in ROSTER)
    sexes = {person.sex for person in ROSTER}
    assert sexes == {"male", "female"}
    assert len({person.user_id for person in ROSTER}) == 20
