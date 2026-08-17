from __future__ import annotations

from ..types import EvaluateRow

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
