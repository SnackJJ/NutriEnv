"""Code-side Evaluate knives. Grams stay table values; LLM only rewrites speech."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from nutrienv.world.types import Profile, normalize_tags

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
) -> list[dict[str, object]] | None:
    """Perturb a bind-confirmed fit plate until the knife predicate can hold."""
    plate = [
        {"food_id": str(item["food_id"]), "grams": float(item["grams"])}
        for item in items
    ]
    if knife == KNIFE_ALLERGY:
        return _allergy(plate, profile=profile, catalog=catalog, pool=pool)
    return None


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
