"""Shared portion whitelist: table amounts plus ounce multiples."""

from __future__ import annotations

from nutrienv.bench.portion_table import matches_portion_table
from nutrienv.world.portions import OUNCE_GRAMS


def _catalog():
    return {
        "steak": {
            "name": "Beef, steak, NFS",
            "portions": {"qns": 160.0, "note": "skip", "flag": True},
        },
        "omelet": {"name": "Egg omelet", "portions": {"piece": 55.0}},
    }


def test_steak_160_is_on_table() -> None:
    assert matches_portion_table("steak", 160.0, _catalog()) is True


def test_omelet_55_is_on_table() -> None:
    assert matches_portion_table("omelet", 55.0, _catalog()) is True


def test_two_ounces_is_always_on_table() -> None:
    assert matches_portion_table("steak", 56.7, _catalog()) is True
    assert matches_portion_table("steak", round(2.0 * OUNCE_GRAMS, 2), _catalog()) is True


def test_ounce_multiples_are_always_on_table() -> None:
    catalog = _catalog()
    assert "oz" not in catalog["steak"]["portions"]
    assert matches_portion_table("steak", 28.35, catalog) is True
    assert matches_portion_table("steak", 42.53, catalog) is True
    assert matches_portion_table("steak", 56.7, catalog) is True
    assert matches_portion_table("steak", round(1.0 * OUNCE_GRAMS, 2), catalog) is True
    assert matches_portion_table("steak", round(1.5 * OUNCE_GRAMS, 2), catalog) is True
    assert matches_portion_table("steak", round(2.0 * OUNCE_GRAMS, 2), catalog) is True


def test_non_numeric_and_bool_portion_slots_are_ignored() -> None:
    catalog = _catalog()
    assert matches_portion_table("steak", 160.0, catalog) is True
    assert "note" in catalog["steak"]["portions"]
    assert catalog["steak"]["portions"]["flag"] is True
    assert matches_portion_table("steak", 30.0, catalog) is False
