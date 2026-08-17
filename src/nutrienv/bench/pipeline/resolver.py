"""Fail-closed back-resolve, containment, leak, and near-duplicate gates."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import replace

from nutrienv.bench.realize import (
    FUZZY_DISTRACTORS,
    GOLD_WINDOWS,
    Material,
    Oracle,
    compose_oracles,
    realize,
)
from nutrienv.bench.realizations import EvaluateRow, MultiItemLogRow
from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import ledger_totals

from .types import COMPOSITE_FAMILY, COMPOSITE_STEPS, Candidate, Rejected

__all__ = ["resolve_candidate"]

_LOG_SLOT = "today-lunch"

# Same spirit as validator.validate_draft leak regexes.
_WINDOW_LEAK = re.compile(r"\b(?:kcal|protein_g|carb_g|fat_g)\s+\d")
_SLUG = re.compile(r"\b[a-z]+_[a-z0-9_]+\b")


def resolve_candidate(
    candidate: Candidate,
    *,
    catalog: Mapping,
    task_id: str,
    seen: set[tuple[str, ...]],
    food_index: Mapping[str, str] | None = None,
) -> tuple[object, Rejected | None]:
    """Build a Task or a rejection. ``seen`` is the resolved-id multiset set."""
    index = food_index if food_index is not None else build_food_index(catalog)
    resolved: list[tuple[str, str, float]] = []
    for spoken, expression in candidate.items:
        food_id = match_food(spoken, catalog, index)
        if food_id is None:
            return None, Rejected(candidate.query, "unresolvable", candidate.family)
        grams = resolve_portion(food_id, expression, catalog)
        if grams is None:
            return None, Rejected(candidate.query, "unresolvable", candidate.family)
        resolved.append((food_id, expression, float(grams)))

    if _leaks(candidate.query, catalog):
        return None, Rejected(candidate.query, "leak", candidate.family)

    for food_id, _expression, _grams in resolved:
        if not _mentioned(food_id, catalog, candidate.query, candidate.items):
            return None, Rejected(candidate.query, "containment", candidate.family)

    key = tuple(sorted(food_id for food_id, _expression, _grams in resolved))
    if candidate.family == COMPOSITE_FAMILY or len(candidate.steps) > 1:
        key = ("__composite__",) + key
    if key in seen:
        return None, Rejected(candidate.query, "duplicate", candidate.family)
    seen.add(key)

    try:
        task = _realize(candidate, resolved, catalog, task_id)
    except (RuntimeError, ValueError, TypeError):
        return None, Rejected(candidate.query, "unresolvable", candidate.family)
    return task, None


def build_food_index(catalog: Mapping) -> dict[str, str]:
    """Map lowercase id / name / alias → canonical food id. First sorted wins."""
    index: dict[str, str] = {}
    for food_id in sorted(catalog):
        entry = catalog.get(food_id)
        if not isinstance(entry, dict):
            continue
        canon = canonical_food_id(catalog, food_id)
        keys = {food_id.lower(), canon.lower()}
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            keys.add(name.strip().lower())
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str) and alias.strip():
                keys.add(alias.strip().lower())
        for key in keys:
            index.setdefault(key, canon)
    return index


def match_food(token: str, catalog: Mapping, index: Mapping[str, str]) -> str | None:
    raw = token.strip()
    if not raw:
        return None
    if raw in catalog:
        return canonical_food_id(catalog, raw)
    hit = index.get(raw.lower())
    if hit is None:
        return None
    if hit not in catalog and raw not in catalog:
        return None
    return hit


def _leaks(query: str, catalog: Mapping) -> bool:
    lowered = query.lower()
    if "catalog id" in lowered or "food_id" in lowered:
        return True
    if _WINDOW_LEAK.search(query):
        return True
    for token in _SLUG.findall(lowered):
        if token in catalog:
            return True
    return False


def _mentioned(
    food_id: str,
    catalog: Mapping,
    query: str,
    items: tuple[tuple[str, str], ...],
) -> bool:
    entry = catalog.get(food_id) or {}
    needles = [
        food_id.replace("_", " "),
        str(entry.get("name") or ""),
    ]
    name = str(entry.get("name") or "")
    if "," in name:
        needles.append(name.split(",", 1)[0])
    needles.extend(str(alias) for alias in (entry.get("aliases") or []))
    needles.extend(spoken for spoken, _expression in items)
    lowered = query.lower()
    for needle in needles:
        text = str(needle).strip().lower()
        if len(text) < 3:
            continue
        if re.search(rf"(?<![\w]){re.escape(text)}(?![\w])", lowered):
            return True
    return False


def _realize(
    candidate: Candidate,
    resolved: list[tuple[str, str, float]],
    catalog: Mapping,
    task_id: str,
) -> object:
    food_ids = [food_id for food_id, _expression, _grams in resolved]
    pairs = tuple((food_id, expression) for food_id, expression, _grams in resolved)
    allergies = _log_allergies(catalog, food_ids)
    if candidate.family == "evaluate":
        row = EvaluateRow(task_id, candidate.query, pairs)
        material = Material(
            row=row,
            family="evaluate",
            situations=(),
            persona=candidate.persona,
            task_id=task_id,
            user_id=task_id,
            allergies=allergies,
        )
        return realize(material, candidate.query, catalog=catalog)
    row = MultiItemLogRow(task_id, candidate.query, pairs, _LOG_SLOT)
    material = Material(
        row=row,
        family="log",
        situations=("multi_item_log",),
        persona=candidate.persona,
        task_id=task_id,
        user_id=task_id,
        allergies=allergies,
        windows=dict(GOLD_WINDOWS),
        ledger=_log_distractor_ledger(_LOG_SLOT),
    )
    task = realize(material, candidate.query, catalog=catalog)
    if candidate.family == COMPOSITE_FAMILY or len(candidate.steps) > 1:
        return _attach_recommend(task, candidate)
    return task


def _attach_recommend(task, candidate: Candidate):
    steps = candidate.steps or COMPOSITE_STEPS
    if steps != COMPOSITE_STEPS:
        raise ValueError(f"unsupported composite steps: {steps}")
    log_oracle = task.oracle
    tail = list(log_oracle.ledger_tail or [])
    if not tail:
        raise ValueError("composite log sub-oracle has no ledger_tail")
    final_ledger = (*task.s0.ledger, *tail)
    rec_oracle = Oracle(
        profile=copy.deepcopy(task.s0.profile),
        last_plan=[],
        ledger_tail=list(tail),
        ledger=final_ledger,
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=_remainder_after(task.s0, tail),
    )
    return replace(task, oracle=compose_oracles(log_oracle, rec_oracle))


def _remainder_after(s0, extra_rows) -> dict[str, tuple[float, float]]:
    eaten = ledger_totals([*s0.ledger, *extra_rows], s0.catalog)
    remain: dict[str, tuple[float, float]] = {}
    for key, (lo, hi) in s0.profile.windows.items():
        used = eaten.get(key, 0.0)
        remain[key] = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
    return remain


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
