"""Realization row types, keys, and evaluate-window arithmetic."""

from __future__ import annotations

import math
from dataclasses import dataclass

from nutrienv.world.types import LedgerRow, ledger_totals

__all__ = [
    "FuzzyRow",
    "MultiItemLogRow",
    "UnitConvertRow",
    "NearSynonymRow",
    "LedgerGapRow",
    "LeftoverRow",
    "UpdateRow",
    "ConstrainRow",
    "EvaluateRow",
    "RecommendRow",
    "fuzzy_key",
    "multi_item_log_key",
    "unit_convert_key",
    "near_synonym_key",
    "ledger_gap_key",
    "leftover_key",
    "update_key",
    "constrain_key",
    "evaluate_key",
    "recommend_key",
    "evaluate_windows",
]

@dataclass(frozen=True)
class FuzzyRow:
    seed_id: str
    food_id: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"
    review: str = "ok"


@dataclass(frozen=True)
class MultiItemLogRow:
    seed_id: str
    query: str
    items: tuple[tuple[str, str], ...]
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class UnitConvertRow:
    seed_id: str
    food_id: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class NearSynonymRow:
    seed_id: str
    food_id: str
    spoken: str
    phrase: str
    utterance: str
    slot: str
    source: str = "novel"


@dataclass(frozen=True)
class LedgerGapRow:
    seed_id: str
    query: str
    missing: tuple[str, str, str]
    surround: tuple[tuple[str, float, str], ...]
    source: str = "novel"


@dataclass(frozen=True)
class LeftoverRow:
    seed_id: str
    query: str
    windows: dict[str, tuple[float, float]]
    ledger: tuple[tuple[str, float, str], ...]
    allergies: tuple[str, ...] = ()
    source: str = "novel"
    plan_preset: dict | None = None


@dataclass(frozen=True)
class UpdateRow:
    seed_id: str
    query: str
    add_allergens: tuple[str, ...] = ()
    remove_allergens: tuple[str, ...] = ()
    window_shifts: dict[str, float | tuple[float, float]] | None = None
    s0_allergies: tuple[str, ...] | None = None
    s0_plan_preset: dict | None = None
    set_plan_preset: dict | None = None
    source: str = "novel"


@dataclass(frozen=True)
class RecommendRow:
    seed_id: str
    query: str
    persona: str
    windows: dict[str, tuple[float, float]]
    allergies: tuple[str, ...] = ()
    plan_preset: dict | None = None
    source: str = "novel"
    occasion: str = ""


@dataclass(frozen=True)
class ConstrainRow:
    seed_id: str
    kind: str
    query: str
    allergies: tuple[str, ...]
    windows: dict[str, tuple[float, float]]
    food_id: str | None = None
    last_plan: tuple[tuple[str, float], ...] = ()
    source: str = "novel"
    mechanism: str | None = None


@dataclass(frozen=True)
class EvaluateRow:
    seed_id: str
    query: str
    items: tuple[tuple[str, str], ...]
    margin_kcal: float = 150.0
    margin_protein: float = 15.0
    source: str = "novel"
    tier: str = "gold"


def fuzzy_key(row: FuzzyRow) -> tuple:
    return ("log", "fuzzy_portion", "everyday", row.food_id, row.phrase, row.slot)


def multi_item_log_key(row: MultiItemLogRow) -> tuple:
    return ("log", "multi_item_log", "everyday", row.items, row.slot)


def unit_convert_key(row: UnitConvertRow) -> tuple:
    return ("log", "unit_convert", "everyday", row.food_id, row.phrase, row.slot)


def near_synonym_key(row: NearSynonymRow) -> tuple:
    return (
        "log",
        "near_synonym",
        "everyday",
        row.food_id,
        row.spoken,
        row.phrase,
        row.slot,
    )


def ledger_gap_key(row: LedgerGapRow) -> tuple:
    surround = tuple((food_id, slot) for food_id, _grams, slot in row.surround)
    return ("log", "ledger_gap", "everyday", row.missing, surround)


def leftover_key(row: LeftoverRow) -> tuple:
    foods = tuple((food_id, slot) for food_id, _grams, slot in row.ledger)
    return ("recommend", None, "leftover", foods, tuple(sorted(row.windows)))


def _shift_key(delta: float | tuple[float, float]) -> float | tuple[float, float]:
    if isinstance(delta, (tuple, list)):
        return tuple(float(part) for part in delta)
    return float(delta)


def update_key(row: UpdateRow) -> tuple:
    shifts = tuple(
        sorted((key, _shift_key(delta)) for key, delta in (row.window_shifts or {}).items())
    )
    preset = None
    if row.set_plan_preset:
        preset = tuple(sorted(row.set_plan_preset.items()))
    return (
        "update",
        tuple(row.add_allergens),
        tuple(row.remove_allergens),
        shifts,
        row.s0_allergies,
        preset,
    )


def constrain_key(row: ConstrainRow) -> tuple:
    windows = tuple(sorted((key, bounds) for key, bounds in row.windows.items()))
    return ("constrain", row.kind, row.food_id, row.allergies, windows, row.last_plan)


def recommend_key(row: RecommendRow) -> tuple:
    windows = tuple(sorted((key, tuple(bounds)) for key, bounds in row.windows.items()))
    preset = None
    if row.plan_preset:
        preset = tuple(sorted(row.plan_preset.items()))
    return (
        "recommend",
        row.persona,
        tuple(sorted(row.allergies)),
        windows,
        preset,
    )


def evaluate_key(row: EvaluateRow) -> tuple:
    return ("evaluate", row.items)


def evaluate_windows(
    items: list[dict],
    catalog,
    kcal_margin: float = 150.0,
    protein_margin: float = 15.0,
) -> dict[str, tuple[float, float]]:
    """Meal windows from live totals. Grams are never stored on the row."""
    rows = [
        LedgerRow(str(item["food_id"]), float(item["grams"]), "eval") for item in items
    ]
    totals = ledger_totals(rows, catalog)
    out: dict[str, tuple[float, float]] = {}
    for key, margin in (("kcal", kcal_margin), ("protein_g", protein_margin)):
        total = totals.get(key, 0.0)
        lo = math.floor((total - margin) / 10.0) * 10.0
        hi = math.ceil((total + margin) / 10.0) * 10.0
        if lo < 0:
            lo = 0.0
        out[key] = (float(lo), float(hi))
    return out
