"""Action dispatch: one handler per op, each total on a valid envelope.

Two invariants hold for every handler:

- Validate fully, then mutate. An :class:`ActionError` can never escape from a
  half-applied write, so an Illegal Action leaves the world byte-identical.
- Writes apply now (ADR 0004). There is no pending tray and no confirm step.
"""

from __future__ import annotations

import copy
from dataclasses import replace

from ..world.dri import BASIS, DRI_REFERENCE
from ..world.types import (
    LedgerRow,
    WorldState,
    food_view,
    ledger_view,
    normalize_grams,
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

__all__ = ["dispatch", "DEFAULT_EATEN_AT", "PROFILE_PATCH_KEYS"]

#: Deterministic stand-in for a clock. A wall-clock default would make the
#: ledger unpredictable, and Pass compares the end state to an Oracle.
DEFAULT_EATEN_AT = "now"

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
    """A food_id that must already be minted in this episode's catalog."""
    food_id = as_nonempty_str(value, "food_id")
    if food_id not in state.catalog:
        raise ActionError("unknown_food", f"no such food_id: {food_id!r}")
    return food_id


# --- reads ------------------------------------------------------------------


def _search_foods(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    needle = as_nonempty_str(args["q"], "q").lower()
    results = []
    for food_id, entry in state.catalog.items():
        haystack = [food_id, str(entry.get("name", ""))]
        haystack += [str(alias) for alias in entry.get("aliases", [])]
        if any(needle in text.lower() for text in haystack):
            results.append(
                {
                    "food_id": food_id,
                    "name": entry.get("name", ""),
                    "aliases": list(entry.get("aliases", [])),
                    "allergen_tags": list(entry.get("allergen_tags", [])),
                }
            )
    results.sort(key=lambda row: row["food_id"])
    return {"op": "search_foods", "q": needle, "results": results}


def _get_food(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    food_id = _resolve_food(state, args["food_id"])
    return {"op": "get_food", "food": food_view(state.catalog, food_id)}


def _get_profile(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {"op": "get_profile", "profile": profile_view(state.profile)}


def _get_ledger(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {"op": "get_ledger", "ledger": ledger_view(state.ledger)}


def _get_dri(state: WorldState, _args: dict, _default_eaten_at: str) -> dict:
    return {
        "op": "get_dri",
        "basis": BASIS,
        "reference": copy.deepcopy(DRI_REFERENCE),
        "windows": {key: list(win) for key, win in state.profile.windows.items()},
    }


# --- writes -----------------------------------------------------------------


def _log_meal(state: WorldState, args: dict, default_eaten_at: str) -> dict:
    food_id = _resolve_food(state, args["food_id"])
    try:
        grams = normalize_grams(args["grams"])
    except ValueError as exc:
        raise ActionError("bad_schema", f"'grams': {exc}") from exc
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
        try:
            grams = normalize_grams(item["grams"])
        except ValueError as exc:
            raise ActionError("bad_schema", f"items[{index}].grams: {exc}") from exc
        normalized.append({"food_id": food_id, "grams": grams})

    state.last_plan = normalized
    return {"op": "submit_plan", "items": copy.deepcopy(normalized)}


def _update_profile(state: WorldState, args: dict, _default_eaten_at: str) -> dict:
    patch = as_dict(args["patch"], "patch")
    unknown = sorted(patch.keys() - PROFILE_PATCH_KEYS)
    if unknown:
        raise ActionError("bad_schema", f"patch has non-patchable keys {unknown}")

    changes: dict = {}
    for field in ("allergies", "medications"):
        if field in patch:
            try:
                changes[field] = normalize_tags(patch[field])
            except ValueError as exc:
                raise ActionError("bad_schema", f"'{field}': {exc}") from exc

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
