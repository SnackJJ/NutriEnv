from nutrienv.bench.realizations import (
    FUZZY_ROWS,
    LEFTOVER_ROWS,
    assert_fuzzy_resolves,
    fuzzy_key,
    leftover_key,
)
from nutrienv.bench.validator import semantic_key, validate_draft
from nutrienv.bench import Generator
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.types import LedgerRow, ledger_totals


def test_fuzzy_table_resolves_and_keys_are_unique():
    catalog = load_catalog()
    assert len(FUZZY_ROWS) >= 16
    assert_fuzzy_resolves(catalog)
    keys = [fuzzy_key(row) for row in FUZZY_ROWS]
    assert len(keys) == len(set(keys))
    novel = [row for row in FUZZY_ROWS if row.source != "gold"]
    assert len(novel) >= 16


def test_leftover_table_remainders_are_positive_and_unique():
    catalog = load_catalog()
    assert len(LEFTOVER_ROWS) >= 8
    keys = [leftover_key(row) for row in LEFTOVER_ROWS]
    assert len(keys) == len(set(keys))
    novel = [row for row in LEFTOVER_ROWS if row.source != "gold"]
    assert len(novel) >= 8
    for row in LEFTOVER_ROWS:
        ledger = [LedgerRow(food, grams, slot) for food, grams, slot in row.ledger]
        eaten = ledger_totals(ledger, catalog)
        kcal_hi = row.windows["kcal"][1] - eaten.get("kcal", 0.0)
        assert kcal_hi > 0, row.seed_id


def test_fuzzy_seeds_change_semantic_key():
    keys = {
        semantic_key(Generator().sample(seed, situation="fuzzy_portion"))
        for seed in range(20)
    }
    assert len(keys) > 1
    assert Generator().sample(3, situation="fuzzy_portion") == Generator().sample(
        3, situation="fuzzy_portion"
    )


def test_leftover_seeds_change_semantic_key():
    keys = {
        semantic_key(Generator().sample(seed, persona="leftover"))
        for seed in range(20)
    }
    assert len(keys) > 1


def test_validator_accepts_table_drafts_and_rejects_leaks():
    good = Generator().sample(2, situation="fuzzy_portion")
    assert validate_draft(good) == []
    leftover = Generator().sample(5, persona="leftover")
    assert validate_draft(leftover) == []

    leaked = Generator().sample(2, situation="fuzzy_portion")
    object.__setattr__(leaked, "query", "Log milk_whole please, kcal 1800")
    object.__setattr__(leaked, "family", "recommend")
    issues = validate_draft(leaked)
    assert any("leaks" in item for item in issues)
