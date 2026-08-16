"""Real assertions against the v0.5-gold review-sheet export."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from nutrienv.bench.split import load_split
from nutrienv.world.portions import OUNCE_GRAMS, resolve_portion

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_review_sheet as brs  # noqa: E402

SPLIT = ROOT / "data" / "splits" / "v0.5-gold.json"
ALLOCATION = {"log": 48, "recommend": 72, "evaluate": 48, "update": 36, "constrain": 36}
GLOSS = re.compile(r"^(\S+) x (\S+) \(([0-9.]+) g\) = ([0-9.]+) g$")
MATERIALIZED = ("user_id", "allergies", "medications", "plan_preset", "version")


@pytest.fixture(scope="module")
def raw_split() -> dict:
    return json.loads(SPLIT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def tasks():
    return {task.id: task for task in load_split(SPLIT)}


@pytest.fixture(scope="module")
def sheet(tmp_path_factory) -> dict:
    out = tmp_path_factory.mktemp("review") / "review-sheet.json"
    before = SPLIT.read_bytes()
    assert brs.main([
        "--split", str(SPLIT),
        "--out", str(out),
        "--allow-catalog-sha-mismatch",
    ]) == 0
    assert SPLIT.read_bytes() == before
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def catalog(sheet: dict):
    return brs.FoodCatalog.from_sqlite(ROOT / sheet["catalog"])


def test_export_counts_and_split_untouched(sheet: dict) -> None:
    assert len(sheet["items"]) == sheet["counts"]["total"] == 240
    assert sheet["counts"]["by_family"] == ALLOCATION


def test_expected_food_rows_have_real_names(sheet: dict, catalog) -> None:
    seen = 0
    for item in sheet["items"]:
        for row in (
            item["expected"]["rows"]
            + item["s0"]["ledger"]
            + item["s0"]["last_plan"]
        ):
            seen += 1
            assert row["name"] == catalog[row["food_id"]]["name"], (item["id"], row)
            assert row["name"] != row["food_id"]
    assert seen > 0


def test_grams_explained_round_trips(sheet: dict, catalog) -> None:
    for item in sheet["items"]:
        for row in item["expected"]["rows"]:
            gloss = row["grams_explained"]
            if gloss is None:
                continue
            match = GLOSS.fullmatch(gloss)
            assert match, (item["id"], gloss)
            mult, unit, gpu, rhs = match.group(1), match.group(2), float(match.group(3)), float(match.group(4))
            table = {**(catalog[row["food_id"]].get("portions") or {}), "oz": OUNCE_GRAMS, "g": 1.0}
            assert gpu == table[unit], (item["id"], gloss, table.get(unit))
            assert rhs == row["grams"]
            assert resolve_portion(row["food_id"], f"{mult} {unit}", catalog) == row["grams"]


def test_update_profile_diff_covers_every_field(sheet: dict, tasks) -> None:
    by_id = {item["id"]: item for item in sheet["items"]}
    for task in tasks.values():
        if task.family != "update":
            continue
        fields = {entry["field"] for entry in by_id[task.id]["profile_diff"]}
        missing = [name for name in MATERIALIZED if name not in fields]
        assert not missing, (task.id, missing)
        nuts = set(task.s0.profile.windows) | set(task.oracle.profile.windows)
        for nut in nuts:
            assert f"windows.{nut}.floor" in fields, (task.id, nut, fields)
            assert f"windows.{nut}.ceiling" in fields, (task.id, nut, fields)


def test_window_check_inside_matches_bounds(sheet: dict, catalog) -> None:
    checked = 0
    for item in sheet["items"]:
        if item["flags"]["plan_must_fit_windows"]:
            wins = item["flags"]["plan_windows"] or item["s0"]["windows"]
            names = {row["nutrient"] for row in item["window_check"] if row["window"] is not None}
            assert set(wins) <= names, (item["id"], wins, names)
        if not item["expected"]["rows"] or not item["window_check"]:
            continue
        totals: dict[str, float] = {}
        for row in item["expected"]["rows"]:
            for key, amount in (catalog[row["food_id"]].get("nutrients") or {}).items():
                if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                    totals[key] = totals.get(key, 0.0) + float(amount) * float(row["grams"]) / 100.0
        for row in item["window_check"]:
            if row["total"] is None:
                assert row["inside"] is None
                continue
            recomputed = round(totals.get(row["nutrient"], 0.0), 2)
            assert row["total"] == recomputed, (item["id"], row, recomputed)
            checked += 1
            if row["window"] is None:
                assert row["inside"] is None
            else:
                lo, hi = row["window"]
                assert row["inside"] == (lo <= recomputed <= hi), (item["id"], row, recomputed)
    assert checked > 0


def test_empty_expected_rows_do_not_fabricate_window_verdicts(sheet: dict) -> None:
    empty = [i for i in sheet["items"] if not i["expected"]["rows"]]
    assert empty
    for item in empty:
        assert item["scored_plan_is_fixed"] is False, item["id"]
        for row in item["window_check"]:
            assert row["total"] is None and row["inside"] is None, (item["id"], row)
    safe = next(i for i in sheet["items"] if i["id"] == "v0-rec-safe-001")
    assert safe["scored_plan_is_fixed"] is False
    assert {r["nutrient"] for r in safe["window_check"]} >= {"kcal", "protein_g"}


def test_s0_last_plan_is_exported_for_allow_empty_plan(sheet: dict) -> None:
    item = next(i for i in sheet["items"] if i["id"] == "v0-rec-conflict-001")
    assert item["expected"]["kind"] == "no_plan_required"
    assert item["s0"]["last_plan"]
    row = item["s0"]["last_plan"][0]
    assert row["food_id"] == "chicken_breast"
    assert row["scored_food_id"] == "171477"
    assert row["name"]
    assert "eaten_at" not in row
    assert row["nutrients_at_grams"]


def test_materialized_profile_fields_are_visible(sheet: dict) -> None:
    for item in sheet["items"]:
        other = item["s0"]["other_profile_fields"]
        assert "medications" in other and "version" in other, item["id"]
        assert item["s0"]["plan_preset"] is not None
        assert isinstance(item["s0"]["plan_preset"], dict)


def test_last_plan_rows_omit_eaten_at(sheet: dict) -> None:
    found = 0
    for item in sheet["items"]:
        if item["expected"]["kind"] == "last_plan":
            for row in item["expected"]["rows"]:
                assert "eaten_at" not in row, item["id"]
                found += 1
        for row in item["s0"]["last_plan"]:
            assert "eaten_at" not in row, item["id"]
        for row in item["s0"]["ledger"]:
            assert "eaten_at" in row, item["id"]
    assert found > 0


def test_scored_food_id_is_canonical(sheet: dict, catalog) -> None:
    for item in sheet["items"]:
        for row in item["expected"]["rows"] + item["s0"]["ledger"] + item["s0"]["last_plan"]:
            assert row["scored_food_id"] == catalog.canonical_id(row["food_id"]), item["id"]
            assert row["fdc_id"] is not None


def test_allergens_are_enforced_when_plan_is_scored(sheet: dict) -> None:
    rec = next(i for i in sheet["items"] if i["id"] == "v0-rec-safe-001")
    ev = next(i for i in sheet["items"] if i["id"] == "v0-eval-plan-001")
    upd = next(i for i in sheet["items"] if i["id"] == "v0-update-allergy-001")
    assert rec["allergens_are_enforced"] is True
    assert ev["allergens_are_enforced"] is True
    assert ev["flags"]["plan_must_be_safe"] is False
    assert "allergen" in ev["contract"].lower()
    assert upd["allergens_are_enforced"] is False


def test_multi_window_only_on_two_nutrient_updates(sheet: dict) -> None:
    tagged = [i for i in sheet["items"] if "multi_window" in i["risk"]]
    assert tagged
    assert all(i["family"] == "update" for i in tagged)
    assert {i["id"] for i in tagged} == {
        "v05-upd-two-kcal-200-prot-20", "v05-upd-two-kcal-300-prot-30",
    }


def test_stated_grams_are_not_unexplained(sheet: dict) -> None:
    by_id = {i["id"]: i for i in sheet["items"]}
    for item_id in (
        "v0-log-gap-001", "v0-log-eaten-001", "v0-eval-plan-001", "v0-log-prawn-001",
    ):
        assert "unexplained_grams" not in by_id[item_id]["risk"], item_id


def test_state_unpinned_skips_fruit_and_flags_oatmeal(sheet: dict) -> None:
    by_id = {i["id"]: i for i in sheet["items"]}
    assert "state_unpinned" in by_id["v03-eval-syn-oatmeal-banana"]["risk"]
    fruit = next(
        i for i in sheet["items"]
        if i["expected"]["rows"]
        and all("apple" in r["name"].lower() or "orange" in r["name"].lower()
                or "banana" in r["name"].lower() or "yogurt" in r["name"].lower()
                for r in i["expected"]["rows"])
        and not any("oat" in r["name"].lower() for r in i["expected"]["rows"])
    )
    assert "state_unpinned" not in fruit["risk"], fruit["id"]


def test_can_you_is_not_spoken_portion(sheet: dict) -> None:
    item = next(i for i in sheet["items"] if i["id"] == "v0-rec-safe-001")
    assert item["query"].startswith("Can you")
    assert "spoken_portion" not in item["risk"]


def test_search_term_follows_spoken_phrase(sheet: dict) -> None:
    by_id = {i["id"]: i for i in sheet["items"]}
    shrimp = by_id["v0-log-eaten-001"]["expected"]["rows"][0]
    assert shrimp["other_candidates"], shrimp
    assert any("shrimp" in c["name"].lower() for c in shrimp["other_candidates"])
    oats = next(r for r in by_id["v03-eval-syn-oatmeal-banana"]["expected"]["rows"] if r["food_id"] == "oats")
    assert any(c["name"] == "Oatmeal, NFS" for c in oats["other_candidates"]), oats["other_candidates"]
    oil = by_id["v0-log-oil-001"]["expected"]["rows"][0]
    assert not any(
        "soy" in c["name"].lower() or "canola" in c["name"].lower()
        for c in oil["other_candidates"]
    ) or "olive oil" in by_id["v0-log-oil-001"]["query"].lower()
    # pinned "olive oil" should not raise multi_candidate just from searching "oil"
    # if candidates remain, they should be olive-oil siblings, not a random oil
    if "multi_candidate_food" in by_id["v0-log-oil-001"]["risk"]:
        assert all("oil" in c["name"].lower() for c in oil["other_candidates"])


def test_grams_explained_is_derived_when_unit_unspoken(sheet: dict) -> None:
    item = next(i for i in sheet["items"] if i["id"] == "v0-log-multi-001")
    oats = next(r for r in item["expected"]["rows"] if r["food_id"] == "oats")
    assert oats["grams_explained"]
    assert oats["grams_explained_is_derived"] is True
    cup = next(i for i in sheet["items"] if i["id"] == "v0-log-fuzzy-001")
    milk = cup["expected"]["rows"][0]
    assert milk["grams_explained_is_derived"] is False


def test_grams_explained_null_when_ratio_is_not_clean() -> None:
    catalog = {"milk_whole": {"name": "Milk, whole", "portions": {"cup": 244.0}, "nutrients": {"kcal": 61.0}}}
    assert brs.explain_grams("milk_whole", 121.0, catalog) is None
    assert brs.explain_grams("milk_whole", 100.0, catalog) is None
    assert (
        brs.explain_grams("milk_whole", 122.0, catalog)
        == "0.5 x cup (244.0 g) = 122.0 g"
    )


def test_explain_grams_is_not_stolen_by_fl_oz(catalog) -> None:
    # Design §6 step 1: 4 x fl_oz is an integer ratio but must not beat 0.5 cup.
    assert (
        brs.explain_grams("milk_whole", 122.0, catalog)
        == "0.5 x cup (244.0 g) = 122.0 g"
    )


def test_three_point_five_oz_is_explained(sheet: dict) -> None:
    item = next(i for i in sheet["items"] if i["id"] == "v05-log-uc-salmon-3-5oz")
    row = item["expected"]["rows"][0]
    assert row["grams"] == 99.23
    assert row["grams_explained"] == "3.5 x oz (28.35 g) = 99.23 g"
