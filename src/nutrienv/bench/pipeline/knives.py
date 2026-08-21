"""Code-side Evaluate knives. Grams stay table values; LLM only rewrites speech."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from nutrienv.bench.realize import bind_evaluate_reasons
from nutrienv.world.types import LedgerRow, MAX_ITEM_GRAMS, Profile, ledger_totals, normalize_tags

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
    if knife == KNIFE_UNDER_SLOT:
        return _under_slot(
            plate, profile=profile, catalog=catalog, pool=pool, windows=windows
        )
    if knife == KNIFE_SWAP:
        return _swap(
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


def _swap(
    plate: list[dict[str, object]],
    *,
    profile: Profile,
    catalog: Mapping,
    pool: FoodPool,
    windows: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]] | None:
    """Iso-caloric substitution: fat_g_hi or fiber_g_lo, no kcal code."""
    target = _totals(plate, catalog).get("kcal", 0.0)
    if target <= 0:
        return None
    fatty = _fattiest_id(pool, catalog)
    if fatty is not None:
        whole = _iso_item(fatty, target, catalog)
        if whole is not None and _swap_hits( [whole], windows, catalog, profile.allergies):
            return [whole]
    for index, item in enumerate(plate):
        item_kcal = _totals([item], catalog).get("kcal", 0.0)
        if item_kcal <= 0:
            continue
        for food in pool.foods:
            if food.food_id == item["food_id"]:
                continue
            swapped = _iso_item(food.food_id, item_kcal, catalog)
            if swapped is None:
                continue
            candidate = plate[:index] + [swapped] + plate[index + 1 :]
            if _swap_hits(candidate, windows, catalog, profile.allergies):
                return candidate
    return None


def _fattiest_id(pool: FoodPool, catalog: Mapping) -> str | None:
    best: tuple[float, str] | None = None
    for food in pool.foods:
        nutrients = (catalog.get(food.food_id) or {}).get("nutrients") or {}
        kcal = float(nutrients.get("kcal") or 0.0)
        fat = float(nutrients.get("fat_g") or 0.0)
        if kcal <= 0 or fat <= 0:
            continue
        density = fat / kcal
        if best is None or density > best[0]:
            best = (density, food.food_id)
    return None if best is None else best[1]


def _iso_item(
    food_id: str, target_kcal: float, catalog: Mapping
) -> dict[str, object] | None:
    nutrients = (catalog.get(food_id) or {}).get("nutrients") or {}
    kcal_per_100 = float(nutrients.get("kcal") or 0.0)
    if kcal_per_100 <= 0:
        return None
    grams = round(target_kcal * 100.0 / kcal_per_100, 2)
    item = {"food_id": food_id, "grams": grams}
    if _cartoon_item(item) or grams <= GRAM_TOLERANCE:
        return None
    return item


def _swap_hits(
    plate: Sequence[Mapping[str, object]],
    windows: Mapping[str, tuple[float, float]],
    catalog: Mapping,
    allergies: tuple[str, ...],
) -> bool:
    if any(_cartoon_item(item) for item in plate):
        return False
    reasons = bind_evaluate_reasons(list(plate), dict(windows), catalog, allergies)
    if "kcal_hi" in reasons or "kcal_lo" in reasons:
        return False
    return "fat_g_hi" in reasons or "fiber_g_lo" in reasons


def _totals(plate: Sequence[Mapping[str, object]], catalog: Mapping) -> dict[str, float]:
    rows = [
        LedgerRow(str(item["food_id"]), float(item["grams"]), "eval") for item in plate
    ]
    return ledger_totals(rows, dict(catalog))


def _under_slot(
    plate: list[dict[str, object]],
    *,
    profile: Profile,
    catalog: Mapping,
    pool: FoodPool,
    windows: Mapping[str, tuple[float, float]],
) -> list[dict[str, object]] | None:
    """One step down, or drop one food. Empty and tiny plates are cartoon."""
    for index, item in enumerate(plate):
        stepped = _prev_portion(item, pool)
        if stepped is None or _cartoon_item(stepped):
            continue
        candidate = plate[:index] + [stepped] + plate[index + 1 :]
        if _fires_lo(candidate, windows, catalog, profile.allergies):
            return candidate
    if len(plate) < 2:
        return None
    for index in range(len(plate)):
        candidate = plate[:index] + plate[index + 1 :]
        if not candidate or any(_cartoon_item(item) for item in candidate):
            continue
        if _fires_lo(candidate, windows, catalog, profile.allergies):
            return candidate
    return None


def _prev_portion(
    item: Mapping[str, object], pool: FoodPool
) -> dict[str, object] | None:
    food = next((row for row in pool.foods if row.food_id == item["food_id"]), None)
    if food is None:
        return None
    current = float(item["grams"])
    lower = [
        alt
        for alt in food.alternatives
        if alt.grams < current - 1e-9 and alt.grams > GRAM_TOLERANCE
    ]
    if not lower:
        return None
    alt = max(lower, key=lambda row: row.grams)
    return {"food_id": food.food_id, "grams": float(alt.grams)}


def _fires_lo(
    plate: Sequence[Mapping[str, object]],
    windows: Mapping[str, tuple[float, float]],
    catalog: Mapping,
    allergies: tuple[str, ...],
) -> bool:
    reasons = bind_evaluate_reasons(list(plate), dict(windows), catalog, allergies)
    return any(code.endswith("_lo") for code in reasons)


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
