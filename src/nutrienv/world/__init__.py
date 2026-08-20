"""World layer: profile, ledger, catalog."""

from .catalog import FoodCatalog, SEARCH_LIMIT
from .catalog_store import GOLD_CATALOG_PATH, load_catalog
from .daily_windows import (
    ACTIVITY_PAL,
    UPDATE_BANDS,
    derive_daily_windows,
    derive_profile_windows,
    estimated_energy_requirement,
    implicit_windows_pass,
)
from .dri import DRI_REFERENCE
from .portions import GRAM_UNITS, OUNCE_GRAMS, OUNCE_UNITS, UNIT_SYNONYMS, resolve_portion
from .types import (
    ImplausibleQuantity,
    LedgerRow,
    MAX_ITEM_GRAMS,
    Profile,
    PHASES,
    REASON_CODES,
    WorldState,
    food_view,
    ledger_totals,
    ledger_view,
    normalize_grams,
    normalize_reasons,
    normalize_tags,
    normalize_window,
    profile_view,
)

__all__ = [
    "Profile",
    "LedgerRow",
    "WorldState",
    "DRI_REFERENCE",
    "ACTIVITY_PAL",
    "UPDATE_BANDS",
    "derive_daily_windows",
    "derive_profile_windows",
    "estimated_energy_requirement",
    "implicit_windows_pass",
    "FoodCatalog",
    "SEARCH_LIMIT",
    "GOLD_CATALOG_PATH",
    "load_catalog",
    "normalize_tags",
    "normalize_window",
    "normalize_grams",
    "profile_view",
    "ledger_view",
    "ledger_totals",
    "food_view",
    "resolve_portion",
    "UNIT_SYNONYMS",
    "GRAM_UNITS",
    "OUNCE_GRAMS",
    "OUNCE_UNITS",
    "ImplausibleQuantity",
    "MAX_ITEM_GRAMS",
    "REASON_CODES",
    "PHASES",
    "normalize_reasons",
]
