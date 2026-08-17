from __future__ import annotations

from ..types import NearSynonymRow

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
        "Breakfast was a cup of uncooked oatmeal. Please log it.",
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
        "Lunch was a cup of steamed white rice. Log that?",
        "today-lunch",
    ),
    NearSynonymRow(
        "ns-evoo",
        "olive_oil",
        "evoo",
        "a teaspoon",
        "I put a teaspoon of evoo on lunch. Please log it.",
        "today-lunch",
    ),
)
