from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEFTOVER_ROWS,
    UPDATE_ROWS,
    assert_constrain_rows,
    assert_evaluate_rows,
    assert_fuzzy_resolves,
    assert_leftover_rows,
    assert_update_rows,
    evaluate_windows,
    fuzzy_key,
    leftover_key,
)
from nutrienv.bench.validator import semantic_key, validate_draft
from nutrienv.bench import Generator
from nutrienv.bench.generator import Task
from nutrienv.world.catalog_store import load_catalog
from nutrienv.world.portions import resolve_portion
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
    assert len(LEFTOVER_ROWS) >= 27
    assert_leftover_rows(catalog)
    keys = [leftover_key(row) for row in LEFTOVER_ROWS]
    assert len(keys) == len(set(keys))
    novel = [row for row in LEFTOVER_ROWS if row.source != "gold"]
    assert len(novel) >= 24
    for row in LEFTOVER_ROWS:
        ledger = [LedgerRow(food, grams, slot) for food, grams, slot in row.ledger]
        eaten = ledger_totals(ledger, catalog)
        kcal_hi = row.windows["kcal"][1] - eaten.get("kcal", 0.0)
        assert kcal_hi > 0, row.seed_id


def test_update_constrain_evaluate_tables_have_unique_keys():
    catalog = load_catalog()
    assert len(UPDATE_ROWS) >= 22
    assert len(CONSTRAIN_ROWS) >= 19
    assert {row.kind for row in CONSTRAIN_ROWS} == {"condition", "conflict"}
    assert len(EVALUATE_ROWS) >= 55
    assert_update_rows(catalog)
    assert_constrain_rows(catalog)
    assert_evaluate_rows(catalog)


def test_cut_leftover_rows_carry_plan_preset():
    wanted = {
        "lo-gold-cut",
        "lo-cut-salmon",
        "lo-cut-tight",
        "lo-cut-breakfast-only",
    }
    found = {row.seed_id for row in LEFTOVER_ROWS if row.plan_preset == {"goal": "cut"}}
    assert wanted <= found


def test_evaluate_windows_are_derived_from_live_totals():
    catalog = load_catalog()
    for row in EVALUATE_ROWS:
        items = []
        for food_id, phrase in row.items:
            grams = resolve_portion(food_id, phrase, catalog)
            assert grams is not None, (row.seed_id, food_id, phrase)
            items.append({"food_id": food_id, "grams": grams})
        windows = evaluate_windows(items, catalog)
        eaten = ledger_totals(
            [LedgerRow(item["food_id"], item["grams"], "plan") for item in items],
            catalog,
        )
        assert windows["kcal"][0] <= eaten["kcal"] <= windows["kcal"][1], row.seed_id
        assert (
            windows["protein_g"][0] <= eaten["protein_g"] <= windows["protein_g"][1]
        ), row.seed_id
        assert not hasattr(row, "windows")


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


def test_evaluate_rows_cover_tiers_and_resolve():
    import re
    from collections import Counter

    catalog = load_catalog()
    assert len(EVALUATE_ROWS) >= 55
    counts = Counter(row.tier for row in EVALUATE_ROWS)
    assert counts["single"] >= 7
    assert counts["pair"] >= 12
    assert counts["triple"] >= 12
    assert counts["long"] >= 6
    assert counts["forced_grams"] >= 4
    assert counts["synonym"] >= 3
    assert_evaluate_rows(catalog)
    banned = {("whole_wheat_bread", "a slice"), ("broccoli", "a piece")}
    for row in EVALUATE_ROWS:
        for food_id, phrase in row.items:
            assert (food_id, phrase) not in banned, row.seed_id
            assert resolve_portion(food_id, phrase, catalog) is not None, (
                row.seed_id,
                food_id,
                phrase,
            )

    generator = Generator()
    knobs = generator._difficulty(None)
    base = generator._make_s0(0, knobs)
    keys = []
    for row in EVALUATE_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._evaluate_from_row(s0, row)
        task = Task("draft", "evaluate", query, s0, oracle)
        assert validate_draft(task) == [], (row.seed_id, validate_draft(task))
        keys.append(semantic_key(task))
    assert len(keys) == len(EVALUATE_ROWS)
    assert len(set(keys)) == len(EVALUATE_ROWS)

    for row in EVALUATE_ROWS:
        if row.tier != "forced_grams":
            continue
        for food_id, _phrase in row.items:
            assert not (catalog[food_id].get("portions") or {}), (row.seed_id, food_id)
        assert re.search(r"\d+\s*g", row.query, re.I), row.seed_id

    synonym_targets = {"shrimp", "oats", "greek_yogurt"}
    seen_hidden: set[str] = set()
    for row in EVALUATE_ROWS:
        if row.tier != "synonym":
            continue
        hidden = [food_id for food_id, _phrase in row.items if food_id not in row.query.lower()]
        assert hidden, row.seed_id
        assert set(hidden) & synonym_targets, (row.seed_id, hidden)
        seen_hidden.update(set(hidden) & synonym_targets)
        for food_id, phrase in row.items:
            assert resolve_portion(food_id, phrase, catalog) is not None
    assert seen_hidden == synonym_targets


def test_all_update_rows_have_distinct_semantic_keys():
    generator = Generator()
    knobs = generator._difficulty(None)
    base = generator._make_s0(0, knobs)
    keys = []
    for row in UPDATE_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._update_from_row(s0, row)
        keys.append(semantic_key(Task("draft", "update", query, s0, oracle)))
    assert len(keys) == len(UPDATE_ROWS)
    assert len(set(keys)) == len(UPDATE_ROWS)


def test_update_constrain_evaluate_seeds_change_semantic_key():
    update_keys = {
        semantic_key(Generator().sample(seed, family="update"))
        for seed in range(20)
    }
    constrain_keys = {
        semantic_key(Generator().sample(seed, family="constrain"))
        for seed in range(20)
    }
    evaluate_keys = {
        semantic_key(Generator().sample(seed, family="evaluate"))
        for seed in range(20)
    }
    assert len(update_keys) > 1
    assert len(constrain_keys) > 1
    assert len(evaluate_keys) > 1


def _fresh_s0(base):
    from nutrienv.world.types import WorldState

    return WorldState(
        profile=base.profile,
        ledger=list(base.ledger),
        catalog=base.catalog,
        last_plan=list(base.last_plan),
    )


def test_every_table_row_materializes_to_a_clean_draft():
    from nutrienv.bench.generator import Task

    generator = Generator()
    knobs = generator._difficulty(None)
    base = generator._make_s0(0, knobs)

    def check(family, persona, query, oracle, s0, situations=()):
        task = Task("draft", family, query, s0, oracle, situations, persona)
        assert validate_draft(task) == [], (family, query, validate_draft(task))

    for row in LEFTOVER_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._leftover_from_row(s0, row)
        check("recommend", "leftover", query, oracle, s0)

    for row in UPDATE_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._update_from_row(s0, row)
        check("update", "everyday", query, oracle, s0)

    for row in CONSTRAIN_ROWS:
        s0 = _fresh_s0(base)
        if row.kind == "condition":
            query, oracle = generator._condition_from_row(s0, row)
            check("constrain", "everyday", query, oracle, s0, ("condition_suitability",))
        else:
            query, oracle = generator._conflict_from_row(s0, row)
            check("constrain", "everyday", query, oracle, s0, ("conflict_windows",))

    for row in EVALUATE_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._evaluate_from_row(s0, row)
        check("evaluate", "everyday", query, oracle, s0)


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
