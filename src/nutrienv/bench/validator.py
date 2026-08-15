"""Reject leaky, unresolvable, or unachievable draft tasks.

This is a factory gate, not a Scorer. Admitted exam items still need a human
to check that the spoken query entails the scored end state.
"""

from __future__ import annotations

import re

from nutrienv.world.portions import OUNCE_GRAMS
from nutrienv.world.types import ledger_totals

from .generator import Task

__all__ = ["validate_draft", "semantic_key"]

_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


def semantic_key(task: Task) -> tuple:
    if task.situations == ("fuzzy_portion",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        return (
            task.family,
            "fuzzy_portion",
            task.persona,
            row.food_id,
            row.grams,
            row.eaten_at,
        )
    if task.persona == "leftover":
        foods = tuple((row.food_id, row.eaten_at) for row in task.s0.ledger)
        windows = tuple(sorted(task.s0.profile.windows))
        return ("recommend", None, "leftover", foods, windows)
    return (task.family, task.situations, task.persona, task.query)


def _matches_portion_table(food_id: str, grams: float, catalog) -> bool:
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


def validate_draft(task: Task) -> list[str]:
    """Return issue strings. Empty means the draft is mechanically admissible."""
    issues: list[str] = []
    query = task.query.lower()
    if "catalog id" in query or "food_id" in query:
        issues.append("query leaks food_id")
    if task.family == "recommend" and _WINDOW_LEAK.search(task.query):
        issues.append("recommend query leaks window numbers")
    if task.family != "evaluate":
        leaked = [
            token for token in _SLUG.findall(query) if token in task.s0.catalog
        ]
        if leaked:
            issues.append(f"query leaks catalog slugs {leaked}")

    if task.situations == ("fuzzy_portion",) and task.oracle.ledger_tail:
        row = task.oracle.ledger_tail[0]
        if not _matches_portion_table(row.food_id, row.grams, task.s0.catalog):
            issues.append(f"fuzzy grams {row.grams} do not match portion table")

    if task.persona == "leftover" and task.oracle.plan_windows:
        eaten = ledger_totals(task.s0.ledger, task.s0.catalog)
        for key, (lo, hi) in task.s0.profile.windows.items():
            used = eaten.get(key, 0.0)
            expected = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
            if task.oracle.plan_windows.get(key) != expected:
                issues.append(f"plan_windows {key} != remainder {expected}")
        kcal = task.oracle.plan_windows.get("kcal")
        if kcal is not None and kcal[1] <= 0:
            issues.append("leftover kcal ceiling is not positive")
    return issues
