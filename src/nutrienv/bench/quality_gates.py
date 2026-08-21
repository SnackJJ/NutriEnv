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
from .windows import any_pair_unsatisfiable

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
    "classify_evaluate_tier",
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

# Situation names a split may declare for its hard-S0 recommend items.
_HARD_SITUATIONS = frozenset({"condition_suitability", "conflict_windows"})

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
    """Ids of evaluate items whose gold verdict is reject (unfit named meal)."""
    return tuple(
        task.id
        for task in tasks
        if task.family == "evaluate" and task.oracle.last_verdict == "reject"
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
        names = [food_id.replace("_", " "), str(entry.get("name") or "")]
        names.extend(str(alias) for alias in entry.get("aliases") or [])
        for name in names:
            phrase = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
            if len(phrase) >= 3 and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", query):
                return True
    return False


def constrained_recommends(tasks: Sequence[Task]) -> tuple[str, ...]:
    """Ids of recommend tasks whose S0 is hard (ADR 0016 constrained set).

    A recommend is constrained when any of these reads off the frozen item:
    declared hard situations, impossible windows (no plan can satisfy them),
    or a named-dish allergy trap.
    """
    ids = []
    for task in tasks:
        if task.family != "recommend":
            continue
        if _HARD_SITUATIONS & set(task.situations):
            ids.append(task.id)
            continue
        if any_pair_unsatisfiable(
            task.s0.profile.windows, task.s0.catalog, task.s0.profile.allergies
        ):
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
