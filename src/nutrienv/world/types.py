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
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field

__all__ = [
    "Profile",
    "LedgerRow",
    "WorldState",
    "ImplausibleQuantity",
    "MAX_ITEM_GRAMS",
    "REASON_CODES",
    "normalize_tags",
    "normalize_reasons",
    "normalize_window",
    "normalize_grams",
    "profile_view",
    "ledger_view",
    "ledger_totals",
    "food_view",
]


REASON_CODES = frozenset(
    {
        "allergy",
        "kcal_hi",
        "kcal_lo",
        "protein_g_hi",
        "protein_g_lo",
        "carb_g_hi",
        "carb_g_lo",
        "fat_g_hi",
        "fat_g_lo",
        "fiber_g_hi",
        "fiber_g_lo",
        "sodium_mg_hi",
        "sodium_mg_lo",
    }
)


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
    ``last_verdict`` is ``None`` (silence), ``"accept"``, or ``"reject"``.
    ``last_reasons`` is the closed reason-code set from a reject.
    """

    profile: Profile
    ledger: list[LedgerRow] = field(default_factory=list)
    catalog: Mapping[str, dict] = field(default_factory=dict)
    last_plan: list = field(default_factory=list)
    last_verdict: str | None = None
    last_reasons: tuple[str, ...] = ()


def normalize_reasons(values: object) -> tuple[str, ...]:
    """Canonicalize reject reasons into a sorted unique tuple of closed codes."""
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ValueError("expected a list of strings")
    out: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("expected a list of strings")
        token = value.strip()
        if token not in REASON_CODES:
            raise ValueError(f"unknown reason: {token!r}")
        out.add(token)
    return tuple(sorted(out))


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


# Habitability bound, not validation trivia. A kcal ceiling cannot constrain a
# 0-kcal food, so a protein or fat floor was reachable by submitting tens of
# kilograms of brewed coffee (v0-rec-conflict-001: 90,909 g of 2710376). A
# person cannot eat 2 kg of one item; the largest frozen-split quantity is 300 g.
MAX_ITEM_GRAMS = 2000.0


class ImplausibleQuantity(ValueError):
    """A serving no person can eat. Dispatch maps this to ActionError."""


def normalize_grams(value: object) -> float:
    """Canonicalize a serving size into a positive float at most MAX_ITEM_GRAMS."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("grams must be a number")
    if not math.isfinite(value):
        raise ValueError("grams must be finite")
    if value <= 0:
        raise ValueError("grams must be > 0")
    if value > MAX_ITEM_GRAMS:
        raise ImplausibleQuantity(f"grams must be <= {MAX_ITEM_GRAMS:g}")
    return float(value)


def profile_view(profile: Profile) -> dict:
    """Observation-shaped copy of a Profile (tuples become lists)."""
    view = asdict(profile)
    view["allergies"] = list(profile.allergies)
    view["medications"] = list(profile.medications)
    view["windows"] = {key: list(win) for key, win in profile.windows.items()}
    return view


def _row_nutrients(row: LedgerRow, catalog: dict) -> dict[str, float]:
    entry = catalog.get(row.food_id)
    if not isinstance(entry, dict):
        return {}
    nutrients = entry.get("nutrients") or {}
    if not isinstance(nutrients, dict):
        return {}
    out: dict[str, float] = {}
    for key, amount in nutrients.items():
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            continue
        if not math.isfinite(amount):
            continue
        out[str(key)] = float(amount) * float(row.grams) / 100.0
    return out


def ledger_view(rows: list[LedgerRow], catalog: dict | None = None) -> list[dict]:
    """Observation-shaped copy of the ledger.

    When ``catalog`` is given, each row includes ``nutrients`` already scaled
    to that row's grams so a leftover remainder does not need N ``get_food``s.
    """
    view = []
    for row in rows:
        item = asdict(row)
        if catalog is not None:
            item["nutrients"] = _row_nutrients(row, catalog)
        view.append(item)
    return view


def ledger_totals(rows: list[LedgerRow], catalog: dict) -> dict[str, float]:
    """Sum of scaled ledger nutrients. Missing foods contribute nothing."""
    totals: dict[str, float] = {}
    for row in rows:
        for key, amount in _row_nutrients(row, catalog).items():
            totals[key] = totals.get(key, 0.0) + amount
    return totals


def food_view(catalog: dict, food_id: str) -> dict:
    """Observation-shaped copy of one catalog entry, id included.

    ``portions`` is always present, empty for a food that declares none, so the
    observation has one shape whatever the Generator's catalog carries.
    """
    entry = copy.deepcopy(catalog[food_id])
    entry.setdefault("portions", {})
    return {"food_id": food_id, **entry}
