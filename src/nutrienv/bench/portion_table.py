"""Exam-author portion whitelist. Not Env physics.

Table amounts are each food's portion rows × {0.5, 1, 1.5, 2}, plus
ounce multiples {0.5, 1, 1.5, 2} × 28.35 g. An ounce is always 28.35 g
(react.py handbook). The ounce whitelist mirrors the portion-key
multiples. Validator and the grams gate share this set so a table hit
cannot drift between the two callers.
"""

from __future__ import annotations

from nutrienv.world.portions import OUNCE_GRAMS

__all__ = ["matches_portion_table"]

_OUNCE_MULTIPLES = (0.5, 1.0, 1.5, 2.0)


def matches_portion_table(food_id: str, grams: float, catalog) -> bool:
    entry = catalog.get(food_id)
    if not isinstance(entry, dict):
        return False
    portions = entry.get("portions") or {}
    candidates = {round(q * OUNCE_GRAMS, 2) for q in _OUNCE_MULTIPLES}
    for one in portions.values():
        if isinstance(one, (int, float)) and not isinstance(one, bool):
            for quantity in _OUNCE_MULTIPLES:
                candidates.add(round(quantity * float(one), 2))
    return round(float(grams), 2) in candidates
