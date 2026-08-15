"""Smoke test only. env-verify owns the real suite."""

import pytest

from nutrienv.env import NutriEnv
from nutrienv.world import WorldState, resolve_portion
from nutrienv.world.catalog_fixture import demo_catalog, demo_profile, demo_state

CATALOG = demo_catalog()


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("milk_whole", "half a cup", 122.0),        # 244 / 2
        ("milk_whole", "1/2 cup", 122.0),
        ("milk_whole", "0.5 cups of milk", 122.0),
        ("milk_whole", "a cup", 244.0),
        ("milk_whole", "cup", 244.0),
        ("milk_whole", "two cups", 488.0),
        ("milk_whole", "one and a half cups", 366.0),
        ("milk_whole", "three quarters of a cup", 183.0),   # multiply, not 3 + 0.25
        ("milk_whole", "1 1/2 cups", 366.0),
        ("olive_oil", "2 tbsp", 27.0),
        ("olive_oil", "a tablespoon", 13.5),
        ("egg", "3 pieces", 150.0),
        ("whole_wheat_bread", "2 slices", 64.0),
        ("oats", "150g", 150.0),                    # gram units need no table entry
        ("oats", "150 grams", 150.0),
        ("oats", "2 ounces", 56.7),
        ("oats", "2 oz", 56.7),
    ],
)
def test_resolves_household_measures(food_id, phrase, grams):
    assert resolve_portion(food_id, phrase, CATALOG) == grams


@pytest.mark.parametrize(
    ("food_id", "phrase"),
    [
        ("unicorn_steak", "a cup"),        # unknown food
        ("milk_whole", "2 slices"),        # measure this food does not define
        ("whole_wheat_bread", "a cup"),
        ("milk_whole", "some milk"),       # no quantity the grammar knows
        ("milk_whole", "150"),             # bare number, no unit
        ("milk_whole", ""),
        ("milk_whole", "0 cups"),
        ("milk_whole", "-1 cups"),
    ],
)
def test_unresolvable_phrases_return_none(food_id, phrase):
    assert resolve_portion(food_id, phrase, CATALOG) is None


def test_get_food_observation_carries_portions():
    env = NutriEnv()
    env.reset(demo_state())
    food = env.step({"op": "get_food", "food_id": "milk_whole"})["observation"]["food"]
    assert food["portions"] == {"cup": 244.0, "tbsp": 15.3}


def test_portions_key_is_always_present():
    catalog = {"mystery": {"name": "Mystery", "nutrients": {}, "allergen_tags": [], "aliases": []}}
    env = NutriEnv()
    env.reset(WorldState(profile=demo_profile(), catalog=catalog))
    food = env.step({"op": "get_food", "food_id": "mystery"})["observation"]["food"]
    assert food["portions"] == {}
    assert resolve_portion("mystery", "a cup", catalog) is None
