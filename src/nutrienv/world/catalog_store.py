"""Load a frozen USDA snapshot; fall back to the 15-food fixture."""

from __future__ import annotations

import json
from pathlib import Path

from .catalog_fixture import demo_catalog

__all__ = ["SNAPSHOT_PATH", "load_catalog"]

_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_PATH = _ROOT / "data" / "catalog-snapshot.json"


def load_catalog(path: Path | None = None) -> dict:
    """Return a catalog dict. Snapshot wins when the file exists and is valid."""
    target = path or SNAPSHOT_PATH
    if not target.is_file():
        return demo_catalog()
    payload = json.loads(target.read_text(encoding="utf-8"))
    foods = payload.get("foods")
    if not isinstance(foods, dict) or not foods:
        return demo_catalog()
    return {str(fid): dict(entry) for fid, entry in foods.items()}
