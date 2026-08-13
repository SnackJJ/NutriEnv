"""Compatibility imports for the canonical Oracle in :mod:`generator`."""

from __future__ import annotations

import copy
from dataclasses import replace

from nutrienv.world.types import WorldState, normalize_tags

from .generator import Oracle

__all__ = ["Oracle", "TIRED_KCAL_DELTA", "derive_oracle"]

TIRED_KCAL_DELTA = 200.0


def derive_oracle(s0: WorldState, query: str) -> Oracle:
    """Derive the small legacy tired/shrimp update contract.

    Generator tasks construct their richer, family-specific oracles directly.
    """
    lowered = query.lower()
    profile = s0.profile
    windows = dict(profile.windows)
    allergies = profile.allergies
    if "tired" in lowered:
        lo, hi = windows.get("kcal", (1800.0, 2200.0))
        windows["kcal"] = (lo + TIRED_KCAL_DELTA, hi + TIRED_KCAL_DELTA)
    if "shrimp" in lowered and ("allerg" in lowered or "add" in lowered):
        allergies = normalize_tags([*allergies, "shrimp"])
    expected = replace(
        profile,
        allergies=allergies,
        windows=windows,
        plan_preset=copy.deepcopy(profile.plan_preset),
    )
    recommend = "recommend" in lowered or "suggest" in lowered
    return Oracle(
        profile=expected,
        ledger=tuple(s0.ledger),
        last_plan=None if recommend else copy.deepcopy(s0.last_plan),
        plan_must_be_safe=recommend,
        plan_must_fit_windows=recommend,
    )
