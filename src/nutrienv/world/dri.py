"""Static reference intakes served by the ``get_dri`` action.

FDA Daily Values for a 2000 kcal adult diet. This is a fact table, not advice,
and the keys match the catalog's nutrient keys so the two can be compared
directly. A person's own targets live in ``Profile.windows``, not here.
"""

from __future__ import annotations

DRI_REFERENCE: dict[str, dict] = {
    "kcal": {"unit": "kcal", "reference": 2000.0},
    "protein_g": {"unit": "g", "reference": 50.0},
    "carb_g": {"unit": "g", "reference": 275.0},
    "fat_g": {"unit": "g", "reference": 78.0},
    "fiber_g": {"unit": "g", "reference": 28.0},
    "sodium_mg": {"unit": "mg", "reference": 2300.0, "upper_limit": 2300.0},
}

BASIS = "FDA Daily Value, 2000 kcal adult reference diet"
