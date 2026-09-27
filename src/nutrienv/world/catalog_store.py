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


def load_catalog(path: Path | str | None = None, *, demo: bool = False) -> FoodCatalog:
    """Return the episode catalog.

    A missing or non-sqlite snapshot raises. It used to substitute the 15-food demo fixture
    silently, which is how the 2026-09-08 ablation came to be scored in a toy world: the
    numbers stayed plausible, nothing failed, and the run had to be thrown away. The snapshot
    is committed, so a fresh clone has it. A test that wants the tiny world asks for it with
    ``demo=True``; nothing gets it by accident.
    """
    if demo:
        return FoodCatalog.from_mapping(demo_catalog())
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
    if not (target.is_file() and target.suffix == ".sqlite"):
        raise FileNotFoundError(
            f"catalog snapshot not found: {target} -- refusing to substitute the demo fixture; "
            "pass demo=True if a test world is what you want"
        )
    return FoodCatalog.from_sqlite(target)
