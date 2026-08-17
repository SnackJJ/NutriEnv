"""Load the frozen USDA catalog. Runtime never calls the USDA API."""

from __future__ import annotations

import copy
from pathlib import Path

from .catalog import FoodCatalog
from .catalog_fixture import demo_catalog

__all__ = ["GOLD_CATALOG_PATH", "load_catalog"]

_ROOT = Path(__file__).resolve().parents[3]
GOLD_CATALOG_PATH = _ROOT / "data" / "fdc" / "catalog.sqlite"


def load_catalog(path: Path | str | None = None) -> FoodCatalog:
    """Return the episode catalog.

    Prefers the local FDC sqlite snapshot. Falls back to the 15-food fixture
    when the snapshot has not been built (unit tests, fresh clone).
    """
    target = Path(path) if path is not None else GOLD_CATALOG_PATH
    if target.is_file() and target.suffix == ".sqlite":
        catalog = FoodCatalog.from_sqlite(target)
    else:
        catalog = FoodCatalog.from_mapping(demo_catalog())
    return copy.deepcopy(catalog)
