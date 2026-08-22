"""Composite recommend-step occasion resolution, shared by the gates.

Resolver and validator must resolve the same occasion the same way:
a log tail stamps the meal just eaten, the spoken "for <meal>" word
decides without one, and an unresolvable case is returned as ``None``
so callers can fail loudly instead of guessing dinner.
"""

from __future__ import annotations

import re

__all__ = [
    "MEAL_OCCASIONS",
    "REC_OCCASION_AFTER",
    "occasion_from_query",
    "occasion_from_stamp",
    "recommend_occasion",
]

MEAL_OCCASIONS = ("breakfast", "lunch", "dinner", "snack")

# A composite recommend step asks for the meal after the logged one.
REC_OCCASION_AFTER = {
    "breakfast": "lunch",
    "lunch": "dinner",
    "dinner": "dinner",
    "snack": "dinner",
}

_STAMP_MEAL = re.compile(r"(?:^|-)(breakfast|lunch|dinner|snack)$")
_FOR_MEAL = re.compile(r"\bfor\s+(breakfast|lunch|dinner|snack)\b")


def occasion_from_stamp(stamp: str) -> str | None:
    """Occasion named at the end of a ledger stamp ("today-lunch"), or None."""
    match = _STAMP_MEAL.search(str(stamp))
    return match.group(1) if match else None


def occasion_from_query(query: str) -> str | None:
    """Occasion spoken as "for <meal>" in the query, or None."""
    match = _FOR_MEAL.search(query.lower())
    return match.group(1) if match else None


def recommend_occasion(query: str, tail) -> str | None:
    """Occasion a composite recommend step was pinned for, or None.

    The log tail's stamp wins; without a tail (update+recommend) the
    spoken meal word decides.
    """
    if tail:
        stamped = occasion_from_stamp(getattr(tail[-1], "eaten_at", ""))
        if stamped is not None:
            return REC_OCCASION_AFTER[stamped]
    return occasion_from_query(query)
