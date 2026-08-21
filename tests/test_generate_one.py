"""Ticket 06: generate_one Log mill — roster world, {query, foods}, speech bind."""

from __future__ import annotations

from nutrienv.bench.pipeline.generate_one import generate_one
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
