"""A tiny in-memory catalog so anyone can run the Env without a Generator.

Nutrients are **per 100 g** of the food as described by its name. Values are
rounded USDA-style figures; they are fixture data, not a nutrition source of
truth. Allergen tags are lowercase snake_case and are what a Profile's
``allergies`` entries are expected to intersect with.

``portions`` maps a household measure to the grams it weighs *for that food*,
so a fuzzy phrase like "half a cup" becomes a number by table lookup instead of
model arithmetic. A food only carries the measures that make sense for it —
bread has ``slice``, oil has ``tbsp``, neither has the other. See
:func:`nutrienv.world.resolve_portion`.

Real Tasks get their catalog from the Generator's S0 (ADR 0003). This fixture
exists for smoke runs and examples.
"""

from __future__ import annotations

import copy

from .types import Profile, WorldState

NUTRIENT_KEYS = ("kcal", "protein_g", "carb_g", "fat_g", "fiber_g", "sodium_mg")

_CATALOG: dict[str, dict] = {
    "peanut_butter": {
        "name": "Peanut butter, smooth",
        "nutrients": {"kcal": 588.0, "protein_g": 25.1, "carb_g": 20.0, "fat_g": 50.4, "fiber_g": 6.0, "sodium_mg": 430.0},
        "allergen_tags": ["peanut"],
        "aliases": ["pb", "peanutbutter", "peanut spread"],
        "portions": {"tbsp": 16.0, "cup": 258.0},
    },
    "shrimp": {
        "name": "Shrimp, cooked",
        "nutrients": {"kcal": 99.0, "protein_g": 24.0, "carb_g": 0.2, "fat_g": 0.3, "fiber_g": 0.0, "sodium_mg": 111.0},
        "allergen_tags": ["shellfish"],
        "aliases": ["prawn", "prawns"],
        "portions": {"piece": 7.0, "cup": 145.0},
    },
    "oats": {
        "name": "Oats, rolled, dry",
        "nutrients": {"kcal": 389.0, "protein_g": 16.9, "carb_g": 66.3, "fat_g": 6.9, "fiber_g": 10.6, "sodium_mg": 2.0},
        "allergen_tags": [],
        "aliases": ["oatmeal", "rolled oats", "porridge oats"],
        "portions": {"cup": 81.0},
    },
    "egg": {
        "name": "Egg, whole, raw",
        "nutrients": {"kcal": 143.0, "protein_g": 12.6, "carb_g": 0.7, "fat_g": 9.5, "fiber_g": 0.0, "sodium_mg": 142.0},
        "allergen_tags": ["egg"],
        "aliases": ["eggs", "chicken egg"],
        "portions": {"piece": 50.0},
    },
    "white_rice": {
        "name": "Rice, white, cooked",
        "nutrients": {"kcal": 130.0, "protein_g": 2.7, "carb_g": 28.2, "fat_g": 0.3, "fiber_g": 0.4, "sodium_mg": 1.0},
        "allergen_tags": [],
        "aliases": ["rice", "steamed rice", "cooked rice"],
        "portions": {"cup": 158.0},
    },
    "milk_whole": {
        "name": "Milk, whole, 3.25% fat",
        "nutrients": {"kcal": 61.0, "protein_g": 3.2, "carb_g": 4.8, "fat_g": 3.3, "fiber_g": 0.0, "sodium_mg": 43.0},
        "allergen_tags": ["milk"],
        "aliases": ["milk", "whole milk", "full fat milk"],
        "portions": {"cup": 244.0, "tbsp": 15.3},
    },
    "chicken_breast": {
        "name": "Chicken breast, skinless, cooked",
        "nutrients": {"kcal": 165.0, "protein_g": 31.0, "carb_g": 0.0, "fat_g": 3.6, "fiber_g": 0.0, "sodium_mg": 74.0},
        "allergen_tags": [],
        "aliases": ["chicken", "chicken breast", "grilled chicken"],
        "portions": {"piece": 172.0},
    },
    "almond": {
        "name": "Almonds, raw",
        "nutrients": {"kcal": 579.0, "protein_g": 21.2, "carb_g": 21.6, "fat_g": 49.9, "fiber_g": 12.5, "sodium_mg": 1.0},
        "allergen_tags": ["tree_nut"],
        "aliases": ["almonds", "raw almonds"],
        "portions": {"piece": 1.2, "cup": 143.0},
    },
    "salmon": {
        "name": "Salmon, Atlantic, cooked",
        "nutrients": {"kcal": 208.0, "protein_g": 20.4, "carb_g": 0.0, "fat_g": 13.4, "fiber_g": 0.0, "sodium_mg": 59.0},
        "allergen_tags": ["fish"],
        "aliases": ["atlantic salmon", "baked salmon"],
        "portions": {"piece": 154.0},
    },
    "tofu": {
        "name": "Tofu, firm",
        "nutrients": {"kcal": 144.0, "protein_g": 17.3, "carb_g": 2.8, "fat_g": 8.7, "fiber_g": 2.3, "sodium_mg": 14.0},
        "allergen_tags": ["soy"],
        "aliases": ["bean curd", "firm tofu"],
        "portions": {"cup": 252.0},
    },
    "whole_wheat_bread": {
        "name": "Bread, whole wheat",
        "nutrients": {"kcal": 247.0, "protein_g": 13.0, "carb_g": 41.0, "fat_g": 3.4, "fiber_g": 7.0, "sodium_mg": 400.0},
        "allergen_tags": ["gluten", "wheat"],
        "aliases": ["bread", "wholemeal bread", "brown bread"],
        "portions": {"slice": 32.0},
    },
    "banana": {
        "name": "Banana, raw",
        "nutrients": {"kcal": 89.0, "protein_g": 1.1, "carb_g": 22.8, "fat_g": 0.3, "fiber_g": 2.6, "sodium_mg": 1.0},
        "allergen_tags": [],
        "aliases": ["bananas", "ripe banana"],
        "portions": {"piece": 118.0},
    },
    "broccoli": {
        "name": "Broccoli, raw",
        "nutrients": {"kcal": 34.0, "protein_g": 2.8, "carb_g": 6.6, "fat_g": 0.4, "fiber_g": 2.6, "sodium_mg": 33.0},
        "allergen_tags": [],
        "aliases": ["broccoli florets"],
        "portions": {"cup": 91.0},
    },
    "greek_yogurt": {
        "name": "Yogurt, Greek, plain, nonfat",
        "nutrients": {"kcal": 59.0, "protein_g": 10.3, "carb_g": 3.6, "fat_g": 0.4, "fiber_g": 0.0, "sodium_mg": 36.0},
        "allergen_tags": ["milk"],
        "aliases": ["yogurt", "greek yoghurt", "plain yogurt"],
        "portions": {"cup": 245.0, "tbsp": 15.3},
    },
    "olive_oil": {
        "name": "Oil, olive, extra virgin",
        "nutrients": {"kcal": 884.0, "protein_g": 0.0, "carb_g": 0.0, "fat_g": 100.0, "fiber_g": 0.0, "sodium_mg": 2.0},
        "allergen_tags": [],
        "aliases": ["olive oil", "evoo"],
        "portions": {"tbsp": 13.5, "tsp": 4.5},
    },
}


def demo_catalog() -> dict:
    """A fresh copy of the fixture catalog."""
    return copy.deepcopy(_CATALOG)


def demo_profile() -> Profile:
    """A plausible person with one allergy and two nutrient windows."""
    return Profile(
        user_id="demo",
        allergies=("peanut",),
        medications=(),
        windows={"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)},
        plan_preset={"meals_per_day": 3, "cuisine": "any"},
        version=1,
    )


def demo_state() -> WorldState:
    """A runnable S0 for smoke runs and examples. Not a Bench Task."""
    return WorldState(profile=demo_profile(), ledger=[], catalog=demo_catalog())
