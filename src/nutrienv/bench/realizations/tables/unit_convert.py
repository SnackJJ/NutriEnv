from __future__ import annotations

from ..types import UnitConvertRow

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
        "Lunch was about 3 ounces of chicken breast. Please log it.",
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
        "Dinner was 1.5 cups of white rice. Please log that.",
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
