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
    "MultiItemLogRow",
    "UnitConvertRow",
    "NearSynonymRow",
    "LedgerGapRow",
    "LeftoverRow",
    "UpdateRow",
    "ConstrainRow",
    "EvaluateRow",
    "RecommendRow",
    "FUZZY_ROWS",
    "MULTI_ITEM_LOG_ROWS",
    "UNIT_CONVERT_ROWS",
    "NEAR_SYNONYM_ROWS",
    "LEDGER_GAP_ROWS",
    "LEFTOVER_ROWS",
    "UPDATE_ROWS",
    "CONSTRAIN_ROWS",
    "EVALUATE_ROWS",
    "RECOMMEND_ROWS",
    "fuzzy_key",
    "multi_item_log_key",
    "unit_convert_key",
    "near_synonym_key",
    "ledger_gap_key",
    "leftover_key",
    "update_key",
    "constrain_key",
    "evaluate_key",
    "recommend_key",
    "evaluate_windows",
    "assert_fuzzy_resolves",
    "assert_log_situation_rows",
    "assert_leftover_rows",
    "assert_update_rows",
    "assert_constrain_rows",
    "assert_evaluate_rows",
    "assert_recommend_rows",
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
class MultiItemLogRow:
    seed_id: str
    query: str
    items: tuple[tuple[str, str], ...]
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class UnitConvertRow:
    seed_id: str
    food_id: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class NearSynonymRow:
    seed_id: str
    food_id: str
    spoken: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class LedgerGapRow:
    seed_id: str
    query: str
    missing: tuple[str, str, str]
    surround: tuple[tuple[str, float, str], ...]
    source: str = "novel"


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
    remove_allergens: tuple[str, ...] = ()
    window_shifts: dict[str, float | tuple[float, float]] | None = None
    s0_allergies: tuple[str, ...] | None = None
    s0_plan_preset: dict | None = None
    set_plan_preset: dict | None = None
    source: str = "novel"


@dataclass(frozen=True)
class RecommendRow:
    seed_id: str
    query: str
    persona: str
    windows: dict[str, tuple[float, float]]
    allergies: tuple[str, ...] = ()
    plan_preset: dict | None = None
    source: str = "novel"
    occasion: str = ""


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
    mechanism: str | None = None


@dataclass(frozen=True)
class EvaluateRow:
    seed_id: str
    query: str
    items: tuple[tuple[str, str], ...]
    margin_kcal: float = 150.0
    margin_protein: float = 15.0
    source: str = "novel"
    tier: str = "gold"


def fuzzy_key(row: FuzzyRow) -> tuple:
    return ("log", "fuzzy_portion", "everyday", row.food_id, row.phrase, row.slot)


def multi_item_log_key(row: MultiItemLogRow) -> tuple:
    return ("log", "multi_item_log", "everyday", row.items, row.slot)


def unit_convert_key(row: UnitConvertRow) -> tuple:
    return ("log", "unit_convert", "everyday", row.food_id, row.phrase, row.slot)


def near_synonym_key(row: NearSynonymRow) -> tuple:
    return (
        "log",
        "near_synonym",
        "everyday",
        row.food_id,
        row.spoken,
        row.phrase,
        row.slot,
    )


def ledger_gap_key(row: LedgerGapRow) -> tuple:
    surround = tuple((food_id, slot) for food_id, _grams, slot in row.surround)
    return ("log", "ledger_gap", "everyday", row.missing, surround)


def leftover_key(row: LeftoverRow) -> tuple:
    foods = tuple((food_id, slot) for food_id, _grams, slot in row.ledger)
    return ("recommend", None, "leftover", foods, tuple(sorted(row.windows)))


def _shift_key(delta: float | tuple[float, float]) -> float | tuple[float, float]:
    if isinstance(delta, (tuple, list)):
        return tuple(float(part) for part in delta)
    return float(delta)


def update_key(row: UpdateRow) -> tuple:
    shifts = tuple(
        sorted((key, _shift_key(delta)) for key, delta in (row.window_shifts or {}).items())
    )
    preset = None
    if row.set_plan_preset:
        preset = tuple(sorted(row.set_plan_preset.items()))
    return (
        "update",
        tuple(row.add_allergens),
        tuple(row.remove_allergens),
        shifts,
        row.s0_allergies,
        preset,
    )


def constrain_key(row: ConstrainRow) -> tuple:
    windows = tuple(sorted((key, bounds) for key, bounds in row.windows.items()))
    return ("constrain", row.kind, row.food_id, row.allergies, windows, row.last_plan)


def recommend_key(row: RecommendRow) -> tuple:
    windows = tuple(sorted((key, tuple(bounds)) for key, bounds in row.windows.items()))
    preset = None
    if row.plan_preset:
        preset = tuple(sorted(row.plan_preset.items()))
    return (
        "recommend",
        row.persona,
        tuple(sorted(row.allergies)),
        windows,
        preset,
    )


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


MULTI_ITEM_LOG_ROWS: tuple[MultiItemLogRow, ...] = (
    MultiItemLogRow(
        "mi-gold-breakfast",
        "Breakfast was 60 grams of oats, a banana (110g), and 150g of Greek yogurt. Please log all of it.",
        (("oats", "60 g"), ("banana", "110 g"), ("greek_yogurt", "150 g")),
        "today-breakfast",
        source="gold",
    ),
    MultiItemLogRow(
        "mi-gold-dinner",
        "Dinner was 150g salmon, a cup of rice, and 100g broccoli. Please log all of it.",
        (("salmon", "150 g"), ("white_rice", "a cup"), ("broccoli", "100 g")),
        "today-dinner",
        source="gold",
    ),
    MultiItemLogRow(
        "mi-lunch-chicken-rice",
        "Lunch was 150 grams of chicken and a cup of rice. Please log both.",
        (("chicken_breast", "150 g"), ("white_rice", "a cup")),
        "today-lunch",
    ),
    MultiItemLogRow(
        "mi-bfast-eggs-oats-banana",
        "Breakfast was two eggs, a cup of oats, and a banana. Log all of it.",
        (("egg", "two pieces"), ("oats", "a cup"), ("banana", "a piece")),
        "today-breakfast",
    ),
    MultiItemLogRow(
        "mi-dinner-tofu-four",
        "Dinner was 160 g tofu, a cup of rice, a cup of spinach, and a teaspoon of olive oil. Please log all of it.",
        (
            ("tofu", "160 g"),
            ("white_rice", "a cup"),
            ("spinach", "a cup"),
            ("olive_oil", "a teaspoon"),
        ),
        "today-dinner",
    ),
    MultiItemLogRow(
        "mi-snack-yogurt-almonds",
        "Snack was a cup of Greek yogurt and 40 grams of almonds. Log both.",
        (("greek_yogurt", "a cup"), ("almond", "40 g")),
        "today-snack",
    ),
    MultiItemLogRow(
        "mi-lunch-tuna-broc-rice",
        "Lunch was a can of tuna, 100 g broccoli, and a cup of rice. Please log all of it.",
        (("tuna", "a can"), ("broccoli", "100 g"), ("white_rice", "a cup")),
        "today-lunch",
    ),
    MultiItemLogRow(
        "mi-dinner-beef-pasta-spin",
        "Dinner was 180 g beef, a cup of pasta, and a cup of spinach. Log all three.",
        (("beef", "180 g"), ("pasta", "a cup"), ("spinach", "a cup")),
        "today-dinner",
    ),
    MultiItemLogRow(
        "mi-bfast-milk-oats-banana-pb",
        "Breakfast was a cup of milk, 60 g oats, a banana, and a tablespoon of peanut butter. Please log all of it.",
        (
            ("milk_whole", "a cup"),
            ("oats", "60 g"),
            ("banana", "a piece"),
            ("peanut_butter", "a tablespoon"),
        ),
        "today-breakfast",
    ),
)


UNIT_CONVERT_ROWS: tuple[UnitConvertRow, ...] = (
    UnitConvertRow(
        "uc-gold-oats-2oz",
        "oats",
        "2 ounces",
        "Snack was about 2 ounces of oats. Log it for me.",
        "today-snack",
        source="gold",
    ),
    UnitConvertRow(
        "uc-chicken-3oz",
        "chicken_breast",
        "3 ounces",
        "Lunch was about 3 ounces of chicken. Please log it.",
        "today-lunch",
    ),
    UnitConvertRow(
        "uc-almond-1oz",
        "almond",
        "1 ounce",
        "Snack was about 1 ounce of almonds. Log that?",
        "today-snack",
    ),
    UnitConvertRow(
        "uc-almond-half-oz",
        "almond",
        "half an ounce",
        "I had half an ounce of almonds as a snack. Can you log it?",
        "today-snack",
    ),
    UnitConvertRow(
        "uc-tuna-4oz",
        "tuna",
        "4 oz",
        "Lunch was about 4 oz of tuna. Please log it.",
        "today-lunch",
    ),
    UnitConvertRow(
        "uc-salmon-3-5oz",
        "salmon",
        "3.5 ounces",
        "Dinner was about 3.5 ounces of salmon. Log it for me.",
        "today-dinner",
    ),
    UnitConvertRow(
        "uc-rice-1-5cups",
        "white_rice",
        "1.5 cups",
        "Dinner was 1.5 cups of rice. Please log that.",
        "today-dinner",
    ),
    UnitConvertRow(
        "uc-yogurt-quarter-cup",
        "greek_yogurt",
        "a quarter cup",
        "Snack was a quarter cup of Greek yogurt. Log it?",
        "today-snack",
    ),
)


NEAR_SYNONYM_ROWS: tuple[NearSynonymRow, ...] = (
    NearSynonymRow(
        "ns-gold-prawns",
        "shrimp",
        "prawns",
        "150 g",
        "Log the prawns I had for dinner — about 150 grams.",
        "today-dinner",
        source="gold",
    ),
    NearSynonymRow(
        "ns-oatmeal",
        "oats",
        "oatmeal",
        "a cup",
        "Breakfast was a cup of oatmeal. Please log it.",
        "today-breakfast",
    ),
    NearSynonymRow(
        "ns-bean-curd",
        "tofu",
        "bean curd",
        "a cup",
        "Lunch was a cup of bean curd. Can you log that?",
        "today-lunch",
    ),
    NearSynonymRow(
        "ns-yoghurt",
        "greek_yogurt",
        "greek yoghurt",
        "a cup",
        "Snack was a cup of greek yoghurt. Log it for me.",
        "today-snack",
    ),
    NearSynonymRow(
        "ns-spaghetti",
        "pasta",
        "spaghetti",
        "a cup",
        "Dinner was a cup of spaghetti. Please log it.",
        "today-dinner",
    ),
    NearSynonymRow(
        "ns-steamed-rice",
        "white_rice",
        "steamed rice",
        "a cup",
        "Lunch was a cup of steamed rice. Log that?",
        "today-lunch",
    ),
    NearSynonymRow(
        "ns-evoo",
        "olive_oil",
        "evoo",
        "a tablespoon",
        "I put a tablespoon of evoo on lunch. Please log it.",
        "today-lunch",
    ),
)


LEDGER_GAP_ROWS: tuple[LedgerGapRow, ...] = (
    LedgerGapRow(
        "lg-gold-lunch",
        "I forgot to log lunch — 150g of chicken breast. Add just that.",
        ("chicken_breast", "150 g", "today-lunch"),
        (
            ("banana", 100.0, "today-breakfast"),
            ("white_rice", 200.0, "today-dinner"),
        ),
        source="gold",
    ),
    LedgerGapRow(
        "lg-miss-breakfast",
        "I forgot breakfast — 80 g of oats. Add just that.",
        ("oats", "80 g", "today-breakfast"),
        (
            ("chicken_breast", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-dinner"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-dinner",
        "Dinner never made it onto the ledger — 200 g of pasta. Add just that.",
        ("pasta", "200 g", "today-dinner"),
        (
            ("oats", 80.0, "today-breakfast"),
            ("chicken_breast", 150.0, "today-lunch"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-snack",
        "I skipped logging my snack — a cup of Greek yogurt. Add just that.",
        ("greek_yogurt", "a cup", "today-snack"),
        (
            ("banana", 118.0, "today-breakfast"),
            ("chicken_breast", 150.0, "today-lunch"),
            ("white_rice", 200.0, "today-dinner"),
        ),
    ),
    LedgerGapRow(
        "lg-miss-lunch-three",
        "Lunch is the hole — a can of tuna. Add just that.",
        ("tuna", "a can", "today-lunch"),
        (
            ("oats", 80.0, "today-breakfast"),
            ("apple", 182.0, "today-snack"),
            ("salmon", 150.0, "today-dinner"),
        ),
    ),
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
    UpdateRow(
        "up-rm-peanut",
        "I got tested — I'm not actually allergic to peanuts. Take that off my list.",
        remove_allergens=("peanut",),
    ),
    UpdateRow(
        "up-rm-shellfish",
        "I got tested — I'm not actually allergic to shellfish. Remove it.",
        remove_allergens=("shellfish",),
        s0_allergies=("peanut", "shellfish"),
    ),
    UpdateRow(
        "up-rm-milk",
        "The milk allergy was a false alarm. I'm not actually allergic to milk — remove it.",
        remove_allergens=("milk",),
        s0_allergies=("milk",),
    ),
    UpdateRow(
        "up-rm-egg",
        "I got tested — I'm not actually allergic to eggs. Take that off my allergies.",
        remove_allergens=("egg",),
        s0_allergies=("peanut", "egg"),
    ),
    UpdateRow(
        "up-floor-protein-20",
        "Raise just my protein floor by 20 grams. Leave the ceiling alone.",
        window_shifts={"protein_g": (20.0, 0.0)},
    ),
    UpdateRow(
        "up-floor-protein-30",
        "Bump the lower end of my protein range up 30 grams. Don't move the top.",
        window_shifts={"protein_g": (30.0, 0.0)},
    ),
    UpdateRow(
        "up-ceil-kcal-200",
        "Bring the calorie ceiling down by 200. Leave the floor where it is.",
        window_shifts={"kcal": (0.0, -200.0)},
    ),
    UpdateRow(
        "up-ceil-kcal-300",
        "Take 300 off the top of my calorie range. Don't touch the bottom.",
        window_shifts={"kcal": (0.0, -300.0)},
    ),
    UpdateRow(
        "up-floor-kcal-200",
        "Raise just the lower end of my calorie range by 200. Leave the ceiling alone.",
        window_shifts={"kcal": (200.0, 0.0)},
    ),
    UpdateRow(
        "up-ceil-protein-20",
        "Bring the upper end of my protein range down 20 grams. Leave the floor alone.",
        window_shifts={"protein_g": (0.0, -20.0)},
    ),
    UpdateRow(
        "up-two-kcal-200-prot-20",
        "Raise my calorie range by 200 at both ends and my protein range by 20 at both ends.",
        window_shifts={"kcal": 200.0, "protein_g": 20.0},
    ),
    UpdateRow(
        "up-two-kcal-300-prot-30",
        "Take 300 off both ends of my calorie range and raise protein 30 grams at both ends.",
        window_shifts={"kcal": -300.0, "protein_g": 30.0},
    ),
    UpdateRow(
        "up-two-kcal-200-prot-30",
        "Move my calorie range down 200 at both ends and raise protein 30 grams at both ends.",
        window_shifts={"kcal": -200.0, "protein_g": 30.0},
    ),
    UpdateRow(
        "up-add-milk-egg",
        "I reacted to milk and eggs. Add both to my allergies.",
        add_allergens=("egg", "milk"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-add-fish-treenut",
        "I reacted to salmon and almonds. Add both of those allergies.",
        add_allergens=("fish", "tree_nut"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-add-soy-wheat",
        "I reacted to tofu and pasta. Add both to my allergies.",
        add_allergens=("soy", "wheat"),
        s0_allergies=(),
    ),
    UpdateRow(
        "up-preset-cut-muscle",
        "I'm switching from a cut to a muscle plan. Update my plan.",
        s0_plan_preset={"goal": "cut"},
        set_plan_preset={"goal": "muscle"},
    ),
    UpdateRow(
        "up-preset-muscle-cut",
        "I was on a muscle plan; now I want to cut. Change my plan.",
        s0_plan_preset={"goal": "muscle"},
        set_plan_preset={"goal": "cut"},
    ),
)


# Gold-shaped first so the factory still covers the calibration shapes.
RECOMMEND_ROWS: tuple[RecommendRow, ...] = (
    RecommendRow(
        "rec-safe-001",
        "Can you put together a meal that works with my targets and allergies?",
        "everyday",
        {"kcal": (400.0, 800.0), "protein_g": (25.0, 55.0)},
        allergies=("peanut", "shellfish"),
        source="gold",
        occasion="dinner",
    ),
    RecommendRow(
        "rec-cut-001",
        "I'm cutting and don't want to blow dinner. What should I eat?",
        "cut",
        {"kcal": (400.0, 600.0), "protein_g": (35.0, 55.0)},
        plan_preset={"goal": "cut"},
        source="gold",
        occasion="dinner",
    ),
    RecommendRow(
        "rec-gym-001",
        "Just finished lifting — what should I eat?",
        "gym",
        {"kcal": (400.0, 750.0), "protein_g": (35.0, 65.0)},
        plan_preset={"goal": "muscle"},
        source="gold",
        occasion="post-workout",
    ),
    RecommendRow(
        "rec-flex-001",
        "Tonight I want something more filling. Any ideas?",
        "flex",
        {"kcal": (700.0, 1200.0), "protein_g": (20.0, 80.0)},
        allergies=("peanut",),
        plan_preset={"flex_day": True},
        source="gold",
        occasion="dinner",
    ),
    RecommendRow(
        "rec-htn-001",
        "What's for dinner?",
        "htn",
        {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0), "sodium_mg": (0.0, 400.0)},
        source="gold",
        occasion="dinner",
    ),
    RecommendRow(
        "rec-snack-001",
        "I need a snack.",
        "everyday",
        {"kcal": (80.0, 250.0), "protein_g": (8.0, 25.0)},
        allergies=("peanut",),
        source="gold",
        occasion="snack",
    ),
    RecommendRow(
        "rec-bfast-wide",
        "What's a simple breakfast I can actually make?",
        "everyday",
        {"kcal": (350.0, 650.0), "protein_g": (12.0, 40.0)},
        occasion="breakfast",
    ),
    RecommendRow(
        "rec-lunch-milk",
        "I have to skip dairy. What should lunch look like?",
        "everyday",
        {"kcal": (450.0, 750.0), "protein_g": (25.0, 55.0)},
        allergies=("milk",),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-dinner-egg",
        "Eggs are off the table for me. What can I have tonight?",
        "everyday",
        {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)},
        allergies=("egg",),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-lunch-fish",
        "No fish, please. What should I eat for lunch?",
        "everyday",
        {"kcal": (450.0, 700.0), "protein_g": (30.0, 55.0)},
        allergies=("fish",),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-dinner-soy",
        "Soy is a no for me. What should dinner be?",
        "everyday",
        {"kcal": (400.0, 750.0), "protein_g": (20.0, 50.0)},
        allergies=("soy",),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-snack-treenut",
        "I need a mid-afternoon bite and I can't do tree nuts.",
        "everyday",
        {"kcal": (100.0, 280.0), "protein_g": (8.0, 22.0)},
        allergies=("tree_nut",),
        occasion="snack",
    ),
    RecommendRow(
        "rec-lunch-wheat",
        "Wheat is out. What should I pack for lunch?",
        "everyday",
        {"kcal": (450.0, 780.0), "protein_g": (25.0, 50.0)},
        allergies=("wheat",),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-dinner-gluten",
        "Keep gluten away from dinner. What should I eat?",
        "everyday",
        {"kcal": (400.0, 720.0), "protein_g": (22.0, 48.0)},
        allergies=("gluten",),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-bfast-wheat-gluten",
        "Bread is a problem — wheat and gluten both. What's breakfast?",
        "everyday",
        {"kcal": (320.0, 580.0), "protein_g": (15.0, 40.0)},
        allergies=("wheat", "gluten"),
        occasion="breakfast",
    ),
    RecommendRow(
        "rec-lunch-milk-egg",
        "No dairy, no eggs. What works for lunch?",
        "everyday",
        {"kcal": (450.0, 760.0), "protein_g": (25.0, 52.0)},
        allergies=("egg", "milk"),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-dinner-fish-shell",
        "Seafood of any kind is a bad idea. What's dinner?",
        "everyday",
        {"kcal": (400.0, 780.0), "protein_g": (28.0, 55.0)},
        allergies=("fish", "shellfish"),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-snack-peanut-soy-tn",
        "Peanuts, soy, and tree nuts are all out. I just need a snack.",
        "everyday",
        {"kcal": (90.0, 240.0), "protein_g": (10.0, 24.0)},
        allergies=("peanut", "soy", "tree_nut"),
        occasion="snack",
    ),
    RecommendRow(
        "rec-dinner-milk-wheat-soy",
        "Dairy, wheat, and soy all bother me. What should I eat tonight?",
        "everyday",
        {"kcal": (420.0, 800.0), "protein_g": (22.0, 50.0)},
        allergies=("milk", "soy", "wheat"),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-lunch-tight",
        "I only have room for a small lunch. What should I eat?",
        "everyday",
        {"kcal": (480.0, 560.0), "protein_g": (30.0, 42.0)},
        occasion="lunch",
    ),
    RecommendRow(
        "rec-dinner-sodium",
        "I want dinner that isn't a salt bomb. What should I eat?",
        "everyday",
        {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0), "sodium_mg": (0.0, 500.0)},
        allergies=("peanut",),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-bfast-fiber",
        "I want breakfast that actually has some fibre. Ideas?",
        "everyday",
        {"kcal": (350.0, 600.0), "protein_g": (15.0, 40.0), "fiber_g": (6.0, 20.0)},
        occasion="breakfast",
    ),
    RecommendRow(
        "rec-lunch-fat",
        "Keep lunch on the lean side — no shellfish either. What should I eat?",
        "everyday",
        {"kcal": (450.0, 750.0), "protein_g": (25.0, 50.0), "fat_g": (0.0, 30.0)},
        allergies=("shellfish",),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-snack-fiber",
        "A fibre-ish snack, and skip eggs. What have you got?",
        "everyday",
        {"kcal": (120.0, 280.0), "protein_g": (10.0, 25.0), "fiber_g": (4.0, 12.0)},
        allergies=("egg",),
        occasion="snack",
    ),
    RecommendRow(
        "rec-dinner-carb",
        "I want a carb-forward dinner. What should I eat?",
        "everyday",
        {"kcal": (500.0, 800.0), "protein_g": (20.0, 45.0), "carb_g": (40.0, 90.0)},
        occasion="dinner",
    ),
    RecommendRow(
        "rec-cut-lunch-tight",
        "I'm cutting and lunch has to stay small. What should I eat?",
        "cut",
        {"kcal": (380.0, 520.0), "protein_g": (38.0, 52.0)},
        plan_preset={"goal": "cut"},
        occasion="lunch",
    ),
    RecommendRow(
        "rec-cut-milk",
        "Cutting, and dairy is out. What's dinner?",
        "cut",
        {"kcal": (400.0, 580.0), "protein_g": (35.0, 50.0)},
        allergies=("milk",),
        plan_preset={"goal": "cut"},
        occasion="dinner",
    ),
    RecommendRow(
        "rec-cut-fiber",
        "I'm cutting and I'd like lunch with some fibre. Wheat is a no.",
        "cut",
        {"kcal": (400.0, 600.0), "protein_g": (35.0, 55.0), "fiber_g": (5.0, 18.0)},
        allergies=("wheat",),
        plan_preset={"goal": "cut"},
        occasion="lunch",
    ),
    RecommendRow(
        "rec-gym-peanut",
        "Just trained and I can't do peanuts. What should I eat?",
        "gym",
        {"kcal": (450.0, 800.0), "protein_g": (40.0, 70.0)},
        allergies=("peanut",),
        plan_preset={"goal": "muscle"},
        occasion="post-workout",
    ),
    RecommendRow(
        "rec-gym-egg-milk",
        "Need dinner after training — no eggs, no dairy.",
        "gym",
        {"kcal": (420.0, 760.0), "protein_g": (38.0, 68.0)},
        allergies=("egg", "milk"),
        plan_preset={"goal": "muscle"},
        occasion="dinner",
    ),
    RecommendRow(
        "rec-gym-sodium",
        "Post-lift meal that isn't swimming in salt. What should I eat?",
        "gym",
        {"kcal": (400.0, 750.0), "protein_g": (35.0, 65.0), "sodium_mg": (0.0, 450.0)},
        plan_preset={"goal": "muscle"},
        occasion="post-workout",
    ),
    RecommendRow(
        "rec-flex-lunch",
        "I'm starving and lunch can be a bigger plate than usual.",
        "flex",
        {"kcal": (750.0, 1250.0), "protein_g": (25.0, 85.0)},
        plan_preset={"flex_day": True},
        occasion="lunch",
    ),
    RecommendRow(
        "rec-flex-fish",
        "Flex night, but skip the fish. What should I eat?",
        "flex",
        {"kcal": (700.0, 1150.0), "protein_g": (20.0, 75.0)},
        allergies=("fish",),
        plan_preset={"flex_day": True},
        occasion="dinner",
    ),
    RecommendRow(
        "rec-flex-fat",
        "I can go bigger tonight, just not with tree nuts, and keep fat in check.",
        "flex",
        {"kcal": (720.0, 1180.0), "protein_g": (22.0, 80.0), "fat_g": (0.0, 55.0)},
        allergies=("tree_nut",),
        plan_preset={"flex_day": True},
        occasion="dinner",
    ),
    RecommendRow(
        "rec-htn-lunch",
        "What's a low-salt lunch? Peanuts are out too.",
        "htn",
        {"kcal": (400.0, 750.0), "protein_g": (22.0, 48.0), "sodium_mg": (0.0, 350.0)},
        allergies=("peanut",),
        occasion="lunch",
    ),
    RecommendRow(
        "rec-htn-milk",
        "Dinner, keep the salt down, and I can't do dairy.",
        "htn",
        {"kcal": (380.0, 720.0), "protein_g": (20.0, 50.0), "sodium_mg": (0.0, 380.0)},
        allergies=("milk",),
        occasion="dinner",
    ),
    RecommendRow(
        "rec-htn-fiber",
        "A breakfast that isn't salty and has some fibre in it?",
        "htn",
        {
            "kcal": (400.0, 800.0),
            "protein_g": (20.0, 50.0),
            "sodium_mg": (0.0, 420.0),
            "fiber_g": (5.0, 16.0),
        },
        occasion="breakfast",
    ),
    RecommendRow(
        "rec-bfast-shellfish",
        "Shellfish is a no. What's breakfast?",
        "everyday",
        {"kcal": (300.0, 550.0), "protein_g": (14.0, 38.0)},
        allergies=("shellfish",),
        occasion="breakfast",
    ),
    RecommendRow(
        "rec-snack-soy",
        "Quick snack, and keep soy out of it.",
        "everyday",
        {"kcal": (100.0, 260.0), "protein_g": (8.0, 22.0)},
        allergies=("soy",),
        occasion="snack",
    ),
    RecommendRow(
        "rec-dinner-fat-ceil",
        "Dinner that isn't greasy. What should I eat?",
        "everyday",
        {"kcal": (400.0, 700.0), "protein_g": (22.0, 50.0), "fat_g": (0.0, 25.0)},
        occasion="dinner",
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
        "co-soy-milk",
        "condition",
        "I was thinking of having a glass of soy milk tonight. Is that okay for me, or what should I have instead?",
        ("soy",),
        {"kcal": (350.0, 720.0), "protein_g": (12.0, 42.0)},
        food_id="soy_milk",
    ),
    ConstrainRow(
        "co-cheddar",
        "condition",
        "I was thinking of putting cheddar on dinner. Is that okay for me, or what should I have instead?",
        ("milk",),
        {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)},
        food_id="cheddar",
    ),
    ConstrainRow(
        "co-yogurt",
        "condition",
        "Is Greek yogurt a good snack for me, or should I pick something else?",
        ("milk",),
        {"kcal": (300.0, 650.0), "protein_g": (12.0, 40.0)},
        food_id="greek_yogurt",
    ),
    ConstrainRow(
        "co-tuna",
        "condition",
        "Would a tuna plate work for lunch, or what should I have instead?",
        ("fish",),
        {"kcal": (400.0, 750.0), "protein_g": (20.0, 50.0)},
        food_id="tuna",
    ),
    ConstrainRow(
        "co-pasta",
        "condition",
        "I was craving pasta tonight. Is that okay for me, or what should I have instead?",
        ("wheat",),
        {"kcal": (400.0, 800.0), "protein_g": (20.0, 50.0)},
        food_id="pasta",
    ),
    ConstrainRow(
        "co-bread",
        "condition",
        "Can I have whole wheat bread with dinner, or what should I have instead?",
        ("gluten",),
        {"kcal": (350.0, 700.0), "protein_g": (15.0, 45.0)},
        food_id="whole_wheat_bread",
    ),
    ConstrainRow(
        "co-soy-sauce",
        "condition",
        "Is it alright if I cook with soy sauce tonight, or what should I have instead?",
        ("soy",),
        {"kcal": (400.0, 780.0), "protein_g": (20.0, 50.0)},
        food_id="2707442",
    ),
    ConstrainRow(
        "co-crab",
        "condition",
        "I was looking at crab for dinner. Is that okay for me, or what should I have instead?",
        ("shellfish",),
        {"kcal": (400.0, 800.0), "protein_g": (25.0, 55.0)},
        food_id="2706344",
    ),
    ConstrainRow(
        "co-cashew-butter",
        "condition",
        "Is cashew butter okay on breakfast, or what should I have instead?",
        ("tree_nut",),
        {"kcal": (300.0, 650.0), "protein_g": (10.0, 40.0)},
        food_id="2707536",
    ),
    ConstrainRow(
        "co-wheat-bran",
        "condition",
        "I was thinking of adding wheat bran at breakfast. Is that okay for me, or what should I have instead?",
        ("wheat",),
        {"kcal": (350.0, 720.0), "protein_g": (15.0, 42.0)},
        food_id="2708488",
    ),
    ConstrainRow(
        "co-cream-cheese",
        "condition",
        "I was going to spread cream cheese, regular, plain on something. Is that okay for me, or what should I have instead?",
        ("milk",),
        {"kcal": (320.0, 700.0), "protein_g": (12.0, 40.0)},
        food_id="2705760",
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
    ConstrainRow(
        "cf-near-200-56",
        "conflict",
        "Can you put together something around 200 calories that still hits my protein target?",
        (),
        {"kcal": (0.0, 200.0), "protein_g": (56.0, 90.0)},
        last_plan=(("chicken_breast", 200.0),),
    ),
    ConstrainRow(
        "cf-near-400-111",
        "conflict",
        "I only have a 400 calorie budget left. Can you still make a high-protein meal?",
        (),
        {"kcal": (0.0, 400.0), "protein_g": (111.0, 150.0)},
        last_plan=(("salmon", 150.0),),
    ),
    ConstrainRow(
        "cf-near-800-221",
        "conflict",
        "Build me a day of eating under 800 calories that hits my protein floor.",
        (),
        {"kcal": (0.0, 800.0), "protein_g": (221.0, 300.0)},
        last_plan=(("greek_yogurt", 245.0),),
    ),
    ConstrainRow(
        "cf-fib-200-90",
        "conflict",
        "I want a huge amount of fibre without going over this calorie ceiling. Can you make it work?",
        (),
        {"kcal": (0.0, 200.0), "fiber_g": (90.0, 200.0)},
        last_plan=(("oats", 200.0),),
        mechanism="other_pair",
    ),
    ConstrainRow(
        "cf-fib-150-80",
        "conflict",
        "Is there any mix of foods that hits this fibre floor inside such a small calorie budget?",
        (),
        {"kcal": (0.0, 150.0), "fiber_g": (80.0, 160.0)},
        last_plan=(("black_beans", 200.0),),
        mechanism="other_pair",
    ),
    ConstrainRow(
        "cf-fat-400-55",
        "conflict",
        "I need more fat than this calorie cap can possibly hold. Submit a plan if you can.",
        (),
        {"kcal": (0.0, 400.0), "fat_g": (55.0, 100.0)},
        last_plan=(("olive_oil", 50.0),),
        mechanism="other_pair",
    ),
    ConstrainRow(
        "cf-fat-600-82",
        "conflict",
        "These fat and calorie windows feel like they fight each other. Can you still make a plan?",
        (),
        {"kcal": (0.0, 600.0), "fat_g": (82.0, 140.0)},
        last_plan=(("peanut_butter", 100.0),),
        mechanism="other_pair",
    ),
    ConstrainRow(
        "cf-fib-carb-40-45",
        "conflict",
        "I want more fibre than the carb ceiling can support. What would a day of eating look like?",
        (),
        {"carb_g": (0.0, 40.0), "fiber_g": (45.0, 80.0)},
        last_plan=(("broccoli", 200.0),),
        mechanism="other_pair",
    ),
    ConstrainRow(
        "cf-near-250-70",
        "conflict",
        "Can you put together something around 250 calories that still hits my protein target?",
        (),
        {"kcal": (0.0, 250.0), "protein_g": (70.0, 110.0)},
        last_plan=(("chicken_breast", 180.0),),
        mechanism="near_miss",
    ),
    ConstrainRow(
        "cf-near-350-97",
        "conflict",
        "I only have a 350 calorie budget left. Can you still make a high-protein meal?",
        (),
        {"kcal": (0.0, 350.0), "protein_g": (97.0, 140.0)},
        last_plan=(("tuna", 165.0),),
        mechanism="near_miss",
    ),
    ConstrainRow(
        "cf-near-180-50",
        "conflict",
        "Fifty grams of protein in a very small calorie box. Make a plan anyway?",
        (),
        {"kcal": (0.0, 180.0), "protein_g": (50.0, 80.0)},
        last_plan=(("egg", 200.0),),
        mechanism="near_miss",
    ),
    ConstrainRow(
        "cf-near-fib-250-90",
        "conflict",
        "Can you hit this fibre target without going over about 250 calories?",
        (),
        {"kcal": (0.0, 250.0), "fiber_g": (90.0, 150.0)},
        last_plan=(("oats", 150.0),),
        mechanism="near_miss",
    ),
    ConstrainRow(
        "cf-near-fat-500-67",
        "conflict",
        "I need a lot of fat in a 500 calorie budget. Is there any mix that works?",
        (),
        {"kcal": (0.0, 500.0), "fat_g": (67.0, 120.0)},
        last_plan=(("olive_oil", 40.0),),
        mechanism="near_miss",
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
    EvaluateRow(
        "ev-single-tofu-g",
        "Evaluate this as a light lunch: 160 g of tofu.",
        (("tofu", "160 g"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-oats-cup",
        "Does this work as breakfast: a cup of oats?",
        (("oats", "a cup"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-potato-piece",
        "Check this for me: a baked potato.",
        (("potato", "a piece"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-tuna-can",
        "Submit this as the plan: a can of tuna.",
        (("tuna", "a can"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-cheddar-slice",
        "Evaluate this as a snack: a slice of cheddar.",
        (("cheddar", "a slice"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-pb-tbsp",
        "Check this snack for me: a tablespoon of peanut butter.",
        (("peanut_butter", "a tablespoon"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-single-almond-oz",
        "Does this work as a late snack: about 2 ounces of almonds?",
        (("almond", "2 ounces"),),
        tier="single",
    ),
    EvaluateRow(
        "ev-pair-chicken-rice",
        "Evaluate this as lunch: 150 g chicken and a cup of rice.",
        (("chicken_breast", "150 g"), ("white_rice", "a cup")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-banana-pb",
        "Does this work as breakfast: a banana and a tablespoon of peanut butter?",
        (("banana", "a piece"), ("peanut_butter", "a tablespoon")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-cheddar-apple",
        "Check this snack for me: a slice of cheddar and an apple.",
        (("cheddar", "a slice"), ("apple", "a piece")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-tuna-spinach",
        "Check this as a light lunch: a can of tuna and a cup of spinach.",
        (("tuna", "a can"), ("spinach", "a cup")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-potato-broccoli",
        "Does this work as a light dinner: a baked potato and a cup of broccoli?",
        (("potato", "a piece"), ("broccoli", "a cup")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-oats-oz-banana",
        "I'm thinking of about 2 ounces of oats and a banana after the gym. Does that work?",
        (("oats", "2 ounces"), ("banana", "a piece")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-avocado-egg",
        "Does this work as brunch: half a cup of avocado and two eggs?",
        (("avocado", "half a cup"), ("egg", "two pieces")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-tofu-spinach",
        "Evaluate this as a light lunch: 150 g tofu and a cup of spinach.",
        (("tofu", "150 g"), ("spinach", "a cup")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-yogurt-apple",
        "Check this snack for me: a cup of Greek yogurt and an apple.",
        (("greek_yogurt", "a cup"), ("apple", "a piece")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-potato-oil",
        "Late snack idea: a baked potato with a tablespoon of olive oil. Evaluate that as the plan.",
        (("potato", "a piece"), ("olive_oil", "a tablespoon")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-beef-pasta",
        "Does this work as dinner: 120 g beef and a cup of pasta?",
        (("beef", "120 g"), ("pasta", "a cup")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-pair-milk-oats-oz",
        "Evaluate this as breakfast: a cup of milk and about 2 ounces of oats.",
        (("milk_whole", "a cup"), ("oats", "2 ounces")),
        tier="pair",
    ),
    EvaluateRow(
        "ev-tri-chicken-rice-broc",
        "Evaluate this as dinner: 180 g chicken, a cup of rice, and a cup of broccoli.",
        (
            ("chicken_breast", "180 g"),
            ("white_rice", "a cup"),
            ("broccoli", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-eggs-oats-banana",
        "Does this work as breakfast: two eggs, a cup of oats, and a banana?",
        (
            ("egg", "two pieces"),
            ("oats", "a cup"),
            ("banana", "a piece"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-tuna-potato-spin",
        "Check this lunch for me: a can of tuna, a baked potato, and a cup of spinach.",
        (
            ("tuna", "a can"),
            ("potato", "a piece"),
            ("spinach", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-beef-pasta-spin",
        "Submit this as dinner: 160 g beef, a cup of pasta, and a cup of spinach.",
        (
            ("beef", "160 g"),
            ("pasta", "a cup"),
            ("spinach", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-salmon-potato-broc",
        "Does this work as dinner: 180 g salmon, a baked potato, and a cup of broccoli?",
        (
            ("salmon", "180 g"),
            ("potato", "a piece"),
            ("broccoli", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-yogurt-banana-apple",
        "Check this snack plate for me: a cup of yogurt, a banana, and a slice of apple.",
        (
            ("greek_yogurt", "a cup"),
            ("banana", "a piece"),
            ("apple", "a slice"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-chicken-spin-rice",
        "Evaluate this as lunch: 120 g chicken, a cup of spinach, and a cup of rice.",
        (
            ("chicken_breast", "120 g"),
            ("spinach", "a cup"),
            ("white_rice", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-shrimp-rice-broc",
        "Does this work as dinner: 150 g shrimp, a cup of rice, and a cup of broccoli?",
        (
            ("shrimp", "150 g"),
            ("white_rice", "a cup"),
            ("broccoli", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-pb-banana-oats",
        "Here's breakfast: a tablespoon of peanut butter, a banana, and a cup of oats. Evaluate that as the plan.",
        (
            ("peanut_butter", "a tablespoon"),
            ("banana", "a piece"),
            ("oats", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-cheddar-apple-yogurt",
        "Check this snack plate for me: a slice of cheddar, an apple, and a cup of yogurt.",
        (
            ("cheddar", "a slice"),
            ("apple", "a piece"),
            ("greek_yogurt", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-avocado-eggs-spin",
        "Does this work as brunch: a cup of avocado, two eggs, and a cup of spinach?",
        (
            ("avocado", "a cup"),
            ("egg", "two pieces"),
            ("spinach", "a cup"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-tri-milk-oats-banana",
        "Submit this as breakfast: a cup of milk, a cup of oats, and a banana.",
        (
            ("milk_whole", "a cup"),
            ("oats", "a cup"),
            ("banana", "a piece"),
        ),
        tier="triple",
    ),
    EvaluateRow(
        "ev-long-chicken-rice-broc-oil",
        "Evaluate this as dinner: 160 g chicken, a cup of rice, a cup of broccoli, and a tablespoon of olive oil.",
        (
            ("chicken_breast", "160 g"),
            ("white_rice", "a cup"),
            ("broccoli", "a cup"),
            ("olive_oil", "a tablespoon"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-long-oats-milk-banana-pb",
        "Does this work as breakfast: a cup of oats, a cup of milk, a banana, and a tablespoon of peanut butter?",
        (
            ("oats", "a cup"),
            ("milk_whole", "a cup"),
            ("banana", "a piece"),
            ("peanut_butter", "a tablespoon"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-long-salmon-rice-spin-avo",
        "Check this dinner for me: 150 g salmon, a cup of rice, a cup of spinach, and a slice of avocado.",
        (
            ("salmon", "150 g"),
            ("white_rice", "a cup"),
            ("spinach", "a cup"),
            ("avocado", "a slice"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-long-beef-pasta-broc-oil",
        "Submit this as dinner: 150 g beef, a cup of pasta, a cup of broccoli, and a tablespoon of olive oil.",
        (
            ("beef", "150 g"),
            ("pasta", "a cup"),
            ("broccoli", "a cup"),
            ("olive_oil", "a tablespoon"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-long-tofu-rice-veg-oil",
        "Evaluate this as a vegetarian dinner: a cup of tofu, a cup of rice, a cup of broccoli, a cup of spinach, and a teaspoon of olive oil.",
        (
            ("tofu", "a cup"),
            ("white_rice", "a cup"),
            ("broccoli", "a cup"),
            ("spinach", "a cup"),
            ("olive_oil", "a teaspoon"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-long-chicken-potato-fixings",
        "Does this work as lunch: 150 g chicken, a baked potato, a cup of broccoli, a slice of cheddar, and a tablespoon of olive oil?",
        (
            ("chicken_breast", "150 g"),
            ("potato", "a piece"),
            ("broccoli", "a cup"),
            ("cheddar", "a slice"),
            ("olive_oil", "a tablespoon"),
        ),
        tier="long",
    ),
    EvaluateRow(
        "ev-fg-salmon",
        "Evaluate this as my plan: 120 g salmon.",
        (("salmon", "120 g"),),
        tier="explicit_grams",
    ),
    EvaluateRow(
        "ev-fg-beef",
        "Does this work as dinner: 180 g of beef?",
        (("beef", "180 g"),),
        tier="explicit_grams",
    ),
    EvaluateRow(
        "ev-eg-beef-rice",
        "Does this work as a light dinner: 100 g beef and a cup of rice?",
        (("beef", "100 g"), ("white_rice", "a cup")),
        tier="explicit_grams",
    ),
    EvaluateRow(
        "ev-fg-salmon-beef",
        "Submit this as dinner: 140 g salmon and 80 g beef.",
        (("salmon", "140 g"), ("beef", "80 g")),
        tier="explicit_grams",
    ),
    EvaluateRow(
        "ev-syn-prawns",
        "Does this work as dinner: 150 g of prawns?",
        (("shrimp", "150 g"),),
        tier="synonym",
    ),
    EvaluateRow(
        "ev-syn-oatmeal-banana",
        "Evaluate this as breakfast: a cup of oatmeal and a banana.",
        (("oats", "a cup"), ("banana", "a piece")),
        tier="synonym",
    ),
    EvaluateRow(
        "ev-syn-yogurt-orange",
        "Check this snack for me: a cup of plain yogurt and a cup of orange segments.",
        (("greek_yogurt", "a cup"), ("orange", "a cup")),
        tier="synonym",
    ),
)


def _catalog_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for entry in catalog.values():
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


_BANNED_LOG_PAIRS = frozenset(
    {("whole_wheat_bread", "a slice"), ("broccoli", "a piece")}
)


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


def assert_log_situation_rows(catalog) -> None:
    """Raise if a multi-item / unit / synonym / gap row cannot be realized."""
    seen: set[tuple] = set()
    for row in MULTI_ITEM_LOG_ROWS:
        if not (2 <= len(row.items) <= 4):
            raise RuntimeError(f"{row.seed_id} must log 2-4 items")
        for food_id, phrase in row.items:
            if (food_id, phrase) in _BANNED_LOG_PAIRS:
                raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
            if resolve_portion(food_id, phrase, catalog) is None:
                raise RuntimeError(
                    f"{row.seed_id} does not resolve {phrase!r} for {food_id}"
                )
        key = multi_item_log_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in UNIT_CONVERT_ROWS:
        if (row.food_id, row.phrase) in _BANNED_LOG_PAIRS:
            raise RuntimeError(f"{row.seed_id} uses banned pair {row.food_id} {row.phrase!r}")
        if resolve_portion(row.food_id, row.phrase, catalog) is None:
            raise RuntimeError(
                f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}"
            )
        key = unit_convert_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in NEAR_SYNONYM_ROWS:
        if row.food_id not in catalog:
            raise RuntimeError(f"{row.seed_id} food {row.food_id} is not in the catalog")
        aliases = {str(alias).lower() for alias in (catalog[row.food_id].get("aliases") or [])}
        if row.spoken.lower() not in aliases:
            raise RuntimeError(
                f"{row.seed_id} spoken {row.spoken!r} is not an alias of {row.food_id}"
            )
        if row.spoken.lower() == row.food_id.lower():
            raise RuntimeError(f"{row.seed_id} spoken name is the slug")
        if resolve_portion(row.food_id, row.phrase, catalog) is None:
            raise RuntimeError(
                f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}"
            )
        key = near_synonym_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in LEDGER_GAP_ROWS:
        food_id, phrase, slot = row.missing
        if (food_id, phrase) in _BANNED_LOG_PAIRS:
            raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
        if resolve_portion(food_id, phrase, catalog) is None:
            raise RuntimeError(f"{row.seed_id} does not resolve {phrase!r} for {food_id}")
        surround_slots = {eaten_at for _food, _grams, eaten_at in row.surround}
        if slot in surround_slots:
            raise RuntimeError(f"{row.seed_id} missing slot {slot} is already in S0")
        if not row.surround:
            raise RuntimeError(f"{row.seed_id} has no surrounding ledger rows")
        for surround_food, _grams, _eaten_at in row.surround:
            if surround_food not in catalog:
                raise RuntimeError(f"{row.seed_id} surround food {surround_food} is not in the catalog")
        key = ledger_gap_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
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
        for tag in (*row.add_allergens, *row.remove_allergens):
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
            from nutrienv.bench.validator import _any_pair_unsatisfiable

            if not _any_pair_unsatisfiable(row.windows, catalog, row.allergies):
                raise RuntimeError(f"{row.seed_id} windows are satisfiable")
        for tag in row.allergies:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = constrain_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate constrain key {key}")
        seen.add(key)


_BANNED_EVALUATE_PAIRS = frozenset(
    {("whole_wheat_bread", "a slice"), ("broccoli", "a piece")}
)


def assert_evaluate_rows(catalog) -> None:
    seen: set[tuple] = set()
    for row in EVALUATE_ROWS:
        for food_id, phrase in row.items:
            if (food_id, phrase) in _BANNED_EVALUATE_PAIRS:
                raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
            if resolve_portion(food_id, phrase, catalog) is None:
                raise RuntimeError(f"{row.seed_id} does not resolve {phrase!r} for {food_id}")
        key = evaluate_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate evaluate key {key}")
        seen.add(key)


def assert_recommend_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in RECOMMEND_ROWS:
        if row.persona == "leftover":
            raise RuntimeError(f"{row.seed_id} leftover recommend belongs in LEFTOVER_ROWS")
        for tag in row.allergies:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = recommend_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate recommend key {key}")
        seen.add(key)
