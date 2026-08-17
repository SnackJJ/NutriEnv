from nutrienv.world.catalog import FoodCatalog, SEARCH_LIMIT, canonical_food_id
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
