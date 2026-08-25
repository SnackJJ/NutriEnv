"""Deterministic over-supply food pools from an injected catalog."""

from __future__ import annotations

import random
from collections.abc import Mapping

from nutrienv.world.catalog import canonical_food_id
from nutrienv.world.types import normalize_tags

from .types import (
    POOL_SIZE,
    QUANTITY_MULTIPLES,
    FoodPool,
    PoolFood,
    PortionAlternative,
)

__all__ = ["sample_pools", "portion_alternatives"]

# Spoken forms resolve_portion can actually parse. Catalog-v1 also stores
# cubic_inch; that key has no grammar, so the sampler drops it.
_COUNTABLE: dict[str, tuple[str, str]] = {
    "cup": ("cup", "cups"),
    "tbsp": ("tablespoon", "tablespoons"),
    "tsp": ("teaspoon", "teaspoons"),
    "piece": ("piece", "pieces"),
    "slice": ("slice", "slices"),
    "can": ("can", "cans"),
    "serving": ("serving", "servings"),
    # Food-specific count units (catalog-v2 rebuild, batch 2026-08-25).
    "wing": ("wing", "wings"),
    "drummette": ("drummette", "drummettes"),
    "scoop": ("scoop", "scoops"),
    "patty": ("patty", "patties"),
    "pat": ("pat", "pats"),
    "packet": ("packet", "packets"),
    "pouch": ("pouch", "pouches"),
    "bar": ("bar", "bars"),
    "stick": ("stick", "sticks"),
}
_MASS = {"oz": "oz", "fl_oz": "fl oz"}
_MODIFIERS = frozenset({"thick", "thin", "regular"})


def sample_pools(
    catalog: Mapping,
    *,
    seed: int,
    family: str,
    n_pools: int,
    pool_size: int = POOL_SIZE,
    spoken_only: bool = False,
    with_allergen: str | None = None,
) -> list[FoodPool]:
    """Draw ``n_pools`` independent pools of ~``pool_size`` foods.

    Uses ``random.Random(seed)`` only. Eligible foods are those with at least
    one PortionFact the grammar can speak. When ``spoken_only`` is true, foods
    whose only speakable portion is a plain cup are excluded, so the pool can
    contain snacks and milk rather than only solid-cup mains. Pool membership
    is sorted then sampled so the same seed yields the same pools.

    With ``with_allergen``, each drawn pool must contain at least one food
    carrying that catalog allergen tag: a draw without one has one slot
    replaced by a deterministically chosen carrier (so the carrier lands at a
    random index), and a catalog with no such food raises fail-closed.
    """
    if n_pools <= 0:
        return []
    eligible = _eligible_foods(catalog)
    if spoken_only:
        eligible = [food_id for food_id in eligible if not _cup_only(catalog, food_id)]
    if not eligible:
        raise ValueError("catalog has no foods with speakable PortionFacts")
    carriers = None
    if with_allergen is not None:
        # Same normalization the catalog tags go through, so "Egg" finds "egg".
        normalized = normalize_tags([with_allergen])
        tag = normalized[0] if normalized else with_allergen
        carriers = {
            food_id
            for food_id in eligible
            if tag
            in normalize_tags(
                list((catalog.get(food_id) or {}).get("allergen_tags") or [])
            )
        }
        if not carriers:
            raise ValueError(f"catalog has no food with allergen tag {tag!r}")
    rng = random.Random(seed)
    pools: list[FoodPool] = []
    size = min(pool_size, len(eligible))
    for index in range(n_pools):
        picked = list(rng.sample(eligible, size))
        if carriers is not None and not set(picked) & carriers:
            # Guarantee the carrier condition: on huge catalogs a pure
            # re-draw almost never hits, so swap a randomly chosen slot for
            # a deterministically chosen carrier.
            picked[rng.randrange(len(picked))] = rng.choice(sorted(carriers))
        foods = tuple(_pool_food(catalog, food_id) for food_id in picked)
        pools.append(
            FoodPool(
                pool_id=f"{family}-{index:04d}",
                family=family,
                foods=foods,
            )
        )
    return pools


def portion_alternatives(entry: Mapping) -> tuple[PortionAlternative, ...]:
    """Portion keys × {0.5, 1, 1.5, 2}, same multiples as the whitelist."""
    portions = entry.get("portions") or {}
    if not isinstance(portions, Mapping):
        return ()
    out: list[PortionAlternative] = []
    has_serving = "serving" in portions
    for key, grams_each in portions.items():
        if not _numeric(grams_each):
            continue
        spoken_key = key
        if key == "qns":
            if has_serving:
                continue
            spoken_key = "serving"
        if spoken_key not in _COUNTABLE and spoken_key not in _MASS and spoken_key not in _MODIFIERS:
            continue
        for quantity in QUANTITY_MULTIPLES:
            phrase = _phrase(spoken_key, quantity)
            if phrase is None:
                continue
            out.append(
                PortionAlternative(
                    key=str(key),
                    quantity=float(quantity),
                    phrase=phrase,
                    grams=round(quantity * float(grams_each), 2),
                )
            )
    return tuple(out)


def _cup_only(catalog: Mapping, food_id: str) -> bool:
    """True when a food's only speakable portion is a plain cup."""
    entry = catalog.get(food_id) or {}
    portions = entry.get("portions") or {}
    if not isinstance(portions, Mapping):
        return False
    keys = {str(key) for key in portions if _numeric(portions.get(key))}
    return keys == {"cup"}


def _eligible_foods(catalog: Mapping) -> list[str]:
    ids: list[str] = []
    for food_id in catalog:
        entry = catalog.get(food_id)
        if not isinstance(entry, dict):
            continue
        if portion_alternatives(entry):
            ids.append(canonical_food_id(catalog, food_id))
    # Unique + sorted so rng.sample is independent of catalog iteration order.
    return sorted(set(ids))


def _pool_food(catalog: Mapping, food_id: str) -> PoolFood:
    entry = catalog[food_id]
    aliases = tuple(str(alias) for alias in (entry.get("aliases") or []) if alias)
    return PoolFood(
        food_id=food_id,
        name=str(entry.get("name") or food_id),
        aliases=aliases,
        alternatives=portion_alternatives(entry),
        allergen_tags=tuple(str(tag) for tag in (entry.get("allergen_tags") or [])),
    )


def _phrase(key: str, quantity: float) -> str | None:
    if key in _MODIFIERS:
        singular = f"{key} serving"
        plural = f"{key} servings"
        return _counted(quantity, singular, plural)
    if key in _MASS:
        unit = _MASS[key]
        if quantity == 0.5:
            return f"0.5 {unit}"
        if quantity == 1.0:
            return f"1 {unit}"
        if quantity == 1.5:
            return f"1.5 {unit}"
        if quantity == 2.0:
            return f"2 {unit}"
        return None
    pair = _COUNTABLE.get(key)
    if pair is None:
        return None
    return _counted(quantity, pair[0], pair[1])


def _counted(quantity: float, singular: str, plural: str) -> str | None:
    if quantity == 0.5:
        return f"half a {singular}"
    if quantity == 1.0:
        return f"a {singular}"
    if quantity == 1.5:
        return f"1.5 {plural}"
    if quantity == 2.0:
        return f"two {plural}"
    return None


def _numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
