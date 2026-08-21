"""Agreed Rec/Update query shells (docs/mill-query-templates.md), verbatim.

Difficulty lives in S0, not in wording. The mill fills these shells; it never
invents Recommend or Update phrasing.
"""

from __future__ import annotations

__all__ = [
    "RECOMMEND_SHELLS",
    "UPDATE_SHELLS",
    "recommend_query",
    "update_query",
]

RECOMMEND_SHELLS: dict[str, str] = {
    "rec-occasion": "What's for {occasion}?",
    "rec-occasion-eat": "What should I eat?",
    "rec-dinner": "What's for dinner?",
    "rec-breakfast": "What's for breakfast?",
    "rec-lunch": "What should I eat for lunch?",
    "rec-snack": "I need a snack.",
    "rec-post-gym": "Just finished lifting — what should I eat?",
    "rec-named-dish": "Thinking of {dish} tonight — what should I eat?",
}

UPDATE_SHELLS: dict[str, str] = {
    "upd-add-allergy": (
        "I just found out I'm allergic to {food}. Add that to my profile."
    ),
    "upd-add-allergy-short": "Add {allergen} to my allergies.",
    "upd-rm-allergy": (
        "I got tested — I'm not actually allergic to {allergen}. "
        "Take that off my list."
    ),
    "upd-weight": "I weigh {n} kg now. Update my weight.",
    "upd-phase-cut": "I'm cutting now.",
    "upd-phase-muscle": "I want to start building muscle.",
    "upd-phase-maintain": "Stop the cut — maintain for a while.",
    "upd-fatigue": "I've been exhausted. Can we ease the deficit a bit?",
    "upd-kcal-explicit": "Raise my calorie range by {n} at both ends.",
}


def _fill(table: dict[str, str], shell: str, slots: dict[str, str]) -> str | None:
    template = table.get(shell)
    if template is None:
        return None
    try:
        query = template.format(**slots)
    except (KeyError, IndexError):
        return None
    if "{" in query or "}" in query:
        return None
    return query


def recommend_query(shell: str, slots: dict[str, str]) -> str | None:
    """Fill one Recommend shell. Unknown shell or missing slot is None."""
    return _fill(RECOMMEND_SHELLS, shell, slots)


def update_query(shell: str, slots: dict[str, str]) -> str | None:
    """Fill one Update shell. Unknown shell or missing slot is None."""
    return _fill(UPDATE_SHELLS, shell, slots)
