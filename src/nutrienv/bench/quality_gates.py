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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from nutrienv.world.catalog import iter_catalog_entries

from .realize import Task
from .validator import fitting_plan

__all__ = [
    "CONSTRAINED_RECOMMEND_FLOOR",
    "DEFAULT_EVALUATE_TIER_FLOORS",
    "EVALUATE_TIERS",
    "EVALUATE_UNFIT_FLOOR",
    "LEFTOVER_RECOMMEND_FLOOR",
    "CoverageReport",
    "LeftoverFloorReport",
    "SituationFloorReport",
    "TierCoverageReport",
    "constrained_recommends",
    "evaluate_tier_coverage",
    "evaluate_unfits",
    "leftover_floor",
    "leftover_recommends",
    "recommend_coverage",
    "situation_floors",
    "window_leaks",
]

# ADR 0009, kept by ADR 0016: at least this many leftover recommends.
LEFTOVER_RECOMMEND_FLOOR = 24
# ADR 0016: the situation floors sit inside evaluate / recommend.
EVALUATE_UNFIT_FLOOR = 8
CONSTRAINED_RECOMMEND_FLOOR = 8


def _stated_numbers(value: object) -> tuple[str, ...]:
    """The numeric spellings of a window bound that would leak it."""
    number = float(value)
    if not number or abs(number) < 10:
        return ()
    stated = [str(int(number))]
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    if "." in text:
        stated.append(text)
    return tuple(stated)


def _leaks_windows(task: Task) -> bool:
    """A recommend query that names its own numbers is answerable without
    reading the profile, which is the whole point of the family. New exams
    judge meal-slot/remainder windows via ``oracle.plan_windows``, so those
    numbers are secrets too."""
    window_sets = [task.s0.profile.windows]
    if task.oracle.plan_windows is not None:
        window_sets.append(task.oracle.plan_windows)
    for windows in window_sets:
        for bounds in windows.values():
            for value in bounds:
                if any(
                    re.search(rf"(?<!\d){re.escape(token)}(?!\d)", task.query)
                    for token in _stated_numbers(value)
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


# Difficulty tiers a split declares on its evaluate items, with the per-tier
# floors migrated from tests/archive/test_v03_split.py::
# test_v03_evaluate_covers_every_difficulty_tier. The tier is authoring data
# on the frozen row (``Task.tier``); nothing is inferred from item content.
# Exported policy is read-only: a caller must not be able to bend the gate.
DEFAULT_EVALUATE_TIER_FLOORS = MappingProxyType({
    "single": 7,
    "pair": 11,
    "triple": 11,
    "long": 5,
    "explicit_grams": 4,
    "synonym": 3,
})
EVALUATE_TIERS = tuple(DEFAULT_EVALUATE_TIER_FLOORS)


@dataclass(frozen=True)
class TierCoverageReport:
    counts: dict[str, int]
    missing: tuple[str, ...]


def evaluate_tier_coverage(
    tasks: Sequence[Task],
    *,
    floors: Mapping[str, int] | None = None,
) -> TierCoverageReport:
    """Declared-tier coverage of the evaluate slice against migrated floors.

    Items are grouped by ``Task.tier`` exactly as each split declares it;
    items with no declared tier count toward no floor. Defaults are the
    v0.3 floors exactly.
    """
    declared = DEFAULT_EVALUATE_TIER_FLOORS if floors is None else floors
    counts = {tier: 0 for tier in EVALUATE_TIERS}
    for task in tasks:
        if task.family == "evaluate" and task.tier in counts:
            counts[task.tier] += 1
    missing = tuple(sorted(
        tier for tier, least in declared.items() if counts.get(tier, 0) < least
    ))
    return TierCoverageReport(counts=counts, missing=missing)


@dataclass(frozen=True)
class LeftoverFloorReport:
    count: int
    minimum: int


def leftover_recommends(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of recommend tasks carrying remainder geometry.

    Leftover is a scene, not a persona name (ADR 0017): the S0 ledger holds
    food eaten earlier that day. Older frozen splits tag the same geometry
    with the ``leftover`` persona, so both count.
    """
    return tuple(
        task.id
        for task in tasks
        if task.family == "recommend"
        and (task.persona == "leftover" or task.s0.ledger)
    )


def leftover_floor(
    tasks: Sequence[Task], *, minimum: int = LEFTOVER_RECOMMEND_FLOOR
) -> LeftoverFloorReport:
    """Count of leftover recommends against the ADR floor."""
    return LeftoverFloorReport(count=len(leftover_recommends(tasks)), minimum=minimum)


def evaluate_unfits(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of evaluate items carrying ADR 0017's unfit envelope: a reject
    verdict over an empty named plan. A reject that still names a meal is
    legacy shape, not Evaluate-unfit."""
    return tuple(
        task.id
        for task in tasks
        if task.family == "evaluate"
        and task.oracle.last_verdict == "reject"
        and task.oracle.last_plan == []
    )


def _query_names_allergen_food(task: Task) -> bool:
    """True when the query names a catalog food carrying a profile allergen.

    The named-dish trap of ADR 0017: ordinary speech, the allergy sits in
    the profile. Names, aliases, and slugs match as whole phrases so
    ``prawns`` finds ``shrimp``.
    """
    banned = {str(tag) for tag in task.s0.profile.allergies}
    if not banned:
        return False
    query = re.sub(r"[^a-z0-9]+", " ", task.query.lower())
    for food_id, entry in iter_catalog_entries(task.s0.catalog):
        tags = {str(tag) for tag in entry.get("allergen_tags") or ()}
        if not tags & banned:
            continue
        name = str(entry.get("name") or "")
        names = [food_id.replace("_", " "), name]
        # Generation speaks the first comma-delimited segment ("grilled
        # salmon" out of "Grilled salmon, 150g portion").
        if "," in name:
            names.append(name.split(",", 1)[0])
        names.extend(str(alias) for alias in entry.get("aliases") or [])
        for name in names:
            phrase = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            if len(phrase) >= 3 and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", query):
                return True
    return False


def constrained_recommends(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of recommend tasks whose hard S0 is verified from the item itself.

    Three categories, each read off reality rather than a declared tag:
    pinned ``oracle.plan_windows`` with no fitting allergen-safe plan
    (``fitting_plan`` finds none), a leftover/remainder scene (food eaten
    earlier that day judged on pinned remainder windows), or a named-dish
    allergy trap. Situation labels are never trusted: an unverifiable
    ``conflict_windows`` tag counts as unconstrained. Each task is counted
    once even when several categories match.
    """
    ids = []
    for task in tasks:
        if task.family != "recommend":
            continue
        if task.oracle.plan_windows is not None and fitting_plan(
            task.s0.catalog, task.oracle.plan_windows, task.s0.profile.allergies
        ) is None:
            ids.append(task.id)
            continue
        if task.s0.ledger and task.oracle.plan_windows is not None:
            ids.append(task.id)
            continue
        if _query_names_allergen_food(task):
            ids.append(task.id)
    return tuple(ids)


@dataclass(frozen=True)
class SituationFloorReport:
    unfit_count: int
    unfit_minimum: int
    constrained_count: int
    constrained_minimum: int


def situation_floors(
    tasks: Sequence[Task],
    *,
    unfit_minimum: int = EVALUATE_UNFIT_FLOOR,
    constrained_minimum: int = CONSTRAINED_RECOMMEND_FLOOR,
) -> SituationFloorReport:
    """The two retired constrain mechanisms restated as floors (ADR 0016).

    v0.x kept condition-suitability and conflict-windows constrain rows; the
    four-family exam carries the same mechanisms inside evaluate
    (Evaluate-unfit) and recommend (constrained Recommends).
    """
    return SituationFloorReport(
        unfit_count=len(evaluate_unfits(tasks)),
        unfit_minimum=unfit_minimum,
        constrained_count=len(constrained_recommends(tasks)),
        constrained_minimum=constrained_minimum,
    )
