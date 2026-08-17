"""portion_table whitelist recomputed against catalog-v1.

matches_portion_table is data-driven (catalog portions × {0.5, 1, 1.5, 2}
plus fixed 2 oz). These rows pin the full-strategy gold values: apple
piece 165 is on-table; cheddar slice 9 / cup 113 are on-table; qns
amounts stay on-table. Old first-wins leftovers that are no longer any
key (cheddar cup 132) are off-table.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nutrienv.bench.portion_table import matches_portion_table
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
CATALOG_V1 = ROOT / "data" / "fdc" / "catalog-v1.sqlite"

# (food_id, grams, on_table, note)
_CASES = [
    ("apple", 165.0, True, "new piece (seq 1 small)"),
    ("apple", 82.5, True, "0.5 × piece 165"),
    ("apple", 247.5, True, "1.5 × piece 165"),
    ("apple", 200.0, True, "qns (old piece 200 is no longer a piece slot)"),
    ("apple", 180.0, False, "not a catalog-v1 multiple"),
    ("cheddar", 9.0, True, "new slice (cracker-size, seq 1)"),
    ("cheddar", 18.0, True, "2 × slice 9"),
    ("cheddar", 113.0, True, "new cup (shredded, seq 4)"),
    ("cheddar", 21.0, True, "qns (old slice 21 is no longer a slice slot)"),
    ("cheddar", 132.0, False, "old diced-cup first-wins leftover"),
    ("oats", 10.0, True, "qns"),
    ("oats", 80.0, True, "cup"),
    ("egg", 50.0, True, "qns / piece"),
    ("milk_whole", 244.0, True, "qns / cup"),
    ("pasta", 80.0, True, "oz (was oz_yield in safe-overlay)"),
    ("banana", 126.0, True, "qns / piece"),
]


@pytest.fixture(scope="module")
def catalog_v1():
    if not CATALOG_V1.is_file():
        pytest.fail(
            "data/fdc/catalog-v1.sqlite is missing; build with "
            ".venv/bin/python scripts/build_fdc_catalog.py "
            "--out data/fdc/catalog-v1.sqlite"
        )
    return load_catalog(CATALOG_V1)


@pytest.mark.parametrize(
    ("food_id", "grams", "on_table", "note"),
    _CASES,
    ids=[f"{food}-{grams:g}-{'on' if on else 'off'}" for food, grams, on, _note in _CASES],
)
def test_catalog_v1_portion_table(catalog_v1, food_id, grams, on_table, note):
    assert food_id in catalog_v1, food_id
    assert (
        matches_portion_table(food_id, grams, catalog_v1) is on_table
    ), f"{food_id} {grams:g} ({note})"


def test_catalog_v1_gold_staple_ids(catalog_v1) -> None:
    assert catalog_v1.canonical_id("oats") == "2708489"
    assert catalog_v1.canonical_id("chicken_breast") == "171477"
    assert catalog_v1.canonical_id("apple") == "2709215"
    assert catalog_v1.canonical_id("cheddar") == "2705709"
    assert catalog_v1["apple"]["portions"]["piece"] == 165.0
    assert catalog_v1["cheddar"]["portions"]["slice"] == 9.0
    assert catalog_v1["cheddar"]["portions"]["cup"] == 113.0
    assert catalog_v1["oats"]["portions"]["qns"] == 10.0
    assert "oz_yield" not in catalog_v1["pasta"]["portions"]
    assert catalog_v1["pasta"]["portions"]["oz"] == 80.0
