"""Catalog-backed realization tables for the draft factory.

Rows differ in food / portion / ledger geometry. Paraphrases are not new
rows. Grams are never stored: `resolve_portion` and `ledger_totals` compute
them. A row whose phrase does not resolve is invalid and must not be listed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import LedgerRow, ledger_totals

__all__ = [
    "FuzzyRow",
    "LeftoverRow",
    "UpdateRow",
    "ConstrainRow",
    "EvaluateRow",
    "FUZZY_ROWS",
    "LEFTOVER_ROWS",
    "UPDATE_ROWS",
    "CONSTRAIN_ROWS",
    "EVALUATE_ROWS",
    "fuzzy_key",
    "leftover_key",
    "update_key",
    "constrain_key",
    "evaluate_key",
    "evaluate_windows",
    "assert_fuzzy_resolves",
    "assert_leftover_rows",
    "assert_update_rows",
    "assert_constrain_rows",
    "assert_evaluate_rows",
]


@dataclass(frozen=True)
class FuzzyRow:
    seed_id: str
    food_id: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"
    review: str = "ok"


@dataclass(frozen=True)
class LeftoverRow:
    seed_id: str
    query: str
    windows: dict[str, tuple[float, float]]
    ledger: tuple[tuple[str, float, str], ...]
    allergies: tuple[str, ...] = ()
    source: str = "novel"
    plan_preset: dict | None = None


@dataclass(frozen=True)
class UpdateRow:
    seed_id: str
    query: str
    add_allergens: tuple[str, ...] = ()
    window_shifts: dict[str, float] | None = None
    s0_allergies: tuple[str, ...] | None = None
    s0_plan_preset: dict | None = None
    source: str = "novel"


@dataclass(frozen=True)
class ConstrainRow:
    seed_id: str
    kind: str
    query: str
    allergies: tuple[str, ...]
    windows: dict[str, tuple[float, float]]
    food_id: str | None = None
    last_plan: tuple[tuple[str, float], ...] = ()
    source: str = "novel"


@dataclass(frozen=True)
class EvaluateRow:
    seed_id: str
    query: str
    items: tuple[tuple[str, str], ...]
    margin_kcal: float = 150.0
    margin_protein: float = 15.0
    source: str = "novel"


def fuzzy_key(row: FuzzyRow) -> tuple:
    return ("log", "fuzzy_portion", "everyday", row.food_id, row.phrase, row.slot)


def leftover_key(row: LeftoverRow) -> tuple:
    foods = tuple((food_id, slot) for food_id, _grams, slot in row.ledger)
    return ("recommend", None, "leftover", foods, tuple(sorted(row.windows)))


def update_key(row: UpdateRow) -> tuple:
    shifts = tuple(sorted((row.window_shifts or {}).items()))
    return ("update", tuple(row.add_allergens), shifts, row.s0_allergies)


def constrain_key(row: ConstrainRow) -> tuple:
    windows = tuple(sorted((key, bounds) for key, bounds in row.windows.items()))
    return ("constrain", row.kind, row.food_id, row.allergies, windows, row.last_plan)


def evaluate_key(row: EvaluateRow) -> tuple:
    return ("evaluate", row.items)


def evaluate_windows(
    items: list[dict],
    catalog,
    kcal_margin: float = 150.0,
    protein_margin: float = 15.0,
) -> dict[str, tuple[float, float]]:
    """Meal windows from live totals. Grams are never stored on the row."""
    rows = [
        LedgerRow(str(item["food_id"]), float(item["grams"]), "eval") for item in items
    ]
    totals = ledger_totals(rows, catalog)
    out: dict[str, tuple[float, float]] = {}
    for key, margin in (("kcal", kcal_margin), ("protein_g", protein_margin)):
        total = totals.get(key, 0.0)
        lo = math.floor((total - margin) / 10.0) * 10.0
        hi = math.ceil((total + margin) / 10.0) * 10.0
        if lo < 0:
            lo = 0.0
        out[key] = (float(lo), float(hi))
    return out


# Gold-derived first so the factory still covers the calibration shapes.
# New rows after that are candidates for v0.1.
FUZZY_ROWS: tuple[FuzzyRow, ...] = (
    FuzzyRow("fz-milk-half-cup", "milk_whole", "half a cup",
             "I had half a cup of milk with breakfast — can you log that?",
             "today-breakfast", source="gold"),
    FuzzyRow("fz-eggs-two-piece", "egg", "two pieces",
             "I had two eggs this morning — can you log that?",
             "today-breakfast", source="gold"),
    FuzzyRow("fz-banana-piece", "banana", "a piece",
             "Just ate a banana as a snack — can you log it?",
             "today-snack", source="gold"),
    FuzzyRow("fz-yogurt-cup", "greek_yogurt", "a cup",
             "Had a cup of Greek yogurt as a snack. Please log it.",
             "today-snack", source="gold"),
    FuzzyRow("fz-oil-tbsp", "olive_oil", "a tablespoon",
             "I put a tablespoon of olive oil on my salad at lunch. Log that?",
             "today-lunch", source="gold"),
    FuzzyRow("fz-milk-cup", "milk_whole", "a cup",
             "I drank a cup of milk with breakfast. Please log it.",
             "today-breakfast"),
    FuzzyRow("fz-oats-cup", "oats", "a cup",
             "Breakfast was a cup of oats. Can you log that?",
             "today-breakfast"),
    FuzzyRow("fz-yogurt-half", "greek_yogurt", "half a cup",
             "Snack was half a cup of Greek yogurt. Log it for me.",
             "today-snack"),
    FuzzyRow("fz-oil-tsp", "olive_oil", "a teaspoon",
             "I added a teaspoon of olive oil at lunch. Please log it.",
             "today-lunch"),
    FuzzyRow("fz-cheddar-slice", "cheddar", "a slice",
             "Had a slice of cheddar at lunch — can you log that?",
             "today-lunch"),
    FuzzyRow("fz-orange-slice", "orange", "a slice",
             "I ate a slice of orange as a snack. Log it?",
             "today-snack"),
    FuzzyRow("fz-avocado-slice", "avocado", "a slice",
             "Put a slice of avocado on my lunch. Please log that.",
             "today-lunch"),
    FuzzyRow("fz-apple-piece", "apple", "a piece",
             "Just ate an apple as a snack — can you log it?",
             "today-snack"),
    FuzzyRow("fz-tofu-cup", "tofu", "a cup",
             "Lunch was a cup of tofu. Please log it.",
             "today-lunch"),
    FuzzyRow("fz-pasta-cup", "pasta", "a cup",
             "I had a cup of pasta for dinner. Log that?",
             "today-dinner"),
    FuzzyRow("fz-beans-cup", "black_beans", "a cup",
             "Had a cup of black beans at lunch. Can you log that?",
             "today-lunch"),
    FuzzyRow("fz-soymilk-half", "soy_milk", "half a cup",
             "I had half a cup of soy milk with breakfast. Please log it.",
             "today-breakfast"),
    FuzzyRow("fz-spinach-cup", "spinach", "a cup",
             "Dinner side was a cup of spinach. Log it for me.",
             "today-dinner"),
    FuzzyRow("fz-pb-tbsp", "peanut_butter", "a tablespoon",
             "I had a tablespoon of peanut butter at breakfast. Please log it.",
             "today-breakfast"),
    FuzzyRow("fz-tuna-can", "tuna", "a can",
             "Logged lunch already? I ate a can of tuna. Please add it.",
             "today-lunch"),
    FuzzyRow("fz-potato-piece", "potato", "a piece",
             "I had a baked potato for dinner. Can you log that?",
             "today-dinner"),
    FuzzyRow("fz-almond-half", "almond", "half a cup",
             "Snack was half a cup of almonds. Please log it.",
             "today-snack"),
    FuzzyRow("fz-rice-half", "white_rice", "half a cup",
             "I had half a cup of rice at dinner. Log that?",
             "today-dinner"),
    FuzzyRow("fz-oats-oz", "oats", "2 ounces",
             "Snack was about 2 ounces of oats. Log it for me.",
             "today-snack", source="gold"),
)


_E = {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)}
_CUT = {"kcal": (1600.0, 1900.0), "protein_g": (110.0, 160.0)}
_HIGHP = {"kcal": (1800.0, 2200.0), "protein_g": (120.0, 180.0)}

LEFTOVER_ROWS: tuple[LeftoverRow, ...] = (
    LeftoverRow(
        "lo-gold-early",
        "I already ate breakfast and lunch. What should I eat?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 118.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
            ("chicken_breast", 200.0, "today-lunch"),
            ("white_rice", 300.0, "today-lunch"),
            ("olive_oil", 20.0, "today-lunch"),
            ("cheddar", 40.0, "today-lunch"),
        ),
        source="gold",
    ),
    LeftoverRow(
        "lo-gold-three-meals",
        "I already ate breakfast, lunch, and a snack. Can I still eat something?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 118.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
            ("beef", 180.0, "today-lunch"),
            ("pasta", 280.0, "today-lunch"),
            ("olive_oil", 18.0, "today-lunch"),
            ("spinach", 90.0, "today-lunch"),
            ("greek_yogurt", 200.0, "today-snack"),
            ("apple", 182.0, "today-snack"),
        ),
        source="gold",
    ),
    LeftoverRow(
        "lo-gold-cut",
        "I'm cutting and I already ate breakfast and lunch. What can I still eat?",
        {"kcal": (1600.0, 1900.0), "protein_g": (110.0, 160.0)},
        (
            ("oats", 60.0, "today-breakfast"),
            ("greek_yogurt", 170.0, "today-breakfast"),
            ("banana", 118.0, "today-breakfast"),
            ("chicken_breast", 90.0, "today-lunch"),
            ("white_rice", 250.0, "today-lunch"),
            ("broccoli", 100.0, "today-lunch"),
            ("olive_oil", 12.0, "today-lunch"),
            ("cheddar", 40.0, "today-lunch"),
            ("potato", 200.0, "today-lunch"),
        ),
        source="gold",
        plan_preset={"goal": "cut"},
    ),
    LeftoverRow(
        "lo-breakfast-only",
        "I only had breakfast. What should I eat for the rest of the day?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 118.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
        ),
    ),
    LeftoverRow(
        "lo-protein-debt",
        "I already ate breakfast and lunch. I still want to hit protein.",
        {"kcal": (1800.0, 2200.0), "protein_g": (120.0, 180.0)},
        (
            ("white_rice", 300.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("apple", 182.0, "today-breakfast"),
            ("pasta", 200.0, "today-lunch"),
            ("olive_oil", 15.0, "today-lunch"),
            ("broccoli", 150.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-protein-met",
        "I already ate a high-protein breakfast and lunch. What should I eat for the rest of the day?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("egg", 100.0, "today-breakfast"),
            ("greek_yogurt", 245.0, "today-breakfast"),
            ("chicken_breast", 220.0, "today-lunch"),
            ("spinach", 80.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-snack-no-lunch",
        "I had breakfast and a snack but skipped lunch. What should I eat for the rest of the day?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
            ("greek_yogurt", 200.0, "today-snack"),
            ("apple", 182.0, "today-snack"),
        ),
    ),
    LeftoverRow(
        "lo-tofu-lunch",
        "I already ate breakfast and a tofu lunch. What should I eat for the rest of the day?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("soy_milk", 244.0, "today-breakfast"),
            ("oats", 80.0, "today-breakfast"),
            ("tofu", 200.0, "today-lunch"),
            ("black_beans", 172.0, "today-lunch"),
            ("white_rice", 200.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-almost-full",
        "I already ate breakfast, lunch, and a snack. Is there room for anything else?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 118.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
            ("chicken_breast", 180.0, "today-lunch"),
            ("white_rice", 280.0, "today-lunch"),
            ("olive_oil", 18.0, "today-lunch"),
            ("greek_yogurt", 200.0, "today-snack"),
            ("apple", 182.0, "today-snack"),
        ),
    ),
    LeftoverRow(
        "lo-cut-salmon",
        "I'm cutting and already ate breakfast and lunch. What should I eat for the rest of the day?",
        {"kcal": (1600.0, 1900.0), "protein_g": (110.0, 160.0)},
        (
            ("oats", 60.0, "today-breakfast"),
            ("greek_yogurt", 170.0, "today-breakfast"),
            ("salmon", 150.0, "today-lunch"),
            ("broccoli", 120.0, "today-lunch"),
            ("olive_oil", 10.0, "today-lunch"),
        ),
        plan_preset={"goal": "cut"},
    ),
    LeftoverRow(
        "lo-beans-rice",
        "Breakfast and a beans-and-rice lunch are already logged. What should I eat for the rest of the day?",
        {"kcal": (1800.0, 2200.0), "protein_g": (80.0, 160.0)},
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("black_beans", 172.0, "today-lunch"),
            ("white_rice", 250.0, "today-lunch"),
            ("avocado", 75.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-tuna-lunch",
        "I already ate breakfast and a tuna lunch. What should I eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("tuna", 165.0, "today-lunch"),
            ("spinach", 50.0, "today-lunch"),
            ("white_rice", 158.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-avocado-rice",
        "Breakfast and an avocado-and-rice lunch are already logged. What should I eat for the rest of the day?",
        _E,
        (
            ("soy_milk", 244.0, "today-breakfast"),
            ("oats", 80.0, "today-breakfast"),
            ("avocado", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-lunch"),
            ("black_beans", 172.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-dinner-logged",
        "I already ate breakfast, lunch, and dinner. Is there room for a late bite?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("milk_whole", 244.0, "today-breakfast"),
            ("chicken_breast", 180.0, "today-lunch"),
            ("white_rice", 250.0, "today-lunch"),
            ("olive_oil", 15.0, "today-lunch"),
            ("pasta", 200.0, "today-dinner"),
            ("beef", 150.0, "today-dinner"),
            ("spinach", 80.0, "today-dinner"),
        ),
    ),
    LeftoverRow(
        "lo-skip-breakfast",
        "I skipped breakfast and already ate lunch. What should I eat for the rest of the day?",
        _E,
        (
            ("chicken_breast", 200.0, "today-lunch"),
            ("white_rice", 250.0, "today-lunch"),
            ("broccoli", 150.0, "today-lunch"),
            ("olive_oil", 15.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-almond-snack",
        "I already ate breakfast, lunch, and a handful of almonds. What should I eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("chicken_breast", 160.0, "today-lunch"),
            ("broccoli", 120.0, "today-lunch"),
            ("almond", 36.0, "today-snack"),
        ),
    ),
    LeftoverRow(
        "lo-peanut-allergy",
        "Breakfast and lunch are already in. What can I still eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("chicken_breast", 180.0, "today-lunch"),
            ("white_rice", 200.0, "today-lunch"),
            ("broccoli", 100.0, "today-lunch"),
        ),
        allergies=("peanut",),
    ),
    LeftoverRow(
        "lo-milk-allergy",
        "I already logged breakfast and lunch. What should I eat for the rest of the day?",
        _E,
        (
            ("soy_milk", 244.0, "today-breakfast"),
            ("oats", 80.0, "today-breakfast"),
            ("apple", 200.0, "today-breakfast"),
            ("chicken_breast", 170.0, "today-lunch"),
            ("potato", 230.0, "today-lunch"),
            ("spinach", 80.0, "today-lunch"),
        ),
        allergies=("milk",),
    ),
    LeftoverRow(
        "lo-cut-tight",
        "I'm cutting and I already ate breakfast, lunch, and a snack. What should I eat for the rest of the day?",
        _CUT,
        (
            ("oats", 60.0, "today-breakfast"),
            ("greek_yogurt", 170.0, "today-breakfast"),
            ("chicken_breast", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-lunch"),
            ("broccoli", 100.0, "today-lunch"),
            ("olive_oil", 10.0, "today-lunch"),
            ("apple", 200.0, "today-snack"),
        ),
        plan_preset={"goal": "cut"},
    ),
    LeftoverRow(
        "lo-potato-lunch",
        "I already ate breakfast and a potato lunch. What should I eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("potato", 230.0, "today-lunch"),
            ("cheddar", 42.0, "today-lunch"),
            ("broccoli", 100.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-pb-breakfast",
        "I only had breakfast — oats with peanut butter. What should I eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("peanut_butter", 32.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
        ),
    ),
    LeftoverRow(
        "lo-beef-pasta",
        "Breakfast and a beef-and-pasta lunch are already logged. What should I eat for the rest of the day?",
        _E,
        (
            ("greek_yogurt", 245.0, "today-breakfast"),
            ("orange", 180.0, "today-breakfast"),
            ("beef", 180.0, "today-lunch"),
            ("pasta", 280.0, "today-lunch"),
            ("spinach", 90.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-late-snack-only",
        "I've only had a snack so far. What should I eat for the rest of the day?",
        _E,
        (
            ("greek_yogurt", 200.0, "today-snack"),
            ("apple", 200.0, "today-snack"),
        ),
    ),
    LeftoverRow(
        "lo-three-carb-debt",
        "I already ate, but I still want to hit protein. What should I eat?",
        _HIGHP,
        (
            ("white_rice", 250.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
            ("pasta", 280.0, "today-lunch"),
            ("olive_oil", 18.0, "today-lunch"),
            ("apple", 200.0, "today-lunch"),
            ("potato", 230.0, "today-snack"),
        ),
    ),
    LeftoverRow(
        "lo-gym-protein-in",
        "Breakfast and lunch were already high in protein. What should I eat for the rest of the day?",
        _E,
        (
            ("egg", 150.0, "today-breakfast"),
            ("greek_yogurt", 245.0, "today-breakfast"),
            ("tuna", 165.0, "today-lunch"),
            ("spinach", 80.0, "today-lunch"),
            ("chicken_breast", 150.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-shrimp-lunch",
        "I already ate breakfast and a shrimp lunch. What should I eat for the rest of the day?",
        _E,
        (
            ("oats", 80.0, "today-breakfast"),
            ("orange", 180.0, "today-breakfast"),
            ("shrimp", 200.0, "today-lunch"),
            ("white_rice", 200.0, "today-lunch"),
            ("broccoli", 100.0, "today-lunch"),
        ),
    ),
    LeftoverRow(
        "lo-cut-breakfast-only",
        "I'm cutting and I only had breakfast. What should I eat for the rest of the day?",
        _CUT,
        (
            ("oats", 60.0, "today-breakfast"),
            ("greek_yogurt", 170.0, "today-breakfast"),
            ("banana", 126.0, "today-breakfast"),
        ),
        plan_preset={"goal": "cut"},
    ),
)


UPDATE_ROWS: tuple[UpdateRow, ...] = (
    UpdateRow(
        "up-gold-shrimp",
        "I just found out I'm allergic to shrimp. Add that to my profile.",
        add_allergens=("shellfish",),
        source="gold",
    ),
    UpdateRow(
        "up-gold-kcal",
        "I've been exhausted. Move my whole calorie range up by 200 — both the floor and the ceiling. Leave everything else alone.",
        window_shifts={"kcal": 200.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-both",
        "Add shellfish to my allergies — I reacted to shrimp — and move my whole calorie range up by 200. Don't change anything else.",
        add_allergens=("shellfish",),
        window_shifts={"kcal": 200.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-peanut",
        "Add peanut to my allergies.",
        add_allergens=("peanut",),
        s0_allergies=("shellfish",),
        source="gold",
    ),
    UpdateRow(
        "up-gold-protein",
        "I want more protein. Shift my protein range up 20 grams at both ends.",
        window_shifts={"protein_g": 20.0},
        source="gold",
    ),
    UpdateRow(
        "up-gold-cut",
        "I'm cutting now. Take 300 off both ends of my calorie range.",
        window_shifts={"kcal": -300.0},
        s0_allergies=(),
        s0_plan_preset={"goal": "cut"},
        source="gold",
    ),
    UpdateRow(
        "up-milk",
        "I reacted to milk. Add that to my allergies.",
        add_allergens=("milk",),
    ),
    UpdateRow(
        "up-soy-tofu",
        "I reacted to tofu. Add that to my allergies.",
        add_allergens=("soy",),
    ),
    UpdateRow(
        "up-egg",
        "I reacted to eggs. Add that to my allergies.",
        add_allergens=("egg",),
    ),
    UpdateRow(
        "up-fish-salmon",
        "I reacted to salmon. Add that to my allergies.",
        add_allergens=("fish",),
    ),
    UpdateRow(
        "up-tree-nut-almonds",
        "I reacted to almonds. Add that to my allergies.",
        add_allergens=("tree_nut",),
    ),
    UpdateRow(
        "up-kcal-plus-300",
        "Raise my whole calorie range by 300 at both ends.",
        window_shifts={"kcal": 300.0},
    ),
    UpdateRow(
        "up-kcal-minus-200",
        "Lower my whole calorie range by 200 at both ends.",
        window_shifts={"kcal": -200.0},
    ),
    UpdateRow(
        "up-protein-plus-30",
        "I want more protein. Shift my protein range up 30 grams at both ends.",
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-milk-kcal-200",
        "I reacted to milk. Add that to my allergies and raise my calorie range by 200 at both ends.",
        add_allergens=("milk",),
        window_shifts={"kcal": 200.0},
    ),
    UpdateRow(
        "up-soy-kcal-300",
        "I reacted to tofu. Add that to my allergies and increase my calorie range by 300 at both ends.",
        add_allergens=("soy",),
        window_shifts={"kcal": 300.0},
    ),
    UpdateRow(
        "up-egg-protein-20",
        "I reacted to eggs. Add that to my allergies and shift my protein range up 20 grams at both ends.",
        add_allergens=("egg",),
        window_shifts={"protein_g": 20.0},
    ),
    UpdateRow(
        "up-fish-protein-30",
        "I reacted to salmon. Add that to my allergies and raise my protein range 30 grams at both ends.",
        add_allergens=("fish",),
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-almond-kcal-minus-200",
        "I reacted to almonds. Add that to my allergies and lower my calorie range by 200 at both ends.",
        add_allergens=("tree_nut",),
        window_shifts={"kcal": -200.0},
    ),
    UpdateRow(
        "up-cut-400",
        "I'm cutting. Reduce my calorie range by 400 at both ends.",
        window_shifts={"kcal": -400.0},
        s0_allergies=(),
        s0_plan_preset={"goal": "cut"},
    ),
    UpdateRow(
        "up-milk-protein-30",
        "I reacted to milk. Add that to my allergies and shift my protein range up 30 grams at both ends.",
        add_allergens=("milk",),
        window_shifts={"protein_g": 30.0},
    ),
    UpdateRow(
        "up-egg-kcal-300",
        "I reacted to eggs. Add that to my allergies and raise my calorie range by 300 at both ends.",
        add_allergens=("egg",),
        window_shifts={"kcal": 300.0},
    ),
)


_MEAL = {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)}

CONSTRAIN_ROWS: tuple[ConstrainRow, ...] = (
    ConstrainRow(
        "co-gold-shrimp",
        "condition",
        "I was thinking of having shrimp tonight. Is that okay for me, or what should I have instead?",
        ("shellfish",),
        _MEAL,
        food_id="shrimp",
        source="gold",
    ),
    ConstrainRow(
        "co-gold-pb",
        "condition",
        "Is peanut butter okay for me, or what should I have instead?",
        ("peanut",),
        _MEAL,
        food_id="peanut_butter",
        source="gold",
    ),
    ConstrainRow(
        "co-gold-conflict",
        "conflict",
        "Can you make a day of eating that hits my protein target without going over calories?",
        (),
        {"kcal": (0.0, 100.0), "protein_g": (100.0, 200.0)},
        last_plan=(("chicken_breast", 200.0),),
        source="gold",
    ),
    ConstrainRow(
        "co-milk",
        "condition",
        "I was thinking of having a glass of milk tonight. Is that okay for me, or what should I have instead?",
        ("milk",),
        {"kcal": (350.0, 750.0), "protein_g": (15.0, 45.0)},
        food_id="milk_whole",
    ),
    ConstrainRow(
        "co-tofu",
        "condition",
        "Is tofu okay for me, or what should I have instead?",
        ("soy",),
        {"kcal": (300.0, 700.0), "protein_g": (10.0, 40.0)},
        food_id="tofu",
    ),
    ConstrainRow(
        "co-eggs",
        "condition",
        "I was thinking of having scrambled eggs tonight. Is that okay for me, or what should I have instead?",
        ("egg",),
        {"kcal": (400.0, 800.0), "protein_g": (25.0, 55.0)},
        food_id="egg",
    ),
    ConstrainRow(
        "co-salmon",
        "condition",
        "Is salmon okay for me tonight, or what should I have instead?",
        ("fish",),
        {"kcal": (450.0, 800.0), "protein_g": (25.0, 55.0)},
        food_id="salmon",
    ),
    ConstrainRow(
        "co-almonds",
        "condition",
        "I was thinking of having almonds as a snack. Is that okay for me, or what should I have instead?",
        ("tree_nut",),
        {"kcal": (300.0, 650.0), "protein_g": (10.0, 35.0)},
        food_id="almond",
    ),
    ConstrainRow(
        "co-peanuts",
        "condition",
        "Are peanuts okay for me, or what should I have instead?",
        ("peanut",),
        {"kcal": (350.0, 700.0), "protein_g": (15.0, 40.0)},
        food_id="peanut",
    ),
    ConstrainRow(
        "co-prawns",
        "condition",
        "I was thinking of having prawns tonight. Is that okay for me, or what should I have instead?",
        ("shellfish",),
        {"kcal": (400.0, 750.0), "protein_g": (20.0, 50.0)},
        food_id="shrimp",
    ),
    ConstrainRow(
        "cf-50-70",
        "conflict",
        "These calorie and protein targets look impossible together. Can you still make a plan?",
        (),
        {"kcal": (0.0, 50.0), "protein_g": (70.0, 120.0)},
        last_plan=(("chicken_breast", 200.0),),
    ),
    ConstrainRow(
        "cf-55-75",
        "conflict",
        "I need a huge amount of protein but almost no calories. What would a day of eating look like?",
        (),
        {"kcal": (0.0, 55.0), "protein_g": (75.0, 125.0)},
        last_plan=(("beef", 150.0),),
    ),
    ConstrainRow(
        "cf-60-80",
        "conflict",
        "Please build a full day that stays inside my calorie cap and still hits protein.",
        (),
        {"kcal": (0.0, 60.0), "protein_g": (80.0, 130.0)},
        last_plan=(("salmon", 150.0),),
    ),
    ConstrainRow(
        "cf-65-85",
        "conflict",
        "My protein floor is way above what the calorie ceiling can support. Can you make it work?",
        (),
        {"kcal": (0.0, 65.0), "protein_g": (85.0, 135.0)},
        last_plan=(("tuna", 165.0),),
    ),
    ConstrainRow(
        "cf-70-90",
        "conflict",
        "Can you plan meals that hit protein without blowing the tiny calorie budget?",
        (),
        {"kcal": (0.0, 70.0), "protein_g": (90.0, 140.0)},
        last_plan=(("egg", 200.0),),
    ),
    ConstrainRow(
        "cf-75-95",
        "conflict",
        "I set a very tight calorie ceiling and a high protein floor. Make a plan anyway?",
        (),
        {"kcal": (0.0, 75.0), "protein_g": (95.0, 145.0)},
        last_plan=(("chicken_breast", 150.0),),
    ),
    ConstrainRow(
        "cf-80-100",
        "conflict",
        "Is there any mix of foods that satisfies both of these windows?",
        (),
        {"kcal": (0.0, 80.0), "protein_g": (100.0, 150.0)},
        last_plan=(("greek_yogurt", 245.0),),
    ),
    ConstrainRow(
        "cf-85-105",
        "conflict",
        "Try to build a day of eating under this calorie cap that still reaches my protein target.",
        (),
        {"kcal": (0.0, 85.0), "protein_g": (105.0, 155.0)},
        last_plan=(("oats", 200.0),),
    ),
    ConstrainRow(
        "cf-90-110",
        "conflict",
        "These windows feel contradictory — protein way up, calories almost none. Submit a plan if you can.",
        (),
        {"kcal": (0.0, 90.0), "protein_g": (110.0, 160.0)},
        last_plan=(("pasta", 280.0),),
    ),
)


EVALUATE_ROWS: tuple[EvaluateRow, ...] = (
    EvaluateRow(
        "ev-gold-plan",
        "Evaluate this as my plan: 200g chicken breast, 300g rice, 150g broccoli, and 20g olive oil.",
        (
            ("chicken_breast", "200 g"),
            ("white_rice", "300 g"),
            ("broccoli", "150 g"),
            ("olive_oil", "20 g"),
        ),
        source="gold",
    ),
    EvaluateRow(
        "ev-gold-salmon",
        "Does this work as dinner: 150g salmon, a cup of rice, and 100g broccoli?",
        (
            ("salmon", "150 g"),
            ("white_rice", "a cup"),
            ("broccoli", "100 g"),
        ),
        source="gold",
    ),
    EvaluateRow(
        "ev-gold-snack",
        "Check this snack for me: a banana and 150g of Greek yogurt.",
        (
            ("banana", "a piece"),
            ("greek_yogurt", "150 g"),
        ),
        source="gold",
    ),
    EvaluateRow(
        "ev-tuna-rice",
        "Evaluate this as my plan: a can of tuna, a cup of rice, and a cup of broccoli.",
        (
            ("tuna", "a can"),
            ("white_rice", "a cup"),
            ("broccoli", "a cup"),
        ),
    ),
    EvaluateRow(
        "ev-yogurt-banana",
        "Submit this as the plan: a cup of Greek yogurt and a banana.",
        (
            ("greek_yogurt", "a cup"),
            ("banana", "a piece"),
        ),
    ),
    EvaluateRow(
        "ev-chicken-potato",
        "Evaluate this as my plan: 150 g chicken, a baked potato, and 100 g broccoli.",
        (
            ("chicken_breast", "150 g"),
            ("potato", "a piece"),
            ("broccoli", "100 g"),
        ),
    ),
    EvaluateRow(
        "ev-tofu-rice",
        "Submit this as the plan: a cup of tofu, a cup of rice, and a cup of spinach.",
        (
            ("tofu", "a cup"),
            ("white_rice", "a cup"),
            ("spinach", "a cup"),
        ),
    ),
    EvaluateRow(
        "ev-egg-oats",
        "Evaluate this as my plan: two eggs and a cup of oats.",
        (
            ("egg", "two pieces"),
            ("oats", "a cup"),
        ),
    ),
    EvaluateRow(
        "ev-salmon-spinach",
        "Does this work as dinner: 150 g salmon and a cup of spinach?",
        (
            ("salmon", "150 g"),
            ("spinach", "a cup"),
        ),
    ),
    EvaluateRow(
        "ev-beef-pasta",
        "Evaluate this as my plan: 150 g beef and a cup of pasta.",
        (
            ("beef", "150 g"),
            ("pasta", "a cup"),
        ),
    ),
    EvaluateRow(
        "ev-chicken-only",
        "Submit this as the plan: 180 g chicken.",
        (("chicken_breast", "180 g"),),
    ),
)


def _catalog_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for entry in catalog.values():
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


def _windows_unsatisfiable(windows: dict, catalog) -> bool:
    kcal_hi = float(windows.get("kcal", (0.0, 0.0))[1])
    prot_lo = float(windows.get("protein_g", (0.0, 0.0))[0])
    best = 0.0
    for entry in catalog.values():
        nutrients = entry.get("nutrients") or {}
        kcal = float(nutrients.get("kcal") or 0.0)
        protein = float(nutrients.get("protein_g") or 0.0)
        if protein <= 0:
            continue
        if kcal <= 0:
            if protein >= 1.0:
                return False
            continue
        best = max(best, protein / kcal)
    return best * kcal_hi < prot_lo


def assert_fuzzy_resolves(catalog) -> None:
    """Raise if any table row cannot be converted by the live catalog."""
    seen: set[tuple] = set()
    for row in FUZZY_ROWS:
        grams = resolve_portion(row.food_id, row.phrase, catalog)
        if grams is None:
            raise RuntimeError(f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}")
        key = fuzzy_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate fuzzy key {key}")
        seen.add(key)


def assert_leftover_rows(catalog) -> None:
    seen: set[tuple] = set()
    for row in LEFTOVER_ROWS:
        for food_id, _grams, _slot in row.ledger:
            if food_id not in catalog:
                raise RuntimeError(f"{row.seed_id} food {food_id} is not in the catalog")
        key = leftover_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate leftover key {key}")
        seen.add(key)


def assert_update_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in UPDATE_ROWS:
        for tag in row.add_allergens:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = update_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate update key {key}")
        seen.add(key)


def assert_constrain_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in CONSTRAIN_ROWS:
        if row.kind not in {"condition", "conflict"}:
            raise RuntimeError(f"{row.seed_id} has unknown kind {row.kind!r}")
        if row.kind == "condition":
            if row.food_id is None or row.food_id not in catalog:
                raise RuntimeError(f"{row.seed_id} food {row.food_id} does not resolve")
            food_tags = set(catalog[row.food_id].get("allergen_tags") or [])
            if not food_tags.intersection(row.allergies):
                raise RuntimeError(f"{row.seed_id} food does not carry a listed allergy")
            if row.windows["kcal"][1] > 800:
                raise RuntimeError(f"{row.seed_id} meal kcal ceiling exceeds 800")
        else:
            if not row.last_plan:
                raise RuntimeError(f"{row.seed_id} conflict row has no violating plan")
            if not _windows_unsatisfiable(row.windows, catalog):
                raise RuntimeError(f"{row.seed_id} windows are satisfiable")
        for tag in row.allergies:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = constrain_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate constrain key {key}")
        seen.add(key)


def assert_evaluate_rows(catalog) -> None:
    seen: set[tuple] = set()
    for row in EVALUATE_ROWS:
        for food_id, phrase in row.items:
            if resolve_portion(food_id, phrase, catalog) is None:
                raise RuntimeError(f"{row.seed_id} does not resolve {phrase!r} for {food_id}")
        key = evaluate_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate evaluate key {key}")
        seen.add(key)
