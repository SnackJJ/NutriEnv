"""Load the published USDA FNDDS catalog.

Runtime never calls the USDA API.
"""

from __future__ import annotations

import copy
from functools import lru_cache
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
    return copy.deepcopy(_snapshot(target, _stamp(target)))


def _stamp(target: Path) -> tuple[int, int]:
    """File identity, so a rebuilt snapshot is not served from the cache."""
    try:
        stat = target.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _snapshot(target: Path, stamp: tuple[int, int]) -> FoodCatalog:
    """Parse the snapshot once. Callers get a clone that shares frozen entries."""
    if target.is_file() and target.suffix == ".sqlite":
        return FoodCatalog.from_sqlite(target)
    return FoodCatalog.from_mapping(demo_catalog())
