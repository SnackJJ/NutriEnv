"""Fail-closed back-resolve, containment, leak, and near-duplicate gates."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from nutrienv.bench.occasions import (
    REC_OCCASION_AFTER,
    occasion_from_query,
    occasion_from_stamp,
)
from nutrienv.bench.realize import (
    FUZZY_DISTRACTORS,
    GOLD_WINDOWS,
    Material,
    Oracle,
    Task,
    compose_oracles,
    realize,
)
from nutrienv.bench.realizations import EvaluateRow, MultiItemLogRow
from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.daily_windows import plan_windows_for_meal
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import WorldState, ledger_totals, normalize_tags

from .expander import match_pool_food
from .roster import ROSTER, profile_for
from .types import COMPOSITE_FAMILY, COMPOSITE_STEPS, Candidate, FoodPool, Rejected

__all__ = [
    "match_spoken",
    "query_backresolves_oracle",
    "resolve_candidate",
    "spoken_grams_from_query",
]

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
    skip_gram_backresolve: bool = False,
    pool: FoodPool | None = None,
) -> tuple[object, Rejected | None]:
    """Build a Task or a rejection. ``seen`` is the resolved-id multiset set.

    When ``skip_gram_backresolve`` is true, query speech checks (back-resolve
    and containment) are left to the semantic vote; the payload items are
    still bound to pool/catalog table grams.
    """
    index = food_index if food_index is not None else build_food_index(catalog)
    resolved: list[tuple[str, str, float]] = []
    for spoken, expression in candidate.items:
        food_id = match_spoken(spoken, catalog, index, pool)
        if food_id is None:
            return None, Rejected(candidate.query, "unresolvable", candidate.family)
        grams = resolve_portion(food_id, expression, catalog)
        if grams is None:
            return None, Rejected(candidate.query, "unresolvable", candidate.family)
        resolved.append((food_id, expression, float(grams)))

    if _leaks(candidate.query, catalog):
        return None, Rejected(candidate.query, "leak", candidate.family)

    # Recommend/update oracles carry no bound grams (free plan / profile
    # patch), so there is nothing to gram-backresolve; the spoken foods are
    # still context and the query must name them (containment below).
    context_only = candidate.family in {"recommend", "update"}
    if not skip_gram_backresolve and not context_only:
        for food_id, expression, grams in resolved:
            if not query_backresolves_oracle(
                candidate.query, food_id, expression, grams, catalog
            ):
                return None, Rejected(candidate.query, "backresolve", candidate.family)

    if not skip_gram_backresolve:
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


def query_backresolves_oracle(
    query: str,
    food_id: str,
    expression: str,
    oracle_grams: float,
    catalog: Mapping,
) -> bool:
    """True when a spoken phrase in ``query`` resolves to the oracle grams.

    Oracle grams stay the PortionFact value from ``expression``. This only
    checks that the query itself back-resolves to that same number.
    """
    target = round(float(oracle_grams), 2)
    for phrase in _query_portion_phrases(query, food_id, catalog, expression):
        resolved = resolve_portion(food_id, phrase, catalog)
        if resolved is not None and round(float(resolved), 2) == target:
            return True
    return False


def _phrase_in_query(phrase: str, query: str) -> bool:
    text = phrase.strip().lower()
    if not text:
        return False
    return re.search(rf"(?<![\w]){re.escape(text)}(?![\w])", query.lower()) is not None


def _food_spoken_names(food_id: str, catalog: Mapping) -> list[str]:
    entry = catalog.get(food_id) or {}
    names = [food_id.replace("_", " ")]
    name = str(entry.get("name") or "")
    if name.strip():
        names.append(name)
        if "," in name:
            names.append(name.split(",", 1)[0])
    names.extend(str(alias) for alias in (entry.get("aliases") or []))
    return names


def _query_portion_phrases(
    query: str, food_id: str, catalog: Mapping, expression: str
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def _add(phrase: str) -> None:
        text = phrase.strip()
        if text and text.lower() not in seen:
            seen.add(text.lower())
            found.append(text)

    if _phrase_in_query(expression, query):
        _add(expression)
    lowered = query.lower()
    for name in _food_spoken_names(food_id, catalog):
        needle = name.strip().lower()
        if len(needle) < 3:
            continue
        for match in re.finditer(rf"(?<![\w]){re.escape(needle)}(?![\w])", lowered):
            tokens = re.findall(r"[a-z0-9.]+", lowered[: match.start()])
            _add(needle)
            for width in range(1, min(6, len(tokens)) + 1):
                head = " ".join(tokens[-width:])
                _add(head)
                _add(f"{head} {needle}")
            trimmed = list(tokens)
            while trimmed and trimmed[-1] in {"of", "in", "the", "a", "an"}:
                trimmed.pop()
                for width in range(1, min(6, len(trimmed)) + 1):
                    head = " ".join(trimmed[-width:])
                    _add(head)
                    _add(f"{head} {needle}")
    return found


def spoken_grams_from_query(
    query: str,
    food_id: str,
    catalog: Mapping,
    expression: str = "",
) -> float | None:
    """Longest resolvable spoken amount in ``query`` for ``food_id``, or None."""
    phrases = _query_portion_phrases(query, food_id, catalog, expression)
    for phrase in sorted(phrases, key=len, reverse=True):
        resolved = resolve_portion(food_id, phrase, catalog)
        if resolved is not None:
            return float(resolved)
    return None


def match_spoken(
    token: str,
    catalog: Mapping,
    index: Mapping[str, str],
    pool: FoodPool | None,
) -> str | None:
    """Prefer a unique pool hit (FNDDS short names), then the catalog index."""
    if pool is not None:
        hit = match_pool_food(token, pool)
        if hit is not None:
            return hit
    return match_food(token, catalog, index)


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
    if candidate.family == "recommend":
        return _realize_recommend(candidate, catalog, task_id)
    if candidate.family == "update":
        return _realize_update(candidate, resolved, catalog, task_id)
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
    is_composite = candidate.family == COMPOSITE_FAMILY or len(candidate.steps) > 1
    row = MultiItemLogRow(task_id, candidate.query, pairs, _LOG_SLOT)
    material = Material(
        row=row,
        family="log",
        situations=("multi_item_log",),
        persona=candidate.persona,
        task_id=task_id,
        user_id=task_id,
        allergies=allergies,
        # ADR 0014: a composite recommend leg is judged on all six catalog
        # nutrients, so its profile carries a roster person's full derived
        # windows — the same source the mill uses — not the two-key legacy
        # GOLD_WINDOWS fixture.
        windows=_composite_windows() if is_composite else dict(GOLD_WINDOWS),
        ledger=_log_distractor_ledger(_LOG_SLOT),
    )
    task = realize(material, candidate.query, catalog=catalog)
    if is_composite:
        return _attach_recommend(task, candidate)
    return task


def _composite_windows() -> dict:
    """Full six-key derived windows for synthetic composite drafts."""
    return dict(profile_for(ROSTER[0]).windows)


def _attach_recommend(task, candidate: Candidate):
    steps = candidate.steps or COMPOSITE_STEPS
    if steps != COMPOSITE_STEPS:
        raise ValueError(f"unsupported composite steps: {steps}")
    log_oracle = task.oracle
    tail = list(log_oracle.ledger_tail or [])
    if not tail:
        raise ValueError("composite log sub-oracle has no ledger_tail")
    final_ledger = (*task.s0.ledger, *tail)
    # ADR 0014: plan_windows is meal-slot ∩ remainder after the log tail,
    # the same helper and convention the generate_one mill pins.
    stamped = occasion_from_stamp(str(tail[-1].eaten_at))
    if stamped is None:
        raise ValueError("composite recommend occasion unresolved")
    eaten = ledger_totals(list(final_ledger), task.s0.catalog)
    plan_windows = plan_windows_for_meal(
        task.s0.profile.windows, eaten, REC_OCCASION_AFTER[stamped]
    )
    if plan_windows is None:
        raise ValueError("composite recommend windows are empty")
    rec_oracle = Oracle(
        profile=copy.deepcopy(task.s0.profile),
        last_plan=[],
        ledger_tail=list(tail),
        ledger=final_ledger,
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
    )
    return replace(task, oracle=compose_oracles(log_oracle, rec_oracle))


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


def _realize_recommend(candidate: Candidate, catalog, task_id: str) -> Task:
    """Synthetic recommend draft: a free plan pinned to meal-slot windows.

    The named foods stay spoken context (the oracle judges any
    allergen-safe plan inside the windows); windows derive from a roster
    person's six-key daily table -- the same source the composite recommend
    leg uses. The occasion comes from the spoken "for <meal>" word.
    """
    profile = profile_for(ROSTER[0])
    occasion = occasion_from_query(candidate.query)
    if occasion is None:
        # occasions.py contract: an unresolved occasion fails loudly instead
        # of silently pinning dinner geometry.
        raise ValueError("recommend query names no meal occasion")
    plan_windows = plan_windows_for_meal(_composite_windows(), {}, occasion)
    if plan_windows is None:
        raise ValueError("recommend windows are empty")
    oracle = Oracle(
        profile=copy.deepcopy(profile),
        last_plan=[],
        plan_must_be_safe=True,
        plan_must_fit_windows=True,
        plan_windows=plan_windows,
        ledger=(),
    )
    s0 = WorldState(profile=copy.deepcopy(profile), ledger=[], catalog=catalog)
    return Task(task_id, "recommend", candidate.query, s0, oracle, (), candidate.persona)


def _realize_update(
    candidate: Candidate,
    resolved: Sequence[tuple[str, str, float]],
    catalog,
    task_id: str,
) -> Task:
    """Synthetic add-allergy update draft.

    The query names a food; that food's catalog allergen tags (not already
    on the roster profile) become the oracle's added allergies, so the
    change is always evidenced in the query. Windows stay untouched, so
    they remain world-derived and need no spoken magnitudes.
    """
    profile = profile_for(ROSTER[0])
    added: set[str] = set()
    for food_id, _expression, _grams in resolved:
        tags = (catalog.get(food_id) or {}).get("allergen_tags") or ()
        added.update(str(tag) for tag in tags if tag not in profile.allergies)
    if not added:
        raise ValueError("update names no food carrying a new allergen tag")
    expected = replace(
        profile, allergies=normalize_tags([*profile.allergies, *sorted(added)])
    )
    if expected.allergies == profile.allergies:
        raise ValueError("update has no effect on the profile")
    oracle = Oracle(profile=expected, ledger=())
    s0 = WorldState(profile=copy.deepcopy(profile), ledger=[], catalog=catalog)
    return Task(task_id, "update", candidate.query, s0, oracle, (), candidate.persona)
