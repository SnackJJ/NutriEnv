"""Search-returned FDC ids and staple slugs must write the same Pass identity."""

from __future__ import annotations

from nutrienv.bench import GOLD_SPLIT_PATH, load_split
from nutrienv.bench.scorer import Scorer
from nutrienv.env import NutriEnv
from nutrienv.world.catalog_store import GOLD_CATALOG_PATH
from nutrienv.world.portions import resolve_portion
from nutrienv.world.types import ledger_totals


def test_gold_log_passes_with_search_fdc_id_and_slug() -> None:
    assert GOLD_CATALOG_PATH.is_file()
    task = next(item for item in load_split(GOLD_SPLIT_PATH) if item.id == "v0-log-fuzzy-001")
    scorer = Scorer()
    row = task.oracle.ledger_tail[0]
    assert row.food_id.isdigit()

    env = NutriEnv()
    env.reset(task.s0)
    hits = env.step({"op": "search_foods", "q": "whole milk"})["observation"]["results"]
    assert hits
    fdc_id = hits[0]["food_id"]
    assert fdc_id.isdigit()
    assert env.step(
        {
            "op": "log_meal",
            "food_id": fdc_id,
            "grams": row.grams,
            "eaten_at": row.eaten_at,
        }
    )["ok"]
    via_search = scorer.score(env.state(), task.oracle)
    assert via_search == {"passed": True, "tag": "pass"}, via_search

    env.reset(task.s0)
    assert env.step(
        {
            "op": "log_meal",
            "food_id": "milk_whole",
            "grams": row.grams,
            "eaten_at": row.eaten_at,
        }
    )["ok"]
    via_slug = scorer.score(env.state(), task.oracle)
    assert via_slug == {"passed": True, "tag": "pass"}, via_slug
    assert env.state().ledger[-1].food_id == fdc_id == row.food_id


def test_gold_evaluate_passes_with_search_fdc_ids() -> None:
    assert GOLD_CATALOG_PATH.is_file()
    task = next(item for item in load_split(GOLD_SPLIT_PATH) if item.id == "v0-eval-plan-001")
    env = NutriEnv()
    env.reset(task.s0)
    chicken = env.step({"op": "search_foods", "q": "chicken breast"})["observation"]["results"][0]
    assert chicken["food_id"].isdigit()
    rebuilt = [
        {"food_id": chicken["food_id"], "grams": task.oracle.last_plan[0]["grams"]},
        {"food_id": "white_rice", "grams": task.oracle.last_plan[1]["grams"]},
        {"food_id": "broccoli", "grams": task.oracle.last_plan[2]["grams"]},
        {"food_id": "olive_oil", "grams": task.oracle.last_plan[3]["grams"]},
    ]
    assert env.step({"op": "submit_plan", "items": rebuilt})["ok"]
    score = Scorer().score(env.state(), task.oracle)
    assert score == {"passed": True, "tag": "pass"}, score


def test_staple_aliases_and_spoken_portions_match_official_rows() -> None:
    assert GOLD_CATALOG_PATH.is_file()
    task = load_split(GOLD_SPLIT_PATH)[0]
    catalog = task.s0.catalog
    expected = {
        "oats": "2708489",
        "chicken_breast": "171477",
        "greek_yogurt": "2705424",
        "white_rice": "2708408",
        "banana": "2709224",
    }
    for slug, fdc_id in expected.items():
        assert catalog.canonical_id(slug) == fdc_id, slug
    assert resolve_portion("banana", "a piece", catalog) == 126.0
    assert resolve_portion("greek_yogurt", "a cup", catalog) == 245.0
    assert resolve_portion("milk_whole", "half a cup", catalog) == 122.0
    assert resolve_portion("olive_oil", "a tablespoon", catalog) == 13.5
    assert resolve_portion("oats", "2 ounces", catalog) == 56.7


def test_gold_json_stays_slug_authored_and_catalog_has_no_branded() -> None:
    import json
    import sqlite3

    payload = json.loads(GOLD_SPLIT_PATH.read_text(encoding="utf-8"))
    assert payload["catalog"] == "data/fdc/catalog.sqlite"
    text = GOLD_SPLIT_PATH.read_text(encoding="utf-8")
    assert '"food_id": "milk_whole"' in text
    assert '"food_id": "2705385"' not in text
    conn = sqlite3.connect(GOLD_CATALOG_PATH)
    branded = conn.execute(
        "SELECT COUNT(*) FROM foods WHERE data_type = 'branded_food'"
    ).fetchone()[0]
    conn.close()
    assert branded == 0


def test_leftover_oracles_equal_live_ledger_remainder() -> None:
    leftovers = [
        task
        for task in load_split(GOLD_SPLIT_PATH)
        if task.persona == "leftover" and task.family == "recommend"
    ]
    assert leftovers
    for task in leftovers:
        eaten = ledger_totals(task.s0.ledger, task.s0.catalog)
        for key, (lo, hi) in task.s0.profile.windows.items():
            used = eaten.get(key, 0.0)
            expected = (round(max(0.0, lo - used), 2), round(max(0.0, hi - used), 2))
            assert task.oracle.plan_windows[key] == expected, (task.id, key)
