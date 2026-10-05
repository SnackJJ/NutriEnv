"""Validate candidate profile constraints without mutating the world."""

from .types import Profile


def validate_profile_targets(profile: Profile) -> None:
    for field in ("age_y", "height_cm", "weight_kg"):
        value = getattr(profile, field)
        if value is not None and value <= 0:
            raise ValueError(f"{field} must be positive, got {value}")
    for key, (lo, hi) in profile.windows.items():
        if lo < 0 or hi < 0:
            raise ValueError(f"{key} window must be non-negative")
        if key == "kcal" and hi <= 0:
            raise ValueError("daily energy target must have a positive ceiling")
    required = {"kcal", "protein_g", "carb_g", "fat_g"}
    if required <= profile.windows.keys():
        lower = sum(profile.windows[key][0] * factor for key, factor in
                    (("protein_g", 4), ("carb_g", 4), ("fat_g", 9)))
        upper = sum(profile.windows[key][1] * factor for key, factor in
                    (("protein_g", 4), ("carb_g", 4), ("fat_g", 9)))
        lo, hi = profile.windows["kcal"]
        if lower > hi + 1e-6 or upper < lo - 1e-6:
            raise ValueError("macro energy ranges cannot meet the energy target")
