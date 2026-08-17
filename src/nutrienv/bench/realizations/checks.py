"""Row-level admission asserts for realization tables."""

from __future__ import annotations

from nutrienv.bench.windows import any_pair_unsatisfiable
from nutrienv.world.portions import resolve_portion

from .tables import (
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
)
from .types import (
    constrain_key,
    evaluate_key,
    fuzzy_key,
    ledger_gap_key,
    leftover_key,
    multi_item_log_key,
    near_synonym_key,
    recommend_key,
    unit_convert_key,
    update_key,
)

__all__ = [
    "assert_fuzzy_resolves",
    "assert_log_situation_rows",
    "assert_leftover_rows",
    "assert_update_rows",
    "assert_constrain_rows",
    "assert_evaluate_rows",
    "assert_recommend_rows",
]

def _catalog_tags(catalog) -> set[str]:
    tags: set[str] = set()
    for entry in catalog.values():
        for tag in entry.get("allergen_tags") or []:
            tags.add(str(tag))
    return tags


_BANNED_PAIRS = frozenset(
    {("whole_wheat_bread", "a slice"), ("broccoli", "a piece")}
)


def assert_fuzzy_resolves(catalog) -> None:
    """Raise if any table row cannot be converted by the live catalog."""
    seen: set[tuple] = set()
    for row in FUZZY_ROWS:
        grams = resolve_portion(row.food_id, row.phrase, catalog)
        if grams is None:
            raise RuntimeError(f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}")
        key = fuzzy_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate fuzzy key {key}")
        seen.add(key)


def assert_log_situation_rows(catalog) -> None:
    """Raise if a multi-item / unit / synonym / gap row cannot be realized."""
    seen: set[tuple] = set()
    for row in MULTI_ITEM_LOG_ROWS:
        if not (2 <= len(row.items) <= 4):
            raise RuntimeError(f"{row.seed_id} must log 2-4 items")
        for food_id, phrase in row.items:
            if (food_id, phrase) in _BANNED_PAIRS:
                raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
            if resolve_portion(food_id, phrase, catalog) is None:
                raise RuntimeError(
                    f"{row.seed_id} does not resolve {phrase!r} for {food_id}"
                )
        key = multi_item_log_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in UNIT_CONVERT_ROWS:
        if (row.food_id, row.phrase) in _BANNED_PAIRS:
            raise RuntimeError(f"{row.seed_id} uses banned pair {row.food_id} {row.phrase!r}")
        if resolve_portion(row.food_id, row.phrase, catalog) is None:
            raise RuntimeError(
                f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}"
            )
        key = unit_convert_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in NEAR_SYNONYM_ROWS:
        if row.food_id not in catalog:
            raise RuntimeError(f"{row.seed_id} food {row.food_id} is not in the catalog")
        aliases = {str(alias).lower() for alias in (catalog[row.food_id].get("aliases") or [])}
        if row.spoken.lower() not in aliases:
            raise RuntimeError(
                f"{row.seed_id} spoken {row.spoken!r} is not an alias of {row.food_id}"
            )
        if row.spoken.lower() == row.food_id.lower():
            raise RuntimeError(f"{row.seed_id} spoken name is the slug")
        if resolve_portion(row.food_id, row.phrase, catalog) is None:
            raise RuntimeError(
                f"{row.seed_id} does not resolve {row.phrase!r} for {row.food_id}"
            )
        key = near_synonym_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)
    for row in LEDGER_GAP_ROWS:
        food_id, phrase, slot = row.missing
        if (food_id, phrase) in _BANNED_PAIRS:
            raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
        if resolve_portion(food_id, phrase, catalog) is None:
            raise RuntimeError(f"{row.seed_id} does not resolve {phrase!r} for {food_id}")
        surround_slots = {eaten_at for _food, _grams, eaten_at in row.surround}
        if slot in surround_slots:
            raise RuntimeError(f"{row.seed_id} missing slot {slot} is already in S0")
        if not row.surround:
            raise RuntimeError(f"{row.seed_id} has no surrounding ledger rows")
        for surround_food, _grams, _eaten_at in row.surround:
            if surround_food not in catalog:
                raise RuntimeError(f"{row.seed_id} surround food {surround_food} is not in the catalog")
        key = ledger_gap_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate log key {key}")
        seen.add(key)


def assert_leftover_rows(catalog) -> None:
    seen: set[tuple] = set()
    for row in LEFTOVER_ROWS:
        for food_id, _grams, _slot in row.ledger:
            if food_id not in catalog:
                raise RuntimeError(f"{row.seed_id} food {food_id} is not in the catalog")
        key = leftover_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate leftover key {key}")
        seen.add(key)


def assert_update_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in UPDATE_ROWS:
        for tag in (*row.add_allergens, *row.remove_allergens):
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = update_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate update key {key}")
        seen.add(key)


def assert_constrain_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in CONSTRAIN_ROWS:
        if row.kind not in {"condition", "conflict"}:
            raise RuntimeError(f"{row.seed_id} has unknown kind {row.kind!r}")
        if row.kind == "condition":
            if row.food_id is None or row.food_id not in catalog:
                raise RuntimeError(f"{row.seed_id} food {row.food_id} does not resolve")
            food_tags = set(catalog[row.food_id].get("allergen_tags") or [])
            if not food_tags.intersection(row.allergies):
                raise RuntimeError(f"{row.seed_id} food does not carry a listed allergy")
            if row.windows["kcal"][1] > 800:
                raise RuntimeError(f"{row.seed_id} meal kcal ceiling exceeds 800")
        else:
            if not row.last_plan:
                raise RuntimeError(f"{row.seed_id} conflict row has no violating plan")
            if not any_pair_unsatisfiable(row.windows, catalog, row.allergies):
                raise RuntimeError(f"{row.seed_id} windows are satisfiable")
        for tag in row.allergies:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = constrain_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate constrain key {key}")
        seen.add(key)


def assert_evaluate_rows(catalog) -> None:
    seen: set[tuple] = set()
    for row in EVALUATE_ROWS:
        for food_id, phrase in row.items:
            if (food_id, phrase) in _BANNED_PAIRS:
                raise RuntimeError(f"{row.seed_id} uses banned pair {food_id} {phrase!r}")
            if resolve_portion(food_id, phrase, catalog) is None:
                raise RuntimeError(f"{row.seed_id} does not resolve {phrase!r} for {food_id}")
        key = evaluate_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate evaluate key {key}")
        seen.add(key)


def assert_recommend_rows(catalog) -> None:
    tags = _catalog_tags(catalog)
    seen: set[tuple] = set()
    for row in RECOMMEND_ROWS:
        if row.persona == "leftover":
            raise RuntimeError(f"{row.seed_id} leftover recommend belongs in LEFTOVER_ROWS")
        for tag in row.allergies:
            if tag not in tags:
                raise RuntimeError(f"{row.seed_id} uses non-tag allergy {tag!r}")
        key = recommend_key(row)
        if key in seen:
            raise RuntimeError(f"duplicate recommend key {key}")
        seen.add(key)
