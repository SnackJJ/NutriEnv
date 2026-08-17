from __future__ import annotations

from ..types import MultiItemLogRow

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
        "Lunch was 150 grams of chicken breast and a cup of white rice. Please log both.",
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
        "Dinner was 160 g tofu, a cup of white rice, a cup of spinach, and a teaspoon of olive oil. Please log all of it.",
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
        "Lunch was a can of tuna, 100 g broccoli, and a cup of white rice. Please log all of it.",
        (("tuna", "a can"), ("broccoli", "100 g"), ("white_rice", "a cup")),
        "today-lunch",
    ),
    MultiItemLogRow(
        "mi-dinner-beef-pasta-spin",
        "Dinner was 180 g ground beef, a cup of pasta, and a cup of spinach. Log all three.",
        (("beef", "180 g"), ("pasta", "a cup"), ("spinach", "a cup")),
        "today-dinner",
    ),
    MultiItemLogRow(
        "mi-bfast-milk-oats-banana-pb",
        "Breakfast was a cup of whole milk, 60 g oats, a banana, and a tablespoon of peanut butter. Please log all of it.",
        (
            ("milk_whole", "a cup"),
            ("oats", "60 g"),
            ("banana", "a piece"),
            ("peanut_butter", "a tablespoon"),
        ),
        "today-breakfast",
    ),
)
