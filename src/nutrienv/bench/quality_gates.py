"""Split-agnostic quality floors for any frozen exam split.

Five checks migrated from the archived v0.x increment tests (ticket 14).
They take a loaded split -- the ``Sequence[Task]`` that ``load_split``
returns -- never a split path or item id, and report instead of asserting,
so a caller chooses to gate, print, or drop ids. Coverage-type floors are
declared by the exam's own contract; the gates only verify the frozen
split backs it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from nutrienv.world.catalog import iter_catalog_entries

from .realize import Task

__all__ = [
    "DEFAULT_EVALUATE_TIER_FLOORS",
    "EVALUATE_TIERS",
    "CoverageReport",
    "TierCoverageReport",
    "classify_evaluate_tier",
    "evaluate_tier_coverage",
    "recommend_coverage",
    "window_leaks",
]

# Spoken raw gram phrase ("200 g chicken"), as in validator's parse rules.
_SPOKEN_GRAMS = re.compile(r"(?<!\d)(\d+(?:\.\d+)?)\s*g(?:rams?)?\b")


def _leaks_windows(task: Task) -> bool:
    """A recommend query that names its own numbers is answerable without
    reading the profile, which is the whole point of the family."""
    for bounds in task.s0.profile.windows.values():
        for value in bounds:
            if (
                value
                and float(value).is_integer()
                and abs(value) >= 10
                and str(int(value)) in task.query
            ):
                return True
    return False


def window_leaks(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of recommend tasks whose query states one of their window numbers."""
    return tuple(task.id for task in tasks if task.family == "recommend" and _leaks_windows(task))


@dataclass(frozen=True)
class CoverageReport:
    missing_personas: tuple[str, ...]
    missing_allergens: tuple[str, ...]


def _catalog_allergen_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for _, entry in iter_catalog_entries(catalog):
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


def recommend_coverage(
    tasks: Sequence[Task],
    *,
    personas: Sequence[str] = (),
    allergen_tags: Sequence[str] | None = None,
) -> CoverageReport:
    """Persona x allergen coverage of the recommend slice.

    The diversity claim is persona x allergy: if the admitted recommends
    drop a declared persona or leave a catalog allergen tag uncovered by
    every profile, the claim is not backed. ``allergen_tags=None`` derives
    the claim from the split's own catalog (every declared tag).
    """
    recommends = [task for task in tasks if task.family == "recommend"]
    seen = {task.persona for task in recommends}
    covered: set[str] = set()
    for task in recommends:
        covered.update(task.s0.profile.allergies)
    wanted = (
        _catalog_allergen_tags(next((t.s0.catalog for t in tasks), {}))
        if allergen_tags is None
        else set(allergen_tags)
    )
    return CoverageReport(
        missing_personas=tuple(sorted(set(personas) - seen)),
        missing_allergens=tuple(sorted(wanted - covered)),
    )


# Structural difficulty tiers any frozen split exposes without its authoring
# tables: the size of the named meal, and whether the query speaks raw grams.
EVALUATE_TIERS = ("single", "pair", "triple", "explicit_grams")
DEFAULT_EVALUATE_TIER_FLOORS = {tier: 1 for tier in EVALUATE_TIERS}


def classify_evaluate_tier(task: Task) -> str:
    """Structural tier of one evaluate item, readable off the frozen Task."""
    if _SPOKEN_GRAMS.search(task.query):
        return "explicit_grams"
    named = task.oracle.evaluated_plan or task.oracle.last_plan or ()
    if len(named) >= 3:
        return "triple"
    if len(named) == 2:
        return "pair"
    return "single"


@dataclass(frozen=True)
class TierCoverageReport:
    counts: dict[str, int]
    missing: tuple[str, ...]


def evaluate_tier_coverage(
    tasks: Sequence[Task],
    *,
    floors: dict[str, int] | None = None,
) -> TierCoverageReport:
    """Difficulty-tier coverage of the evaluate slice.

    The slots are only worth having if they differ on a declared axis. The
    structural axis is the named-meal size plus spoken-gram phrases; floors
    default to at least one item per known tier.
    """
    declared = DEFAULT_EVALUATE_TIER_FLOORS if floors is None else floors
    counts = {tier: 0 for tier in EVALUATE_TIERS}
    for task in tasks:
        if task.family == "evaluate":
            counts[classify_evaluate_tier(task)] += 1
    missing = tuple(sorted(
        tier for tier, least in declared.items() if counts.get(tier, 0) < least
    ))
    return TierCoverageReport(counts=counts, missing=missing)
