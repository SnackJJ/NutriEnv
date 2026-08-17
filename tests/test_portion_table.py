"""Shared portion whitelist: table amounts plus the fixed 2 oz slot."""

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


def test_non_numeric_and_bool_portion_slots_are_ignored() -> None:
    catalog = _catalog()
    assert matches_portion_table("steak", 160.0, catalog) is True
    assert "note" in catalog["steak"]["portions"]
    assert catalog["steak"]["portions"]["flag"] is True
    assert matches_portion_table("steak", 30.0, catalog) is False
