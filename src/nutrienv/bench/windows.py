"""Pairwise nutrient-window reachability. Atwater caps are physics, not policy."""

from __future__ import annotations

from nutrienv.world.types import normalize_tags

__all__ = ["KCAL_RATIO_CAP", "windows_unsatisfiable", "any_pair_unsatisfiable"]

KCAL_RATIO_CAP = {
    "protein_g": 0.25,
    "carb_g": 0.25,
    "fat_g": 1.0 / 9.0,
    "fiber_g": 0.5,
}


def _tag_set(values) -> set[str]:
    return set(normalize_tags(list(values or [])))


def windows_unsatisfiable(
    windows: dict,
    catalog,
    allergies: tuple[str, ...] = (),
    floor_nutrient: str = "protein_g",
    ceiling_nutrient: str = "kcal",
) -> bool:
    banned = _tag_set(allergies)
    ceiling_value = float(windows.get(ceiling_nutrient, (0.0, 0.0))[1])
    floor_value = float(windows.get(floor_nutrient, (0.0, 0.0))[0])
    best = 0.0
    for entry in catalog.values():
        try:
            tags = _tag_set(entry.get("allergen_tags") or [])
        except ValueError:
            continue
        if tags & banned:
            continue
        nutrients = entry.get("nutrients") or {}
        ceiling = float(nutrients.get(ceiling_nutrient) or 0.0)
        floor = float(nutrients.get(floor_nutrient) or 0.0)
        if floor <= 0:
            continue
        if ceiling <= 0:
            # A zero-denominator food has an unbounded floor/ceiling ratio, so
            # on paper it satisfies any tight ceiling. The catalog holds 14
            # zero-kcal entries -- all decaf coffee at 0.1 g protein per 100 g
            # -- and reaching a 56 g protein floor from them means drinking
            # 56 kg. Anything at or above 1 g per 100 g is a real source of
            # the floor nutrient and does make the window satisfiable; below
            # that the "solution" is not food, so it does not count as one.
            if floor >= 1.0:
                return False
            continue
        ratio = floor / ceiling
        if ceiling_nutrient == "kcal":
            # Atwater factors: protein and carbohydrate yield 4 kcal/g, fat
            # yields 9 kcal/g. No food can exceed 0.25 g protein or carb, or
            # 1/9 g fat, per kcal. The fibre cap (0.5 g/kcal) is a pragmatic
            # bound rather than physics; catalog conflicts are already
            # infeasible under the observed maximum (~0.353 g/kcal). Sodium
            # carries no energy. Catalog rounding sometimes reports ratios
            # above the Atwater caps; trust physics, not the artifact.
            cap = KCAL_RATIO_CAP.get(floor_nutrient)
            if cap is not None:
                ratio = min(ratio, cap)
        best = max(best, ratio)
    return best * ceiling_value < floor_value


def any_pair_unsatisfiable(
    windows: dict, catalog, allergies: tuple[str, ...] = ()
) -> bool:
    keys = list(windows)
    for floor_nutrient in keys:
        if float(windows[floor_nutrient][0]) <= 0:
            continue
        for ceiling_nutrient in keys:
            if ceiling_nutrient == floor_nutrient:
                continue
            if windows_unsatisfiable(
                windows,
                catalog,
                allergies,
                floor_nutrient=floor_nutrient,
                ceiling_nutrient=ceiling_nutrient,
            ):
                return True
    return False
