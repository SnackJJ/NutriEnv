"""Meal-scale mass policy, independent of nutrient budgets and spoken portions.

These are conservative adult benchmark envelopes, not medical maximum intakes.
The day scope preserves the historical whole-day envelope. Drinks in a submitted
plan count toward the same total as solids; row splitting never changes the total.
"""

from collections.abc import Mapping, Sequence

PLAN_MASS_LIMITS = {
    "meal": 1500.0,
    "snack": 500.0,
    "day": 4000.0,
}


def plan_mass_limit(scope: str) -> float:
    if not isinstance(scope, str):
        raise TypeError("plan scope must be a string")
    if scope not in PLAN_MASS_LIMITS:
        raise ValueError(f"unknown plan scope {scope!r}; expected {tuple(PLAN_MASS_LIMITS)}")
    return PLAN_MASS_LIMITS[scope]


def plan_mass_pass(items: Sequence[Mapping], scope: str) -> bool:
    """Judge already validated food/gram rows against the immutable episode scope."""
    return sum(float(item["grams"]) for item in items) <= plan_mass_limit(scope)


def plan_limits_view(scope: str) -> dict:
    return {"scope": scope, "max_total_grams": plan_mass_limit(scope)}
