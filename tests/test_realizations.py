from nutrienv.bench.realizations import (
    CONSTRAIN_ROWS,
    EVALUATE_ROWS,
    FUZZY_ROWS,
    LEDGER_GAP_ROWS,
    LEFTOVER_ROWS,
    MULTI_ITEM_LOG_ROWS,
    NEAR_SYNONYM_ROWS,
    RECOMMEND_ROWS,
    UNIT_CONVERT_ROWS,
    UPDATE_ROWS,
    assert_constrain_rows,
    assert_evaluate_rows,
    assert_fuzzy_resolves,
    assert_leftover_rows,
    assert_log_situation_rows,
    assert_recommend_rows,
    assert_update_rows,
    evaluate_windows,
    fuzzy_key,
    leftover_key,
    recommend_key,
)
from nutrienv.bench.validator import (
    _any_pair_unsatisfiable,
    semantic_key,
    validate_draft,
)
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
    assert len(UPDATE_ROWS) >= 34
    assert len(CONSTRAIN_ROWS) >= 42
    assert {row.kind for row in CONSTRAIN_ROWS} == {"condition", "conflict"}
    assert len([row for row in CONSTRAIN_ROWS if row.kind == "condition"]) >= 19
    assert len([row for row in CONSTRAIN_ROWS if row.kind == "conflict"]) >= 23
    assert len(EVALUATE_ROWS) >= 55
    assert_update_rows(catalog)
    assert_constrain_rows(catalog)
    assert_evaluate_rows(catalog)
    assert_recommend_rows(catalog)


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
    assert counts["explicit_grams"] >= 4
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
        if row.tier != "explicit_grams":
            continue
        assert re.search(r"\d+\s*g", row.query, re.I), row.seed_id
        assert any(
            not (catalog[food_id].get("portions") or {})
            for food_id, _phrase in row.items
        ), row.seed_id

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

    for row in RECOMMEND_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._recommend_from_row(s0, row)
        check("recommend", row.persona, query, oracle, s0)

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

    for row in MULTI_ITEM_LOG_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._multi_item_from_row(s0, row)
        check("log", "everyday", query, oracle, s0, ("multi_item_log",))

    for row in UNIT_CONVERT_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._unit_convert_from_row(s0, row)
        check("log", "everyday", query, oracle, s0, ("unit_convert",))

    for row in NEAR_SYNONYM_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._near_synonym_from_row(s0, row)
        check("log", "everyday", query, oracle, s0, ("near_synonym",))

    for row in LEDGER_GAP_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._ledger_gap_from_row(s0, row)
        check("log", "everyday", query, oracle, s0, ("ledger_gap",))


def test_recommend_table_covers_declared_axes():
    catalog = load_catalog()
    assert len(RECOMMEND_ROWS) >= 40
    assert_recommend_rows(catalog)
    personas = {row.persona for row in RECOMMEND_ROWS}
    assert {"everyday", "cut", "gym", "flex", "htn"} <= personas
    assert "leftover" not in personas
    everyday = [row for row in RECOMMEND_ROWS if row.persona == "everyday"]
    assert len(everyday) > len(RECOMMEND_ROWS) / 2
    occasions = {row.occasion for row in RECOMMEND_ROWS}
    assert {"breakfast", "lunch", "dinner", "snack", "post-workout"} <= occasions
    tags: set[str] = set()
    for row in RECOMMEND_ROWS:
        tags.update(row.allergies)
    assert {
        "milk",
        "wheat",
        "gluten",
        "fish",
        "egg",
        "peanut",
        "soy",
        "tree_nut",
        "shellfish",
    } <= tags
    assert any(len(row.allergies) == 2 for row in RECOMMEND_ROWS)
    assert any(len(row.allergies) >= 3 for row in RECOMMEND_ROWS)
    third = [
        row
        for row in RECOMMEND_ROWS
        if set(row.windows) - {"kcal", "protein_g"}
    ]
    assert len(third) >= 10
    keys = [recommend_key(row) for row in RECOMMEND_ROWS]
    assert len(keys) == len(set(keys))
    for row in RECOMMEND_ROWS:
        lower = row.query.lower()
        assert "already ate" not in lower, row.seed_id
        assert "i ate" not in lower, row.seed_id


def test_rec_gym_peanut_is_not_the_gold_gym_window():
    row = next(item for item in RECOMMEND_ROWS if item.seed_id == "rec-gym-peanut")
    assert row.persona == "gym"
    assert row.allergies == ("peanut",)
    assert row.plan_preset == {"goal": "muscle"}
    assert row.windows != {"kcal": (450.0, 800.0), "protein_g": (40.0, 70.0)}


def test_ns_evoo_ledger_is_not_the_gold_oil_row():
    row = next(item for item in NEAR_SYNONYM_ROWS if item.seed_id == "ns-evoo")
    assert row.food_id == "olive_oil"
    assert (row.phrase, row.slot) != ("a tablespoon", "today-lunch")


def test_keep_fat_down_rows_have_an_open_fat_floor():
    wanted = {"rec-lunch-fat", "rec-flex-fat", "rec-dinner-fat-ceil"}
    found = {row.seed_id for row in RECOMMEND_ROWS if row.seed_id in wanted}
    assert found == wanted
    for row in RECOMMEND_ROWS:
        if row.seed_id not in wanted:
            continue
        lo, hi = row.windows["fat_g"]
        assert lo == 0.0, row.seed_id
        assert hi > 0.0, row.seed_id


def test_constrain_conflict_spans_three_mechanisms():
    conflict = [row for row in CONSTRAIN_ROWS if row.kind == "conflict"]
    condition = [row for row in CONSTRAIN_ROWS if row.kind == "condition"]
    assert len(CONSTRAIN_ROWS) >= 42
    assert len(condition) >= 19
    assert len(conflict) >= 23
    mechanisms = {row.mechanism for row in conflict if row.mechanism}
    assert {"other_pair", "near_miss"} <= mechanisms
    frozen = {
        "cf-50-70",
        "cf-70-90",
        "cf-90-110",
        "cf-near-200-56",
        "cf-near-400-111",
        "cf-near-800-221",
    }
    assert frozen <= {row.seed_id for row in conflict}


def test_allergen_conflict_rows_are_infeasible_only_with_the_allergy():
    catalog = load_catalog()
    allergen_rows = [
        row
        for row in CONSTRAIN_ROWS
        if row.kind == "conflict" and row.mechanism == "allergen"
    ]
    for row in allergen_rows:
        assert _any_pair_unsatisfiable(
            row.windows, catalog, row.allergies
        ), row.seed_id
        assert not _any_pair_unsatisfiable(
            row.windows, catalog, ()
        ), row.seed_id


def test_all_recommend_rows_have_distinct_semantic_keys():
    generator = Generator()
    knobs = generator._difficulty(None)
    base = generator._make_s0(0, knobs)
    keys = []
    for row in RECOMMEND_ROWS:
        s0 = _fresh_s0(base)
        query, oracle = generator._recommend_from_row(s0, row)
        keys.append(semantic_key(Task("draft", "recommend", query, s0, oracle, (), row.persona)))
    assert len(keys) == len(RECOMMEND_ROWS)
    assert len(set(keys)) == len(RECOMMEND_ROWS)


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


def _is_asymmetric(delta) -> bool:
    return isinstance(delta, tuple) and delta[0] != delta[1]


def test_log_situation_tables_cover_the_four_shapes():
    catalog = load_catalog()
    assert len(MULTI_ITEM_LOG_ROWS) >= 6
    assert len(UNIT_CONVERT_ROWS) >= 5
    assert len(NEAR_SYNONYM_ROWS) >= 5
    assert len(LEDGER_GAP_ROWS) >= 3
    total = (
        len(MULTI_ITEM_LOG_ROWS)
        + len(UNIT_CONVERT_ROWS)
        + len(NEAR_SYNONYM_ROWS)
        + len(LEDGER_GAP_ROWS)
    )
    assert total >= 24
    assert_log_situation_rows(catalog)
    banned = {("whole_wheat_bread", "a slice"), ("broccoli", "a piece")}
    counts = {len(row.items) for row in MULTI_ITEM_LOG_ROWS}
    assert {2, 3, 4} <= counts
    slots = {row.slot for row in MULTI_ITEM_LOG_ROWS}
    assert len(slots) >= 3
    for row in MULTI_ITEM_LOG_ROWS:
        for food_id, phrase in row.items:
            assert (food_id, phrase) not in banned, row.seed_id
            assert resolve_portion(food_id, phrase, catalog) is not None, (
                row.seed_id,
                food_id,
                phrase,
            )
    phrases = {row.phrase for row in UNIT_CONVERT_ROWS}
    assert {"2 ounces", "3 ounces", "1 ounce", "half an ounce", "4 oz", "3.5 ounces"} <= phrases
    assert any("cup" in row.phrase for row in UNIT_CONVERT_ROWS)
    foods = {row.food_id for row in UNIT_CONVERT_ROWS}
    assert len(foods) >= 5
    for row in NEAR_SYNONYM_ROWS:
        aliases = {str(alias).lower() for alias in (catalog[row.food_id].get("aliases") or [])}
        assert row.spoken.lower() in aliases, row.seed_id
        assert row.spoken.lower() != row.food_id.lower(), row.seed_id
        assert resolve_portion(row.food_id, row.phrase, catalog) is not None, row.seed_id
    missing_slots = {row.missing[2] for row in LEDGER_GAP_ROWS}
    assert {"today-breakfast", "today-lunch", "today-dinner", "today-snack"} <= missing_slots
    surround_counts = {len(row.surround) for row in LEDGER_GAP_ROWS}
    assert len(surround_counts) >= 2
    for row in LEDGER_GAP_ROWS:
        food_id, phrase, slot = row.missing
        assert slot not in {eaten_at for _food, _grams, eaten_at in row.surround}, row.seed_id
        assert resolve_portion(food_id, phrase, catalog) is not None, row.seed_id


def test_update_table_covers_new_axes():
    catalog = load_catalog()
    assert len(UPDATE_ROWS) >= 34
    assert_update_rows(catalog)
    removals = [row for row in UPDATE_ROWS if row.remove_allergens]
    single_bound = [
        row
        for row in UPDATE_ROWS
        if row.window_shifts and any(_is_asymmetric(delta) for delta in row.window_shifts.values())
    ]
    two_window = [row for row in UPDATE_ROWS if row.window_shifts and len(row.window_shifts) >= 2]
    multi_allergen = [row for row in UPDATE_ROWS if len(row.add_allergens) >= 2]
    preset = [row for row in UPDATE_ROWS if row.set_plan_preset]
    assert len(removals) >= 4
    assert len(single_bound) >= 6
    assert len(two_window) >= 3
    assert len(multi_allergen) >= 3
    assert len(preset) >= 2


def test_log_situation_seeds_change_semantic_key():
    for situation in ("multi_item_log", "unit_convert", "near_synonym", "ledger_gap"):
        keys = {
            semantic_key(Generator().sample(seed, situation=situation))
            for seed in range(20)
        }
        assert len(keys) > 1, situation
        assert Generator().sample(3, situation=situation) == Generator().sample(
            3, situation=situation
        )


def test_log_situation_builders_are_table_backed():
    import inspect

    from nutrienv.bench.generator import Generator as Gen

    assert "MULTI_ITEM_LOG_ROWS" in inspect.getsource(Gen._build_situation_multi_item_log)
    assert "UNIT_CONVERT_ROWS" in inspect.getsource(Gen._build_situation_unit_convert)
    assert "NEAR_SYNONYM_ROWS" in inspect.getsource(Gen._build_situation_near_synonym)
    assert "LEDGER_GAP_ROWS" in inspect.getsource(Gen._build_situation_ledger_gap)
    assert "60 g rolled oats" not in inspect.getsource(Gen._build_situation_multi_item_log)
    assert "2 ounces of oats" not in inspect.getsource(Gen._build_situation_unit_convert)
    assert "prawns" not in inspect.getsource(Gen._build_situation_near_synonym)
    assert "150 g chicken breast" not in inspect.getsource(Gen._build_situation_ledger_gap)
