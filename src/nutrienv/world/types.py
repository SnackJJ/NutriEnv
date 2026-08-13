"""Core world data types and the normalization rules that go with them.

Bench must mirror these rules when it builds an Oracle, because Pass is
``end state == Oracle`` (ADR 0004) and a write goes through normalization:

- ``allergies`` / ``medications`` are a set of names: stripped, lowercased,
  de-duplicated, sorted. Use :func:`normalize_tags` to build Oracle values.
- ``windows`` values are ``(lo, hi)`` floats with ``lo <= hi``.
- Only the keys a patch mentions change; everything else stays as S0.
  ``version`` is never bumped by Env, only by an explicit patch.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass, field

__all__ = [
    "Profile",
    "LedgerRow",
    "WorldState",
    "normalize_tags",
    "normalize_window",
    "normalize_grams",
    "profile_view",
    "ledger_view",
    "food_view",
]


@dataclass(frozen=True)
class Profile:
    """The authenticated person's structured constraints and nutrient windows."""

    user_id: str
    allergies: tuple[str, ...] = ()
    medications: tuple[str, ...] = ()
    windows: dict[str, tuple[float, float]] = field(default_factory=dict)
    plan_preset: dict = field(default_factory=dict)
    version: int = 1


@dataclass(frozen=True)
class LedgerRow:
    """One append-only row of what the person actually ate."""

    food_id: str
    grams: float
    eaten_at: str


@dataclass
class WorldState:
    """The whole world of one episode.

    ``last_plan`` holds the items of the most recent ``submit_plan`` as
    ``[{"food_id": str, "grams": float}, ...]``; it is empty until one lands.
    """

    profile: Profile
    ledger: list[LedgerRow] = field(default_factory=list)
    catalog: dict = field(default_factory=dict)
    last_plan: list = field(default_factory=list)


def normalize_tags(values: object) -> tuple[str, ...]:
    """Canonicalize an allergy/medication list into a sorted tuple of names."""
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError("expected a list of strings")
    out: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("expected a list of strings")
        name = value.strip().lower()
        if not name:
            raise ValueError("tag must be a non-empty string")
        out.add(name)
    return tuple(sorted(out))


def normalize_window(value: object) -> tuple[float, float]:
    """Canonicalize a nutrient window into ``(lo, hi)`` floats."""
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError("window must be a [lo, hi] pair")
    if len(value) != 2:
        raise ValueError("window must be a [lo, hi] pair")
    bounds = []
    for bound in value:
        if isinstance(bound, bool) or not isinstance(bound, (int, float)):
            raise ValueError("window bounds must be numbers")
        if not math.isfinite(bound):
            raise ValueError("window bounds must be finite")
        bounds.append(float(bound))
    lo, hi = bounds
    if lo > hi:
        raise ValueError("window lo must be <= hi")
    return (lo, hi)


def normalize_grams(value: object) -> float:
    """Canonicalize a serving size into a positive float."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("grams must be a number")
    if not math.isfinite(value):
        raise ValueError("grams must be finite")
    if value <= 0:
        raise ValueError("grams must be > 0")
    return float(value)


def profile_view(profile: Profile) -> dict:
    """Observation-shaped copy of a Profile (tuples become lists)."""
    view = asdict(profile)
    view["allergies"] = list(profile.allergies)
    view["medications"] = list(profile.medications)
    view["windows"] = {key: list(win) for key, win in profile.windows.items()}
    return view


def ledger_view(rows: list[LedgerRow]) -> list[dict]:
    """Observation-shaped copy of the ledger."""
    return [asdict(row) for row in rows]


def food_view(catalog: dict, food_id: str) -> dict:
    """Observation-shaped copy of one catalog entry, id included.

    ``portions`` is always present, empty for a food that declares none, so the
    observation has one shape whatever the Generator's catalog carries.
    """
    entry = copy.deepcopy(catalog[food_id])
    entry.setdefault("portions", {})
    return {"food_id": food_id, **entry}
