"""Catalog-backed realization tables for the draft factory.

Rows differ in food / portion / ledger geometry. Paraphrases are not new
rows. Grams are never stored: `resolve_portion` and `ledger_totals` compute
them. A row whose phrase does not resolve is invalid and must not be listed.
"""

from __future__ import annotations

from dataclasses import dataclass

from nutrienv.world.portions import resolve_portion

__all__ = [
    "FuzzyRow",
    "LeftoverRow",
    "FUZZY_ROWS",
    "LEFTOVER_ROWS",
    "fuzzy_key",
    "leftover_key",
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


def fuzzy_key(row: FuzzyRow) -> tuple:
    return ("log", "fuzzy_portion", "everyday", row.food_id, row.phrase, row.slot)


def leftover_key(row: LeftoverRow) -> tuple:
    foods = tuple((food_id, slot) for food_id, _grams, slot in row.ledger)
    return ("recommend", None, "leftover", foods, tuple(sorted(row.windows)))


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
