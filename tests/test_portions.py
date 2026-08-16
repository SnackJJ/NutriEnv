"""Smoke test only. env-verify owns the real suite."""

import pytest

from nutrienv.env import NutriEnv
from nutrienv.harness.react import react_manual
from nutrienv.world import WorldState, resolve_portion
from nutrienv.world.catalog_fixture import demo_catalog, demo_profile, demo_state
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import OUNCE_GRAMS, UNIT_SYNONYMS

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

def _dish_catalog():
    """A tiny in-memory catalog of dishes for grammar tests."""
    return {
        "sandwich_nfs": {
            "name": "Sandwich, NFS", "nutrients": {}, "allergen_tags": [],
            "aliases": [], "portions": {"piece": 175.0},
        },
        "burrito_nfs": {
            "name": "Burrito, NFS", "nutrients": {}, "allergen_tags": [],
            "aliases": [], "portions": {"piece": 220.0, "cup": 120.0},
        },
        "foo_yung": {
            "name": "Shrimp egg foo yung", "nutrients": {}, "allergen_tags": [],
            "aliases": [], "portions": {"cup": 175.0},
        },
        "olive_oil": {
            "name": "Olive oil", "nutrients": {}, "allergen_tags": [],
            "aliases": [], "portions": {"tbsp": 13.5},
        },
        "milk_whole": {
            "name": "Milk, whole", "nutrients": {}, "allergen_tags": [],
            "aliases": [], "portions": {"cup": 244.0},
        },
    }


def test_serving_unit_uses_food_default_portion():
    catalog = _dish_catalog()
    assert resolve_portion("foo_yung", "a serving of shrimp egg foo yung", catalog) == 175.0
    assert resolve_portion("foo_yung", "two servings", catalog) == 350.0
    assert resolve_portion("foo_yung", "a bowl of foo yung", catalog) == 175.0
    # a food with no piece/slice/cup default has no "serving"
    assert resolve_portion("olive_oil", "a serving of olive oil", catalog) is None


def test_dish_noun_is_its_own_unit():
    catalog = _dish_catalog()
    assert resolve_portion("sandwich_nfs", "a sandwich", catalog) == 175.0
    assert resolve_portion("sandwich_nfs", "two sandwiches", catalog) == 350.0
    assert resolve_portion("burrito_nfs", "a burrito", catalog) == 220.0
    # the noun must name the food itself: no cross-food inventions
    assert resolve_portion("milk_whole", "a sandwich", catalog) is None
    assert resolve_portion("foo_yung", "a sandwich", catalog) is None
    # "some" carries no quantity, so it still asks for grams
    assert resolve_portion("sandwich_nfs", "some sandwich", catalog) is None


@pytest.fixture(scope="module")
def live_catalog():
    return load_catalog()


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("2705824", "a thick steak", 240.0),          # M1 thick
        ("2705824", "two thin steaks", 240.0),         # M2 thin ×2
        ("2705824", "a regular steak", 160.0),         # M3 regular
        ("2705824", "a thick serving", 240.0),         # M4 serving + thick
        ("2706880", "a regular serving", 115.0),       # M5
        ("2707684", "a thin serving", 46.0),           # M6 Bagel Thin
        ("2708312", "a thick serving", 135.0),         # M7 waffle
        ("2705824", "a thick slice", None),            # M8 explicit measure
        ("2705824", "two thin slices", None),          # M9
        ("2707777", "two thin slices", None),          # M10 must not be 84.0
        ("2707777", "two slices", 48.0),               # M11 unchanged
        ("2705824", "a large steak", None),            # M12 REFUSED_MODIFIERS
        ("2705866", "a thick pork chop", None),        # M13 chop not DISH_NOUNS
        ("2705824", "a thick", None),                  # M14 no unit to bind
    ],
)
def test_modifier_phrases_match_design(live_catalog, food_id, phrase, grams):
    assert resolve_portion(food_id, phrase, live_catalog) == grams


def test_modifier_missing_catalog_key_is_none():
    # M15: spoken thick, but the food has no thick key.
    catalog = _dish_catalog()
    assert resolve_portion("sandwich_nfs", "a thick sandwich", catalog) is None


@pytest.mark.parametrize(
    ("food_id", "phrase"),
    [
        ("2705824", "a thick thin steak"),
        ("2705824", "a thick thin"),
        ("2705824", "a regular thin steak"),
    ],
)
def test_mutex_modifiers_return_none(live_catalog, food_id, phrase):
    """Two size words in one phrase refuse (design §2.1.2)."""
    assert resolve_portion(food_id, phrase, live_catalog) is None


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("milk_whole", "8 fl oz", 244.0),              # F1
        ("milk_whole", "a fluid ounce", 30.5),         # F2
        ("milk_whole", "12 fluid ounces", 366.0),      # F3
        ("soy_milk", "8 fl oz", 244.0),                # F4
        ("milk_whole", "an ounce", 28.35),             # F5 must not steal fl_oz
        ("oats", "8 fl oz", None),                     # F6 no fl_oz key
    ],
)
def test_fl_oz_phrases_match_design(live_catalog, food_id, phrase, grams):
    assert resolve_portion(food_id, phrase, live_catalog) == grams


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("orange", "a serving", 154.0),                # Q1 qns
        ("broccoli", "a serving", 45.0),               # Q2
        ("avocado", "a serving", 30.0),                # Q3
        ("peanut_butter", "a serving", 32.0),          # Q4 newly resolvable
        ("potato", "a serving", 285.0),                # Q5
        ("cheddar", "a serving", 21.0),                # Q6 qns = slice
        ("167668", "a serving of fried rice", 137.0),  # Q7 no qns, cup fallback
        ("salmon", "a serving", None),                 # Q8 no portion keys
        ("2706880", "a sandwich", 115.0),              # Q9 qns, not piece
        ("2706880", "two sandwiches", 230.0),          # Q10
        ("2707198", "an omelet", 110.0),               # Q11
        ("2708750", "a serving of lasagna", 250.0),    # Q12
        ("2706880", "some sandwich", None),            # Q13 empty-span guard
        ("oats", "a serving", 10.0),                   # Q14 known qns regression
    ],
)
def test_serving_default_prefers_qns(live_catalog, food_id, phrase, grams):
    assert resolve_portion(food_id, phrase, live_catalog) == grams


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("cheddar", "a cubic inch", None),             # N1 catalog-only
        ("pasta", "an ounce", 28.35),                  # N2 not oz_yield
        ("pasta", "2 ounces", 56.7),                   # N3
        ("2705730", "an ounce", 28.35),                # N4 table oz == constant
    ],
)
def test_catalog_only_keys_stay_out_of_grammar(live_catalog, food_id, phrase, grams):
    assert resolve_portion(food_id, phrase, live_catalog) == grams
    assert "cubic_inch" not in UNIT_SYNONYMS
    assert "oz_yield" not in UNIT_SYNONYMS


@pytest.mark.parametrize(
    ("food_id", "phrase", "grams"),
    [
        ("pasta", "1 oz dry", None),
        ("pasta", "2 oz raw", None),
        ("oats", "a cup of uncooked oats", None),
        ("pasta", "2 oz", 56.7),
        ("pasta", "150 g chicken", 150.0),
        ("oats", "a cup", 80.0),  # ns-oatmeal phrase; "uncooked" is in the query
    ],
)
def test_refuses_state_words_after_unit(live_catalog, food_id, phrase, grams):
    """Design §6 5a: dry/raw/uncooked after a unit refuse; bare units stay."""
    assert resolve_portion(food_id, phrase, live_catalog) == grams


def test_manual_expressions_all_resolve(live_catalog):
    """Every measure word the v1 manual names must parse (AGENTS.md rule 4)."""
    manual = react_manual("v1")
    for word in (
        "cup", "tbsp", "tsp", "slice", "piece", "can", "fl_oz",
        "serving", "thick", "thin", "regular",
    ):
        assert word in manual
    assert resolve_portion("milk_whole", "half a cup", live_catalog) == 122.0
    assert resolve_portion("olive_oil", "a tablespoon", live_catalog) == 13.5
    assert resolve_portion("olive_oil", "a teaspoon", live_catalog) == 4.5
    assert resolve_portion("cheddar", "a slice", live_catalog) == 21.0
    assert resolve_portion("egg", "a piece", live_catalog) == 50.0
    assert "can" in UNIT_SYNONYMS
    assert resolve_portion("milk_whole", "8 fl oz", live_catalog) == 244.0
    assert resolve_portion("orange", "a serving", live_catalog) == 154.0
    assert resolve_portion("2705824", "a thick steak", live_catalog) == 240.0
    assert resolve_portion("2705824", "two thin steaks", live_catalog) == 240.0
    assert resolve_portion("2706880", "a regular serving", live_catalog) == 115.0
    assert resolve_portion("cheddar", "2 oz", live_catalog) == 56.7
    assert resolve_portion("shrimp", "150 g", live_catalog) == 150.0
    # Reverse symmetry: catalog-only keys appear only as "do not convert".
    assert "oz_yield" in manual
    assert "cubic_inch" in manual
    assert "do not convert" in manual.lower()
    assert "oz_yield" not in UNIT_SYNONYMS
    assert "cubic_inch" not in UNIT_SYNONYMS
    assert resolve_portion("cheddar", "a cubic inch", live_catalog) is None
    assert resolve_portion("pasta", "an ounce", live_catalog) == OUNCE_GRAMS


def test_omelet_piece_55_is_legal_table_value(live_catalog):
    """Gray-zone regression: omelet piece=55 is an FNDDS table value.

    reports/gray-zone-probe.md: the judge false-killed 55 g (ok_frac=0.40).
    A table value is whitelist-legal and must not be sent to the judge.
    """
    portions = live_catalog["2707198"]["portions"]
    assert portions["piece"] == 55.0
    assert portions["qns"] == 110.0
    table_values = {
        float(value)
        for value in portions.values()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    assert 55.0 in table_values
    # Spoken "an omelet" now reads qns; the piece row stays a legal table value.
    assert resolve_portion("2707198", "an omelet", live_catalog) == 110.0
    assert resolve_portion("2707198", "a piece", live_catalog) == 55.0