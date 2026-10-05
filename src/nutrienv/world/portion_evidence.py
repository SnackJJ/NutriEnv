"""Compute grams from agent-authored evidence, never from natural-language parsing."""

import math
from collections.abc import Mapping

from .types import normalize_grams


def portion_grams(food_id: str, evidence: Mapping, catalog: Mapping) -> float:
    """Accept an explicit measured weight or a catalog key/count; missing evidence raises."""
    if food_id not in catalog:
        raise ValueError(f"unknown portion food_id: {food_id!r}")
    if not isinstance(evidence, Mapping):
        raise TypeError("portion evidence must be an object")
    if set(evidence) == {"grams"}:
        return normalize_grams(evidence["grams"])
    if set(evidence) != {"key", "count"}:
        raise ValueError("portion evidence requires exactly grams, or key and count")
    key, count = evidence["key"], evidence["count"]
    if not isinstance(key, str) or not key:
        raise ValueError("portion key must be a non-empty string")
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        raise TypeError("portion count must be a number")
    if not math.isfinite(count) or count <= 0:
        raise ValueError("portion count must be positive and finite")
    portions = catalog[food_id]["portions"]
    if key not in portions:
        raise ValueError(f"{food_id}: catalog has no portion key {key!r}")
    unit = portions[key]
    if isinstance(unit, bool) or not isinstance(unit, (int, float)) or not math.isfinite(unit) or unit <= 0:
        raise ValueError(f"{food_id}: invalid catalog portion {key!r}: {unit!r}")
    return normalize_grams(round(float(unit) * float(count), 2))
