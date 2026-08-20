from nutrienv.world.catalog import (
    FoodCatalog,
    SEARCH_LIMIT,
    canonical_food_id,
    iter_catalog_entries,
)
from nutrienv.world.catalog_fixture import demo_catalog
from nutrienv.world.catalog_store import GOLD_CATALOG_PATH, load_catalog


def test_fixture_catalog_search_is_token_and_not_a_dump():
    catalog = FoodCatalog.from_mapping(demo_catalog())
    assert catalog.search("*") == []
    assert catalog.search("a") == []
    hits = catalog.search("prawn")
    assert [row["food_id"] for row in hits] == ["shrimp"]
    assert "shrimp" in catalog
    assert catalog["shrimp"]["name"]


def test_load_catalog_prefers_fdc_snapshot_when_built():
    catalog = load_catalog()
    assert len(catalog) >= 15
    assert "milk_whole" in catalog
    assert catalog["milk_whole"]["portions"].get("cup") == 244.0
    if GOLD_CATALOG_PATH.is_file():
        assert len(catalog) > 1000
        hits = catalog.search("milk whole")
        assert hits
        assert hits[0]["food_id"].isdigit() or "milk" in hits[0]["name"].lower()
        assert len(hits) <= SEARCH_LIMIT
        assert catalog.canonical_id("oats") == "2708489"
        assert catalog.canonical_id("chicken_breast") == "171477"


def test_canonical_food_id_foodcatalog() -> None:
    catalog = load_catalog()
    assert canonical_food_id(catalog, "oats") == catalog.canonical_id("oats")


def test_canonical_food_id_plain_dict() -> None:
    catalog = {"oats": {"name": "Rolled oats"}}
    assert canonical_food_id(catalog, "oats") == "oats"
    assert canonical_food_id(catalog, "missing") == "missing"


def test_iter_entries_scans_without_copying_but_getitem_still_does() -> None:
    """A read-only scan shares entries; ``[]`` keeps its copy-on-write guard.

    A clone shares ``_base`` with its parent, so ``__getitem__`` deep-copies
    what it hands out. Scanning the whole catalog that way costs one deepcopy
    per food per task, which is why validators read through ``iter_entries``.
    """
    catalog = load_catalog()
    scanned = dict(catalog.iter_entries())
    assert len(scanned) == len(catalog)
    food_id = next(iter(scanned))
    assert scanned[food_id] is catalog._base[food_id]
    assert catalog[food_id] is not catalog._base[food_id]
    assert catalog[food_id] == scanned[food_id]


def test_iter_catalog_entries_accepts_a_plain_mapping() -> None:
    plain = {"oats": {"name": "Rolled oats"}}
    assert list(iter_catalog_entries(plain)) == [("oats", plain["oats"])]
