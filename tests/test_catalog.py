import copy

import pytest

from nutrienv.world.catalog import (
    FoodCatalog,
    SEARCH_LIMIT,
    canonical_food_id,
    iter_catalog_entries,
)
from nutrienv.world.catalog_fixture import demo_catalog
from nutrienv.world.catalog_store import GOLD_CATALOG_PATH, load_catalog
from nutrienv.world.types import food_view


def test_fixture_catalog_search_is_token_and_not_a_dump():
    catalog = FoodCatalog.from_mapping(demo_catalog())
    assert catalog.search("*") == []
    assert catalog.search("a") == []
    hits = catalog.search("prawn")
    assert [row["food_id"] for row in hits] == ["shrimp"]
    assert "shrimp" in catalog
    assert catalog["shrimp"]["name"]


def test_the_committed_snapshot_is_present():
    # With the demo fallback gone, this file being committed is what makes a fresh clone work.
    assert GOLD_CATALOG_PATH.is_file()


def test_load_catalog_returns_the_fdc_snapshot():
    catalog = load_catalog()
    assert len(catalog) > 1000
    assert "milk_whole" in catalog
    assert catalog["milk_whole"]["portions"].get("cup") == 244.0
    hits = catalog.search("milk whole")
    assert hits
    assert hits[0]["food_id"].isdigit() or "milk" in hits[0]["name"].lower()
    assert len(hits) <= SEARCH_LIMIT
    assert catalog.canonical_id("oats") == "2708489"
    assert catalog.canonical_id("chicken_breast") == "2705956"


def test_missing_snapshot_raises_instead_of_substituting_the_fixture(tmp_path):
    with pytest.raises(FileNotFoundError, match="refusing to substitute"):
        load_catalog(tmp_path / "absent.sqlite")


def test_wrong_suffix_raises_instead_of_substituting_the_fixture(tmp_path):
    bogus = tmp_path / "catalog.db"
    bogus.write_bytes(b"")
    with pytest.raises(FileNotFoundError, match="refusing to substitute"):
        load_catalog(bogus)


def test_the_demo_world_is_opt_in():
    catalog = load_catalog(demo=True)
    assert len(catalog) < 100
    assert catalog["shrimp"]["name"] == "Shrimp, cooked"


def test_canonical_food_id_foodcatalog() -> None:
    catalog = load_catalog()
    assert canonical_food_id(catalog, "oats") == catalog.canonical_id("oats")


def test_canonical_food_id_plain_dict() -> None:
    catalog = {"oats": {"name": "Rolled oats"}}
    assert canonical_food_id(catalog, "oats") == "oats"
    assert canonical_food_id(catalog, "missing") == "missing"


def test_catalog_entry_rejects_in_place_assignment() -> None:
    catalog = FoodCatalog.from_mapping(demo_catalog())
    entry = catalog["shrimp"]
    with pytest.raises(TypeError):
        entry["name"] = "hack"
    assert catalog["shrimp"]["name"] == "Shrimp, cooked"


def test_catalog_entry_rejects_nested_dict_assignment() -> None:
    catalog = FoodCatalog.from_mapping(demo_catalog())
    entry = catalog["shrimp"]
    with pytest.raises(TypeError):
        entry["nutrients"]["kcal"] = 0
    with pytest.raises(TypeError):
        entry["portions"]["piece"] = 1
    assert catalog["shrimp"]["nutrients"]["kcal"] == 99.0
    assert catalog["shrimp"]["portions"]["piece"] == 7.0


def test_catalog_entry_rejects_nested_list_mutation() -> None:
    catalog = FoodCatalog.from_mapping(demo_catalog())
    entry = catalog["shrimp"]
    with pytest.raises((TypeError, AttributeError)):
        entry["allergen_tags"].append("milk")
    with pytest.raises((TypeError, AttributeError)):
        entry["aliases"].append("scampi")
    assert list(catalog["shrimp"]["allergen_tags"]) == ["shellfish"]
    assert list(catalog["shrimp"]["aliases"]) == ["prawn", "prawns"]


def test_catalog_entry_rejects_ior_and_reinit() -> None:
    """``|=`` and ``__init__`` are public mutators too (ship-11 review finding)."""
    catalog = FoodCatalog.from_mapping(demo_catalog())
    entry = catalog["shrimp"]
    with pytest.raises(TypeError):
        entry |= {"name": "after"}
    with pytest.raises(TypeError):
        entry.__init__({"name": "after"})
    assert catalog["shrimp"]["name"] == "Shrimp, cooked"
    assert dict(catalog["shrimp"]) == dict(entry)


def test_catalog_entry_deepcopy_shares_the_frozen_entry() -> None:
    """An immutable entry needs no copy; deepcopy must not raise."""
    catalog = FoodCatalog.from_mapping(demo_catalog())
    entry = catalog["shrimp"]
    assert copy.deepcopy(entry) is entry


def test_food_view_returns_a_mutable_observation_copy() -> None:
    catalog = FoodCatalog.from_mapping(
        {"mystery": {"name": "Mystery", "nutrients": {}, "allergen_tags": [], "aliases": []}}
    )
    view = food_view(catalog, "mystery")
    assert view["food_id"] == "mystery"
    assert view["name"] == "Mystery"
    assert view["portions"] == {}
    view["name"] = "hack"
    view["portions"]["cup"] = 10.0
    view["allergen_tags"].append("milk")
    view.setdefault("extra", 1)
    assert catalog["mystery"]["name"] == "Mystery"
    assert "portions" not in catalog["mystery"]
    assert list(catalog["mystery"]["allergen_tags"]) == []
    assert "extra" not in catalog["mystery"]


def test_iter_catalog_entries_reads_the_same_objects_as_getitem() -> None:
    catalog = load_catalog()
    scanned = dict(iter_catalog_entries(catalog))
    assert len(scanned) == len(catalog)
    food_id = next(iter(scanned))
    assert catalog[food_id] is scanned[food_id]


def test_iter_catalog_entries_accepts_a_plain_mapping() -> None:
    plain = {"oats": {"name": "Rolled oats"}}
    assert list(iter_catalog_entries(plain)) == [("oats", plain["oats"])]


def test_cloned_catalog_shares_frozen_entries() -> None:
    catalog = FoodCatalog.from_mapping(demo_catalog())
    clone = copy.deepcopy(catalog)
    assert catalog["shrimp"] is clone["shrimp"]
