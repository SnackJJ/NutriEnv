"""Situation kinds realized by the local v1 Generator.

These names are literature-inspired problem shapes, not imported benchmark
items or labels. Their facts come from the local catalog.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["Situation", "SITUATIONS"]


class Situation(str, Enum):
    FUZZY_PORTION = "fuzzy_portion"
    MULTI_ITEM_LOG = "multi_item_log"
    CONDITION_SUITABILITY = "condition_suitability"
    UNIT_CONVERT = "unit_convert"
    NEAR_SYNONYM = "near_synonym"
    CONFLICT_WINDOWS = "conflict_windows"
    LEDGER_GAP = "ledger_gap"
    IDEMPOTENT_UPDATE = "idempotent_update"


SITUATIONS = tuple(item.value for item in Situation)

GENERATOR_V1_SITUATIONS = (
    Situation.FUZZY_PORTION.value,
    Situation.MULTI_ITEM_LOG.value,
    Situation.CONDITION_SUITABILITY.value,
    Situation.UNIT_CONVERT.value,
    Situation.NEAR_SYNONYM.value,
    Situation.CONFLICT_WINDOWS.value,
    Situation.LEDGER_GAP.value,
)
