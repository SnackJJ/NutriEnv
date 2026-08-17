"""Exam-author portion whitelist. Not Env physics.

Table amounts are each food's portion rows × {0.5, 1, 1.5, 2}, plus the
fixed 2 oz = 56.7 g. Validator and the grams gate share this set so a
table hit cannot drift between the two callers.
"""

from __future__ import annotations

from nutrienv.world.portions import OUNCE_GRAMS

__all__ = ["matches_portion_table"]


def matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return False
    portions = entry.get("portions") or {}
    candidates = {round(2.0 * OUNCE_GRAMS, 2)}
    for one in portions.values():
        if isinstance(one, (int, float)) and not isinstance(one, bool):
            for quantity in (0.5, 1.0, 1.5, 2.0):
                candidates.add(round(quantity * float(one), 2))
    return round(float(grams), 2) in candidates
