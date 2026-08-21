"""Code-side Evaluate knives. Grams stay table values; LLM only rewrites speech."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from nutrienv.bench.realize import bind_evaluate_reasons
from nutrienv.world.types import MAX_ITEM_GRAMS, Profile, normalize_tags

from .semantic_vote import GRAM_TOLERANCE
from .types import FoodPool, PoolFood

__all__ = ["KNIVES", "apply_knife"]

KNIFE_ALLERGY = "allergy"
KNIFE_OVER_SLOT = "over_slot"
KNIFE_UNDER_SLOT = "under_slot"
KNIFE_SWAP = "swap"
KNIVES: tuple[str, ...] = (
    KNIFE_ALLERGY,
    KNIFE_OVER_SLOT,
    KNIFE_UNDER_SLOT,
    KNIFE_SWAP,
)


def apply_knife(
    knife: str,
    items: Sequence[Mapping[str, object]],
    *,
    profile: Profile,
    catalog: Mapping,
    pool: FoodPool,
    windows: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]] | None:
    """Perturb a bind-confirmed fit plate until the knife predicate can hold."""
    plate = [
        {"food_id": str(item["food_id"]), "grams": float(item["grams"])}
        for item in items
    ]
    if knife == KNIFE_ALLERGY:
        return _allergy(plate, profile=profile, catalog=catalog, pool=pool)
    if knife == KNIFE_OVER_SLOT:
        return _over_slot(
            plate, profile=profile, catalog=catalog, pool=pool, windows=windows
        )
    return None


def _over_slot(
    plate: list[dict[str, object]],
    *,
    profile: Profile,
    catalog: Mapping,
    pool: FoodPool,
    windows: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]] | None:
    """One catalog-legal bump, or one ordinary accompaniment. Do not double."""
    for index, item in enumerate(plate):
        bumped = _next_portion(item, pool)
        if bumped is None or _cartoon_item(bumped):
            continue
        candidate = plate[:index] + [bumped] + plate[index + 1 :]
        if _fires_hi(candidate, windows, catalog, profile.allergies):
            return candidate
    present = {str(item["food_id"]) for item in plate}
    for food in pool.foods:
        if food.food_id in present:
            continue
        grams = _one_portion_grams(food)
        if grams is None:
            continue
        extra = {"food_id": food.food_id, "grams": grams}
        if _cartoon_item(extra):
            continue
        candidate = plate + [extra]
        if _fires_hi(candidate, windows, catalog, profile.allergies):
            return candidate
    return None


def _next_portion(
    item: Mapping[str, object], pool: FoodPool
) -> dict[str, object] | None:
    food = next((row for row in pool.foods if row.food_id == item["food_id"]), None)
    if food is None:
        return None
    current = float(item["grams"])
    higher = [alt for alt in food.alternatives if alt.grams > current + 1e-9]
    if not higher:
        return None
    alt = min(higher, key=lambda row: row.grams)
    return {"food_id": food.food_id, "grams": float(alt.grams)}


def _fires_hi(
    plate: Sequence[Mapping[str, object]],
    windows: Mapping[str, tuple[float, float]],
    catalog: Mapping,
    allergies: tuple[str, ...],
) -> bool:
    reasons = bind_evaluate_reasons(list(plate), dict(windows), catalog, allergies)
    return any(code.endswith("_hi") for code in reasons)


def _cartoon_item(item: Mapping[str, object]) -> bool:
    return float(item["grams"]) > MAX_ITEM_GRAMS


def _allergy(
    plate: list[dict[str, object]],
    *,
    profile: Profile,
    catalog: Mapping,
    pool: FoodPool,
) -> list[dict[str, object]] | None:
    banned = set(normalize_tags(list(profile.allergies)))
    if not banned:
        return None
    present = {str(item["food_id"]) for item in plate}
    for food in pool.foods:
        if food.food_id in present:
            continue
        entry = catalog.get(food.food_id) or {}
        tags = set(normalize_tags(list(entry.get("allergen_tags") or [])))
        if not (tags & banned):
            continue
        grams = _one_portion_grams(food)
        if grams is None:
            continue
        return plate + [{"food_id": food.food_id, "grams": grams}]
    return None


def _one_portion_grams(food: PoolFood) -> float | None:
    for alt in food.alternatives:
        if alt.quantity == 1.0 and alt.grams > GRAM_TOLERANCE:
            return float(alt.grams)
    return None
