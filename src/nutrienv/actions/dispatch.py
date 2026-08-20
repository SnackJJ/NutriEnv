"""Action dispatch: one handler per op, each total on a valid envelope.

Two invariants hold for every handler:

- Validate fully, then mutate. An :class:`ActionError` can never escape from a
  half-applied write, so an Illegal Action leaves the world byte-identical.
- Writes apply now (ADR 0004). There is no pending tray and no confirm step.
"""

from __future__ import annotations

import copy
import re
from dataclasses import replace

from ..world.catalog import canonical_food_id
from ..world.dri import BASIS, DRI_REFERENCE
from ..world.types import (
    ImplausibleQuantity,
    LedgerRow,
    WorldState,
    food_view,
    ledger_totals,
    ledger_view,
    normalize_grams,
    normalize_reasons,
    normalize_tags,
    normalize_window,
    profile_view,
)
from .schemas import (
    ActionError,
    as_dict,
    as_list,
    as_nonempty_str,
    validate_envelope,
)

__all__ = [
    "dispatch",
    "DEFAULT_EATEN_AT",
    "PROFILE_PATCH_KEYS",
    "SEARCH_ALL",
    "MAX_PLAN_GRAMS",
]

# Habitability bound on a submitted plan's total, not validation trivia. The
# per-item cap in normalize_grams is otherwise defeated by 35 items of 2000 g
# (the zero-kcal coffee exploit on v0-rec-conflict-001). The largest
# legitimate frozen-split plan is 670 g.
MAX_PLAN_GRAMS = 4000.0

#: Deterministic stand-in for a clock. A wall-clock default would make the
#: ledger unpredictable, and Pass compares the end state to an Oracle.
DEFAULT_EATEN_AT = "now"

#: The query that lists the whole catalog. Token-AND matching cannot express
#: "show me everything", so without it an agent that has seen no food_id yet
#: has to guess English food words to discover what the world contains.
SEARCH_ALL = "*"

#: Profile fields an ``update_profile`` patch may touch. ``user_id`` is identity,
#: not a nutrition field, so it is not patchable.
PROFILE_PATCH_KEYS = frozenset(
    {"allergies", "medications", "windows", "plan_preset", "version"}
)


def dispatch(
    state: WorldState, action: object, *, default_eaten_at: str = DEFAULT_EATEN_AT
) -> dict:
    """Run one Action against ``state``. Returns an observation.

    Raises :class:`ActionError` for an Illegal Action, having changed nothing.
    """
    op, args = validate_envelope(action)
    return _HANDLERS[op](state, args, default_eaten_at)


def _resolve_food(state: WorldState, value: object) -> str:
    """A food_id that must already be minted in this episode's catalog.

    Slugs such as ``milk_whole`` resolve to the official FDC id so a search
    hit and a gold-authored alias write the same ledger/plan identity.
    """
    food_id = as_nonempty_str(value, "food_id")
    if food_id not in state.catalog:
        raise ActionError("unknown_food", f"no such food_id: {food_id!r}")
    return canonical_food_id(state.catalog, food_id)


# --- reads ------------------------------------------------------------------


_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower().replace("_", " ")))


def _search_match(needle: str, food_id: str, entry: dict) -> bool:
    query = _tokens(needle)
    if not query:
        return False
    bag = set(_tokens(food_id))
    bag.update(_tokens(str(entry.get("name", ""))))
    for alias in entry.get("aliases") or []:
        bag.update(_tokens(str(alias)))
    return query <= bag


def _search_foods(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    """Ranked search. ``q="*"`` is not a catalog dump; send a food name."""
    needle = as_nonempty_str(args["q"], "q")
    catalog = state.catalog
    search = getattr(catalog, "search", None)
    if callable(search):
        results = search(needle)
    else:
        results = _search_mapping(catalog, needle.lower())
    return {"op": "search_foods", "q": needle, "results": results}


def _search_mapping(catalog: dict, needle: str) -> list[dict]:
    if needle == SEARCH_ALL or not needle:
        return []
    results = []
    for food_id, entry in catalog.items():
        if not isinstance(entry, dict):
            continue
        if _search_match(needle, food_id, entry):
            results.append(
                {
                    "food_id": food_id,
                    "name": entry.get("name", ""),
                    "aliases": list(entry.get("aliases", [])),
                    "allergen_tags": list(entry.get("allergen_tags", [])),
                }
            )
    results.sort(key=lambda row: row["food_id"])
    return results


def _get_food(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    food_id = _resolve_food(state, args["food_id"])
    return {"op": "get_food", "food": food_view(state.catalog, food_id)}


def _get_profile(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {
        "op": "get_profile",
        "profile": profile_view(state.profile),
        "last_plan": copy.deepcopy(state.last_plan),
        "last_verdict": state.last_verdict,
        "last_reasons": list(state.last_reasons),
    }


def _get_ledger(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {
        "op": "get_ledger",
        "ledger": ledger_view(state.ledger, state.catalog),
        "totals": ledger_totals(state.ledger, state.catalog),
    }


def _get_dri(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {
        "op": "get_dri",
        "basis": BASIS,
        "reference": copy.deepcopy(DRI_REFERENCE),
        "windows": {key: list(win) for key, win in state.profile.windows.items()},
    }


# --- writes -----------------------------------------------------------------


def _require_grams(value: object, label: str) -> float:
    try:
        return normalize_grams(value)
    except ImplausibleQuantity as exc:
        raise ActionError("implausible_quantity", f"{label}: {exc}") from exc
    except ValueError as exc:
        raise ActionError("bad_schema", f"{label}: {exc}") from exc


def _log_meal(state: WorldState, args: dict, default_eaten_at: str) -> dict:
    food_id = _resolve_food(state, args["food_id"])
    grams = _require_grams(args["grams"], "'grams'")
    eaten_at = (
        as_nonempty_str(args["eaten_at"], "eaten_at")
        if "eaten_at" in args
        else default_eaten_at
    )

    row = LedgerRow(food_id=food_id, grams=grams, eaten_at=eaten_at)
    state.ledger.append(row)
    return {
        "op": "log_meal",
        "row": {"food_id": row.food_id, "grams": row.grams, "eaten_at": row.eaten_at},
        "ledger_size": len(state.ledger),
    }


def _submit_plan(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    items = as_list(args["items"], "items")
    normalized: list[dict] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ActionError("bad_schema", f"items[{index}] must be a dict")
        extra = sorted(item.keys() - {"food_id", "grams"})
        if extra:
            raise ActionError("bad_schema", f"items[{index}] got unexpected keys {extra}")
        if "food_id" not in item or "grams" not in item:
            raise ActionError("bad_schema", f"items[{index}] needs food_id and grams")
        food_id = _resolve_food(state, item["food_id"])
        grams = _require_grams(item["grams"], f"items[{index}].grams")
        normalized.append({"food_id": food_id, "grams": grams})

    total = sum(item["grams"] for item in normalized)
    if total > MAX_PLAN_GRAMS:
        raise ActionError(
            "implausible_quantity",
            f"plan total {total:g} g exceeds {MAX_PLAN_GRAMS:g} g",
        )

    verdict = (
        as_nonempty_str(args["verdict"], "verdict") if "verdict" in args else None
    )
    if verdict is not None and verdict not in {"accept", "reject"}:
        raise ActionError("bad_schema", "verdict must be 'accept' or 'reject'")

    reasons = None
    if "reasons" in args:
        try:
            reasons = normalize_reasons(args["reasons"])
        except ValueError as exc:
            raise ActionError("bad_schema", f"'reasons': {exc}") from exc

    if verdict is None:
        if reasons is not None:
            raise ActionError("bad_schema", "reasons require a verdict")
        if normalized:
            state.last_plan = normalized
            state.last_verdict = "accept"
            state.last_reasons = ()
        else:
            state.last_plan = []
            state.last_verdict = None
            state.last_reasons = ()
        return {"op": "submit_plan", "items": copy.deepcopy(state.last_plan)}

    if verdict == "accept":
        if not normalized:
            raise ActionError("bad_schema", "accept requires a non-empty plan")
        if reasons:
            raise ActionError("bad_schema", "accept cannot include reasons")
        state.last_plan = normalized
        state.last_verdict = "accept"
        state.last_reasons = ()
        return {"op": "submit_plan", "items": copy.deepcopy(normalized)}

    if normalized:
        raise ActionError("bad_schema", "reject requires empty items")
    state.last_plan = []
    state.last_verdict = "reject"
    state.last_reasons = reasons if reasons is not None else ()
    return {"op": "submit_plan", "items": []}


def _expand_food_allergies(state: WorldState, tags: tuple[str, ...]) -> tuple[str, ...]:
    """A food_id in an allergy patch means that food's allergen tags.

    ``shrimp`` is a catalog id whose tag is ``shellfish``. Writing the food
    name is a valid way to name the constraint; the stored profile keeps tags.
    """
    expanded: list[str] = []
    for tag in tags:
        entry = state.catalog.get(tag)
        if isinstance(entry, dict):
            food_tags = entry.get("allergen_tags") or []
            if food_tags:
                expanded.extend(str(item) for item in food_tags)
                continue
        expanded.append(tag)
    return normalize_tags(expanded)


def _update_profile(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    patch = as_dict(args["patch"], "patch")
    unknown = sorted(patch.keys() - PROFILE_PATCH_KEYS)
    if unknown:
        raise ActionError("bad_schema", f"patch has non-patchable keys {unknown}")

    changes: dict = {}
    for field in ("allergies", "medications"):
        if field in patch:
            try:
                raw = normalize_tags(patch[field])
            except ValueError as exc:
                raise ActionError("bad_schema", f"'{field}': {exc}") from exc
            if field == "allergies":
                raw = _expand_food_allergies(state, raw)
            changes[field] = raw

    if "windows" in patch:
        incoming = as_dict(patch["windows"], "windows")
        windows = dict(state.profile.windows)
        for key, value in incoming.items():
            name = as_nonempty_str(key, "windows key")
            try:
                windows[name] = normalize_window(value)
            except ValueError as exc:
                raise ActionError("bad_schema", f"windows[{name!r}]: {exc}") from exc
        changes["windows"] = windows

    if "plan_preset" in patch:
        incoming = as_dict(patch["plan_preset"], "plan_preset")
        changes["plan_preset"] = {
            **state.profile.plan_preset,
            **copy.deepcopy(incoming),
        }

    if "version" in patch:
        version = patch["version"]
        if isinstance(version, bool) or not isinstance(version, int):
            raise ActionError("bad_schema", "'version' must be an int")
        changes["version"] = version

    state.profile = replace(state.profile, **changes)
    return {"op": "update_profile", "profile": profile_view(state.profile)}


def _update_plan(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    patch = as_dict(args["patch"], "patch")
    plan_preset = {**state.profile.plan_preset, **copy.deepcopy(patch)}
    state.profile = replace(state.profile, plan_preset=plan_preset)
    return {"op": "update_plan", "plan_preset": copy.deepcopy(plan_preset)}


_HANDLERS = {
    "search_foods": _search_foods,
    "get_food": _get_food,
    "get_profile": _get_profile,
    "get_ledger": _get_ledger,
    "get_dri": _get_dri,
    "log_meal": _log_meal,
    "submit_plan": _submit_plan,
    "update_profile": _update_profile,
    "update_plan": _update_plan,
}
