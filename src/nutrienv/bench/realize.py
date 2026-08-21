"""Public seam: material + spoken query → complete Task.

``realize(material, query)`` is the only constructor the freeze path and the
future candidate pipeline share. Grams come from the catalog via
``resolve_portion`` (code, never an LLM). Same material + same query produce
field-equal Tasks; a different query changes only ``Task.query``.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace

from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.daily_windows import meal_slot_and_remainder, plan_windows_for_meal
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import (
    LedgerRow,
    Profile,
    WorldState,
    ledger_totals,
    normalize_reasons,
    normalize_tags,
)

from .realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
    ConstrainRow,
    EvaluateRow,
    FuzzyRow,
    LedgerGapRow,
    LeftoverRow,
    MultiItemLogRow,
    NearSynonymRow,
    RecommendRow,
    UnitConvertRow,
    UpdateRow,
    evaluate_windows,
)

__all__ = [
    "FAMILIES",
    "GOLD_WINDOWS",
    "Oracle",
    "Task",
    "Material",
    "realize",
    "material_from_row",
    "spoken_query",
    "iter_realization_rows",
    "compose_oracles",
    "scored_oracles",
    "realize_evaluate",
    "bind_evaluate_reasons",
    "leftover_bound_labels",
]


FAMILIES = ("lookup", "log", "recommend", "evaluate", "update", "constrain")

GOLD_WINDOWS = {"kcal": (1800.0, 2200.0), "protein_g": (90.0, 140.0)}

# v0.1 curated the S0 of a fuzzy log item as three distractor rows: a
# yesterday row, a row in some other slot today, and a row in the target slot
# under a different food. Reused verbatim so log items stay one shape.
FUZZY_DISTRACTORS = {"apple": 182.0, "orange": 131.0, "oats": 60.0, "banana": 118.0}

_TABLES: tuple[tuple[object, ...], ...] = (
    FUZZY_ROWS,
    MULTI_ITEM_LOG_ROWS,
    UNIT_CONVERT_ROWS,
    NEAR_SYNONYM_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    UPDATE_ROWS,
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    RECOMMEND_ROWS,
)

RealizationRow = (
    FuzzyRow
    | MultiItemLogRow
    | UnitConvertRow
    | NearSynonymRow
    | LedgerGapRow
    | LeftoverRow
    | UpdateRow
    | ConstrainRow
    | EvaluateRow
    | RecommendRow
)


@dataclass(frozen=True)
class Oracle:
    """The query-scoped portion of the expected end state.

    ``last_plan=[]`` is the marker for a free recommendation: the submitted
    plan may contain any catalog items, provided it is non-empty, allergen-safe,
    and inside every judged window.  A non-empty value is the exact plan named
    by an evaluate task.  ``None`` means plans are not judged.

    ``plan_windows``, when set, is what the submitted plan is checked against.
    Use it when the agent reads daily windows on the profile but the meal must
    fit the remainder after the ledger.  Profile equality still uses ``profile``.

    ``last_verdict`` is ``None`` (legacy: today's plan scoring), ``"accept"``,
    or ``"reject"``.  ``last_reasons`` is the closed reason-code set a reject
    oracle requires.  Reject oracles leave ``plan_must_fit_windows`` and
    ``allow_empty_plan`` unset; the verdict branch owns scoring.

    ``update_band`` is ``None`` (exact Profile equality) or an ADR 0015
    implicit intent (``cut``, ``fatigue``, ``muscle``): windows Pass in the
    published band; allergies and other unmentioned fields stay exact.

    ``evaluated_plan`` is the named meal on Evaluate Tasks. Env does not
    adopt it on reject. Validator, reason bind, and Stage A read it.
    """

    profile: Profile | None = None
    last_plan: list | None = None
    ledger_tail: list | None = None
    # Compatibility with the initial integration seam. New code should use
    # ``ledger_tail`` and the last_plan sentinel documented above.
    ledger: tuple[LedgerRow, ...] | None = None
    plan_must_be_safe: bool = False
    plan_must_fit_windows: bool = False
    allow_empty_plan: bool = False
    plan_windows: dict[str, tuple[float, float]] | None = None
    last_verdict: str | None = None
    last_reasons: tuple[str, ...] = ()
    update_band: str | None = None
    evaluated_plan: list | None = None
    bound_labels: tuple[str, ...] = ()
    # None = single-family oracle (frozen v0.5 / v1.0 path). A non-empty
    # tuple is a composite container: Scorer judges only the children.
    sub_oracles: tuple[Oracle, ...] | None = None


@dataclass(frozen=True)
class Task:
    id: str
    family: str
    query: str
    s0: WorldState
    oracle: Oracle
    situations: tuple[str, ...] = ()
    persona: str = "everyday"
    # Declared difficulty tier of the item (authoring data, not inferred
    # from content). Empty when the split declares none; coverage gates
    # group evaluate items by this field.
    tier: str = ""


@dataclass(frozen=True)
class Material:
    """A realization row plus the S0 recipe and Task identity.

    Catalog is injected at ``realize`` time so the same material can be built
    against any catalog. ``windows is None`` means the gold daily windows.
    """

    row: object
    family: str
    situations: tuple[str, ...]
    persona: str
    task_id: str
    user_id: str
    allergies: tuple[str, ...] = ()
    windows: dict[str, tuple[float, float]] | None = None
    plan_preset: dict | None = None
    ledger: tuple[tuple[str, float, str], ...] = ()
    last_plan: tuple[tuple[str, float], ...] = ()


def iter_realization_rows() -> Iterable[RealizationRow]:
    """Yield every row in the ten realization tables, table order."""
    for table in _TABLES:
        yield from table


def spoken_query(row: object) -> str:
    """The hand-written utterance the freeze path pins on a row."""
    text = getattr(row, "query", None) or getattr(row, "utterance", None)
    if not isinstance(text, str) or not text.strip():
        label = getattr(row, "seed_id", type(row).__name__)
        raise ValueError(f"row {label!r} has no spoken query")
    return text


def material_from_row(
    row: RealizationRow,
    *,
    tag: str = "draft",
    catalog: Mapping | None = None,
) -> Material:
    """Gold-style material used by ``materialize_split`` and by tests.

    Task ids and user ids follow the freeze-path derivation so a rebuild of
    v0.2–v0.5 stays byte-identical.
    """
    foods = catalog if catalog is not None else load_catalog()
    if isinstance(row, FuzzyRow):
        stem = row.seed_id.removeprefix("fz-")
        return Material(
            row=row,
            family="log",
            situations=("fuzzy_portion",),
            persona="everyday",
            task_id=f"{tag}-log-fz-{stem}",
            user_id=f"{tag}-fz-{stem}",
            allergies=("peanut",),
            ledger=_fuzzy_distractor_ledger(row),
        )
    if isinstance(row, MultiItemLogRow):
        stem = row.seed_id
        return Material(
            row=row,
            family="log",
            situations=("multi_item_log",),
            persona="everyday",
            task_id=f"{tag}-log-{stem}",
            user_id=f"{tag}-{stem}",
            allergies=_log_allergies(foods, [food_id for food_id, _phrase in row.items]),
            ledger=_log_distractor_ledger(row.slot),
        )
    if isinstance(row, UnitConvertRow):
        return Material(
            row=row,
            family="log",
            situations=("unit_convert",),
            persona="everyday",
            task_id=f"{tag}-log-{row.seed_id}",
            user_id=f"{tag}-{row.seed_id}",
            allergies=_log_allergies(foods, [row.food_id]),
            ledger=_log_distractor_ledger(row.slot),
        )
    if isinstance(row, NearSynonymRow):
        return Material(
            row=row,
            family="log",
            situations=("near_synonym",),
            persona="everyday",
            task_id=f"{tag}-log-{row.seed_id}",
            user_id=f"{tag}-{row.seed_id}",
            allergies=_log_allergies(foods, [row.food_id]),
            ledger=_log_distractor_ledger(row.slot),
        )
    if isinstance(row, LedgerGapRow):
        food_id, _phrase, _slot = row.missing
        return Material(
            row=row,
            family="log",
            situations=("ledger_gap",),
            persona="everyday",
            task_id=f"{tag}-log-{row.seed_id}",
            user_id=f"{tag}-{row.seed_id}",
            allergies=_log_allergies(foods, [food_id]),
            ledger=row.surround,
        )
    if isinstance(row, LeftoverRow):
        stem = row.seed_id.removeprefix("lo-")
        return Material(
            row=row,
            family="recommend",
            situations=(),
            persona="leftover",
            task_id=f"{tag}-rec-lo-{stem}",
            user_id=f"{tag}-lo-{stem}",
            allergies=(),
        )
    if isinstance(row, RecommendRow):
        stem = row.seed_id.removeprefix("rec-")
        return Material(
            row=row,
            family="recommend",
            situations=(),
            persona=row.persona,
            task_id=f"{tag}-rec-{stem}",
            user_id=f"{tag}-rec-{stem}",
            allergies=(),
        )
    if isinstance(row, UpdateRow):
        stem = row.seed_id.removeprefix("up-")
        return Material(
            row=row,
            family="update",
            situations=(),
            persona="cut" if row.s0_plan_preset else "everyday",
            task_id=f"{tag}-upd-{stem}",
            user_id=f"{tag}-upd-{stem}",
            allergies=("peanut",),
        )
    if isinstance(row, ConstrainRow):
        if row.kind == "condition":
            stem = row.seed_id.removeprefix("co-")
            return Material(
                row=row,
                family="constrain",
                situations=("condition_suitability",),
                persona="everyday",
                task_id=f"{tag}-cond-{stem}",
                user_id=f"{tag}-cond-{stem}",
                allergies=(),
            )
        stem = row.seed_id.removeprefix("cf-")
        return Material(
            row=row,
            family="constrain",
            situations=("conflict_windows",),
            persona="everyday",
            task_id=f"{tag}-conf-{stem}",
            user_id=f"{tag}-conf-{stem}",
            allergies=(),
        )
    if isinstance(row, EvaluateRow):
        stem = row.seed_id.removeprefix("ev-")
        carried: set[str] = set()
        for food_id, _phrase in row.items:
            carried.update((foods.get(food_id) or {}).get("allergen_tags") or [])
        allergies = tuple(tag_ for tag_ in ("peanut",) if tag_ not in carried)
        return Material(
            row=row,
            family="evaluate",
            situations=(),
            persona="everyday",
            task_id=f"{tag}-eval-{stem}",
            user_id=f"{tag}-eval-{stem}",
            allergies=allergies,
        )
    raise TypeError(f"unknown realization row: {type(row)!r}")


def scored_oracles(oracle: Oracle) -> tuple[Oracle, ...]:
    """Oracles the Scorer judges. Composite: the children; else ``(oracle,)``."""
    if oracle.sub_oracles:
        return oracle.sub_oracles
    return (oracle,)


def compose_oracles(*oracles: Oracle) -> Oracle:
    """Wrap N ≥ 2 oracles as a composite container. Parent fields are unused."""
    if len(oracles) < 2:
        raise ValueError("compose_oracles requires at least two sub-oracles")
    if any(child.sub_oracles for child in oracles):
        raise ValueError("nested sub_oracles are not allowed")
    return Oracle(sub_oracles=tuple(oracles))


def bind_evaluate_reasons(
    items: list,
    windows: dict[str, tuple[float, float]],
    catalog: Mapping,
    allergies: tuple[str, ...],
) -> tuple[str, ...]:
    """Closed reason codes that fire for a named meal against plan_windows."""
    codes: list[str] = []
    banned = set(normalize_tags(list(allergies)))
    for item in items:
        entry = catalog.get(item["food_id"]) or {}
        tags = set(normalize_tags(list(entry.get("allergen_tags") or [])))
        if tags & banned:
            codes.append("allergy")
            break
    rows = [
        LedgerRow(str(item["food_id"]), float(item["grams"]), "eval") for item in items
    ]
    totals = ledger_totals(rows, catalog)
    for key, (lo, hi) in windows.items():
        amount = totals.get(key, 0.0)
        if amount < lo:
            codes.append(f"{key}_lo")
        if amount > hi:
            codes.append(f"{key}_hi")
    return normalize_reasons(codes)


def leftover_bound_labels(
    items: list,
    slot: dict[str, tuple[float, float]],
    remainder: dict[str, tuple[float, float]],
    catalog: Mapping,
    *,
    last_meal: bool = False,
) -> tuple[str, ...]:
    """leftover_over/under when remainder binds and the slot leg would pass."""
    rows = [
        LedgerRow(str(item["food_id"]), float(item["grams"]), "eval") for item in items
    ]
    totals = ledger_totals(rows, catalog)
    labels: set[str] = set()
    for key, (slot_lo, slot_hi) in slot.items():
        rem_lo, rem_hi = remainder[key]
        amount = totals.get(key, 0.0)
        slot_ok = slot_lo <= amount <= slot_hi
        if not slot_ok:
            continue
        if amount > rem_hi:
            labels.add("leftover_over")
        if last_meal and amount < rem_lo:
            labels.add("leftover_under")
    return tuple(sorted(labels))


def realize_evaluate(
    *,
    task_id: str,
    query: str,
    items: list,
    s0: WorldState,
    occasion: str,
    last_meal: bool = False,
) -> Task:
    """Construct a verdict-aware Evaluate Task. Empty intersections raise."""
    meal = [
        {"food_id": item["food_id"], "grams": float(item["grams"])} for item in items
    ]
    eaten = ledger_totals(s0.ledger, s0.catalog)
    windows = plan_windows_for_meal(
        s0.profile.windows, eaten, occasion, last_meal=last_meal
    )
    if windows is None:
        raise ValueError("empty plan_windows intersection")
    slot, remainder = meal_slot_and_remainder(
        s0.profile.windows, eaten, occasion
    )
    labels = leftover_bound_labels(
        meal, slot, remainder, s0.catalog, last_meal=last_meal
    )
    reasons = bind_evaluate_reasons(
        meal, windows, s0.catalog, s0.profile.allergies
    )
    if reasons:
        oracle = Oracle(
            profile=copy.deepcopy(s0.profile),
            last_plan=[],
            last_verdict="reject",
            last_reasons=reasons,
            plan_windows=windows,
            evaluated_plan=copy.deepcopy(meal),
            bound_labels=labels,
            ledger=tuple(s0.ledger),
        )
    else:
        oracle = Oracle(
            profile=copy.deepcopy(s0.profile),
            last_plan=copy.deepcopy(meal),
            last_verdict="accept",
            plan_windows=windows,
            evaluated_plan=copy.deepcopy(meal),
            bound_labels=labels,
            ledger=tuple(s0.ledger),
        )
    return Task(task_id, "evaluate", query, s0, oracle)


def realize(
    material: Material,
    query: str,
    *,
    catalog: Mapping | None = None,
) -> Task:
    """Build a complete Task from a material and a spoken query.

    Deterministic: no RNG. Catalog-injectable: pass ``catalog`` to pin the
    portion table; ``None`` loads the default sqlite snapshot.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    foods = catalog if catalog is not None else load_catalog()
    s0 = _s0_from_material(material, foods)
    oracle = _oracle_from_row(s0, material.row)
    return Task(
        material.task_id,
        material.family,
        query,
        s0,
        oracle,
        material.situations,
        material.persona,
    )


def _s0_from_material(material: Material, catalog: Mapping) -> WorldState:
    windows = dict(material.windows) if material.windows is not None else dict(GOLD_WINDOWS)
    profile = Profile(
        user_id=material.user_id,
        allergies=material.allergies,
        windows=windows,
        plan_preset=dict(material.plan_preset or {}),
    )
    ledger = [
        LedgerRow(_food_id(catalog, food_id), float(grams), eaten_at)
        for food_id, grams, eaten_at in material.ledger
    ]
    last_plan = [
        {"food_id": _food_id(catalog, food_id), "grams": float(grams)}
        for food_id, grams in material.last_plan
    ]
    return WorldState(profile=profile, ledger=ledger, catalog=catalog, last_plan=last_plan)


def _oracle_from_row(s0: WorldState, row: object) -> Oracle:
    if isinstance(row, FuzzyRow):
        return _fuzzy_from_row(s0, row)
    if isinstance(row, MultiItemLogRow):
        return _multi_item_from_row(s0, row)
    if isinstance(row, UnitConvertRow):
        return _unit_convert_from_row(s0, row)
    if isinstance(row, NearSynonymRow):
        return _near_synonym_from_row(s0, row)
    if isinstance(row, LedgerGapRow):
        return _ledger_gap_from_row(s0, row)
    if isinstance(row, LeftoverRow):
        return _leftover_from_row(s0, row)
    if isinstance(row, RecommendRow):
        return _recommend_from_row(s0, row)
    if isinstance(row, UpdateRow):
        return _update_from_row(s0, row)
    if isinstance(row, ConstrainRow):
        if row.kind == "condition":
            return _condition_from_row(s0, row)
        return _conflict_from_row(s0, row)
    if isinstance(row, EvaluateRow):
        return _evaluate_from_row(s0, row)
    raise TypeError(f"unknown realization row: {type(row)!r}")


def _require_portion(food_id: str, phrase: str, catalog: Mapping) -> float:
    grams = resolve_portion(food_id, phrase, catalog)
    if grams is None:
        raise RuntimeError(f"catalog cannot resolve {phrase!r} for {food_id}")
    return grams


def _food_id(catalog: Mapping, food_id: str) -> str:
    return canonical_food_id(catalog, food_id)


def _log_oracle(s0: WorldState, tail: list[LedgerRow]) -> Oracle:
    canon = [
        LedgerRow(_food_id(s0.catalog, row.food_id), row.grams, row.eaten_at)
        for row in tail
    ]
    return Oracle(
        profile=copy.deepcopy(s0.profile),
        ledger_tail=canon,
        ledger=(*s0.ledger, *canon),
    )


def _remainder_windows(s0: WorldState) -> dict[str, tuple[float, float]]:
    eaten = ledger_totals(s0.ledger, s0.catalog)
    remain: dict[str, tuple[float, float]] = {}
    for key, (lo, hi) in s0.profile.windows.items():
        used = eaten.get(key, 0.0)
        remain[key] = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
    return remain


def _fuzzy_from_row(s0: WorldState, row: FuzzyRow) -> Oracle:
    grams = _require_portion(row.food_id, row.phrase, s0.catalog)
    return _log_oracle(s0, [LedgerRow(row.food_id, grams, row.slot)])


def _multi_item_from_row(s0: WorldState, row: MultiItemLogRow) -> Oracle:
    tail = [
        LedgerRow(
            food_id,
            _require_portion(food_id, phrase, s0.catalog),
            row.slot,
        )
        for food_id, phrase in row.items
    ]
    return _log_oracle(s0, tail)


def _unit_convert_from_row(s0: WorldState, row: UnitConvertRow) -> Oracle:
    grams = _require_portion(row.food_id, row.phrase, s0.catalog)
    return _log_oracle(s0, [LedgerRow(row.food_id, grams, row.slot)])


def _near_synonym_from_row(s0: WorldState, row: NearSynonymRow) -> Oracle:
    grams = _require_portion(row.food_id, row.phrase, s0.catalog)
    return _log_oracle(s0, [LedgerRow(row.food_id, grams, row.slot)])


def _ledger_gap_from_row(s0: WorldState, row: LedgerGapRow) -> Oracle:
    s0.ledger = [
        LedgerRow(_food_id(s0.catalog, food_id), grams, eaten_at)
        for food_id, grams, eaten_at in row.surround
        if food_id in s0.catalog
    ]
    food_id, phrase, slot = row.missing
    missing = LedgerRow(
        food_id,
        _require_portion(food_id, phrase, s0.catalog),
        slot,
    )
    return _log_oracle(s0, [missing])


def _recommend_from_row(s0: WorldState, row: RecommendRow) -> Oracle:
    extras: dict = {}
    if row.plan_preset is not None:
        extras["plan_preset"] = dict(row.plan_preset)
    s0.profile = replace(
        s0.profile,
        windows=dict(row.windows),
        allergies=normalize_tags(row.allergies),
        **extras,
    )
    s0.ledger = []
    s0.last_plan = []
    return Oracle(
        profile=copy.deepcopy(s0.profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        ledger=tuple(s0.ledger),
    )


def _leftover_from_row(s0: WorldState, row: LeftoverRow) -> Oracle:
    extras: dict = {}
    if row.plan_preset is not None:
        extras["plan_preset"] = dict(row.plan_preset)
    s0.profile = replace(
        s0.profile,
        windows=dict(row.windows),
        allergies=row.allergies or s0.profile.allergies,
        **extras,
    )
    s0.ledger = [
        LedgerRow(_food_id(s0.catalog, food_id), grams, eaten_at)
        for food_id, grams, eaten_at in row.ledger
        if food_id in s0.catalog
    ]
    return Oracle(
        profile=copy.deepcopy(s0.profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=_remainder_windows(s0),
        ledger=tuple(s0.ledger),
    )


def _evaluate_from_row(s0: WorldState, row: EvaluateRow) -> Oracle:
    items = []
    for food_id, phrase in row.items:
        grams = _require_portion(food_id, phrase, s0.catalog)
        items.append({"food_id": _food_id(s0.catalog, food_id), "grams": grams})
    windows = evaluate_windows(
        items,
        s0.catalog,
        kcal_margin=row.margin_kcal,
        protein_margin=row.margin_protein,
    )
    colliding = set()
    for item in items:
        entry = s0.catalog.get(item["food_id"]) or {}
        colliding.update(entry.get("allergen_tags") or [])
    allergies = tuple(tag for tag in s0.profile.allergies if tag not in colliding)
    s0.profile = replace(s0.profile, windows=windows, allergies=allergies)
    return Oracle(
        profile=copy.deepcopy(s0.profile),
        last_plan=items,
        plan_must_fit_windows=True,
        ledger=tuple(s0.ledger),
    )


def _update_from_row(s0: WorldState, row: UpdateRow) -> Oracle:
    profile = s0.profile
    if row.s0_allergies is not None:
        profile = replace(profile, allergies=normalize_tags(row.s0_allergies))
    if row.s0_plan_preset is not None:
        profile = replace(profile, plan_preset=dict(row.s0_plan_preset))
    s0.profile = profile
    allergies = list(s0.profile.allergies)
    for tag in row.add_allergens:
        if tag not in allergies:
            allergies.append(tag)
    remove = set(row.remove_allergens)
    if remove:
        allergies = [tag for tag in allergies if tag not in remove]
    windows = dict(s0.profile.windows)
    for key, delta in (row.window_shifts or {}).items():
        lo, hi = windows.get(key, (0.0, 0.0))
        dlo, dhi = _shift_deltas(delta)
        windows[key] = (float(lo) + dlo, float(hi) + dhi)
    extras: dict = {}
    if row.set_plan_preset is not None:
        extras["plan_preset"] = dict(row.set_plan_preset)
    expected = replace(
        s0.profile,
        allergies=normalize_tags(allergies),
        windows=windows,
        **extras,
    )
    return Oracle(profile=expected, ledger=tuple(s0.ledger))


def _condition_from_row(s0: WorldState, row: ConstrainRow) -> Oracle:
    profile = replace(
        s0.profile,
        allergies=normalize_tags(row.allergies),
        windows=dict(row.windows),
    )
    s0.profile = profile
    return Oracle(
        profile=copy.deepcopy(profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        allow_empty_plan=False,
        ledger=tuple(s0.ledger),
    )


def _conflict_from_row(s0: WorldState, row: ConstrainRow) -> Oracle:
    profile = replace(
        s0.profile,
        windows=dict(row.windows),
        allergies=normalize_tags(row.allergies),
    )
    s0.profile = profile
    s0.last_plan = [
        {"food_id": _food_id(s0.catalog, food_id), "grams": grams}
        for food_id, grams in row.last_plan
    ]
    return Oracle(
        profile=copy.deepcopy(profile),
        last_plan=None,
        plan_must_fit_windows=True,
        allow_empty_plan=True,
        ledger=tuple(s0.ledger),
    )


def _shift_deltas(delta: float | tuple[float, float]) -> tuple[float, float]:
    if isinstance(delta, (tuple, list)):
        return (float(delta[0]), float(delta[1]))
    value = float(delta)
    return (value, value)


def _fuzzy_distractor_ledger(row: FuzzyRow) -> tuple[tuple[str, float, str], ...]:
    same_slot = "banana" if row.food_id == "oats" else "oats"
    other_slot = "today-lunch" if row.slot == "today-breakfast" else "today-breakfast"
    return (
        ("apple", FUZZY_DISTRACTORS["apple"], "yesterday-snack"),
        ("orange", FUZZY_DISTRACTORS["orange"], other_slot),
        (same_slot, FUZZY_DISTRACTORS[same_slot], row.slot),
    )


def _log_distractor_ledger(slot: str) -> tuple[tuple[str, float, str], ...]:
    return (
        ("apple", FUZZY_DISTRACTORS["apple"], "yesterday-snack"),
        ("orange", FUZZY_DISTRACTORS["orange"], slot),
    )


def _log_allergies(catalog: Mapping, food_ids: list[str]) -> tuple[str, ...]:
    carried: set[str] = set()
    for food_id in food_ids:
        carried.update((catalog.get(food_id) or {}).get("allergen_tags") or [])
    return tuple(tag for tag in ("peanut",) if tag not in carried)
