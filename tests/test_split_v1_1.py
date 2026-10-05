"""nutrienv-v1.1: v1.0 re-derived under the AMDR daily windows, plus the backlog content fixes."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from nutrienv.bench import EXAM_SPLIT_PATH, load_split
from nutrienv.bench.realize import scored_oracles
from nutrienv.bench.validator import validate_draft
from nutrienv.world.daily_windows import derive_profile_windows

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def builder():
    path = ROOT / "scripts" / "build_split_v1_1.py"
    spec = importlib.util.spec_from_file_location("build_split_v1_1_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def v11() -> dict:
    return {task.id: task for task in load_split(EXAM_SPLIT_PATH)}


def test_the_files_are_what_the_builder_makes(builder) -> None:
    out, _notes = builder.build()
    assert EXAM_SPLIT_PATH.name == "nutrienv-v1.1.json"
    assert EXAM_SPLIT_PATH.read_text(encoding="utf-8") == builder.dump(EXAM_SPLIT_PATH, out)
    for path, reduction in builder.reductions(out).items():
        assert path.read_text(encoding="utf-8") == builder.dump(path, reduction), path.name


def test_the_reductions_are_v1_1_items(v11) -> None:
    for name in ("nutrienv-mini.json", "mini-fast.json", "mini-harness.json"):
        for task in load_split(EXAM_SPLIT_PATH.with_name(name)):
            assert task == v11[task.id], (name, task.id)


def test_same_tasks_as_v1_0_and_every_s0_window_is_the_formulas(v11) -> None:
    v10 = {task.id for task in load_split(EXAM_SPLIT_PATH.with_name("nutrienv-v1.0.json"))}
    assert set(v11) == v10
    for task in v11.values():
        assert task.s0.profile.windows == derive_profile_windows(task.s0.profile), task.id


def test_no_pinned_window_disagrees_with_the_scorer(v11) -> None:
    # v1.0 carried three stale amend pins; v1.1 authors every pin on the Scorer's own basis.
    for task in v11.values():
        issues = [issue for issue in validate_draft(task) if "plan_windows" in issue]
        assert issues == [], task.id


def test_content_fixes(v11) -> None:
    from nutrienv.world.catalog_store import load_catalog
    from nutrienv.world.portions import resolve_portion

    crackers = v11["adr24-comp-8256"]
    assert "a serving of sandwich crackers" in crackers.query
    tail = [row for o in scored_oracles(crackers.oracle) for row in (o.ledger_tail or ())]
    assert [(row.food_id, row.grams) for row in tail] == [("2708171", 18.0)]
    assert resolve_portion("2708171", "a serving", crackers.s0.catalog) == 18.0

    # Each basket food is named so search narrows to the one entry the basket holds.
    store = load_catalog(ROOT / "data" / "fdc" / "catalog.sqlite")
    for phrase, food_id in (
        ("California sushi roll", "2708961"),
        ("ramen with meat and egg", "2709158"),
        ("egg salad made with mayonnaise", "2707182"),
    ):
        assert store.search(phrase)[0]["food_id"] == food_id, phrase
    for i in range(1, 6):
        task = v11[f"adr29-conv-0{i}"]
        assert "12 items" in task.query
        assert len(task.s0.allowed_food_ids) == 28
        assert {"2708961", "2709158", "2707182"} <= task.s0.allowed_food_ids
        assert not {"2708959", "2709153", "2708965"} & task.s0.allowed_food_ids


def test_reviewed_portion_evidence_computes_the_gold(v11, builder) -> None:
    from nutrienv.world.portion_evidence import portion_grams

    revisions = json.loads(builder.REVISIONS.read_text(encoding="utf-8"))["changes"]
    for revision in revisions:
        task = v11[revision["task_id"]]
        for check in revision.get("ledger_portion_fixes", []):
            assert task.query == revision["new_query"]
            assert portion_grams(
                check["food_id"], check["portion"], task.s0.catalog
            ) == pytest.approx(check["grams"]), task.id
            tails = [row for child in scored_oracles(task.oracle)
                     for row in (child.ledger_tail or child.ledger or ())]
            assert any(row.food_id == check["food_id"] and row.grams == check["grams"]
                       for row in tails), task.id


def test_inventory_accepts_exactly_reviewed_options(v11, builder) -> None:
    source = {task.id: task for task in load_split(builder.SOURCE)}
    revisions = json.loads(builder.REVISIONS.read_text())["changes"]
    for revision in revisions:
        if not revision.get("inventory_options"):
            continue
        task = v11[revision["task_id"]]
        allowed = set(source[task.id].s0.allowed_food_ids)
        if task.id.startswith("adr29-conv-0"):
            allowed -= builder._BASKET_DROPS
            allowed = {builder._BASKET_SWAPS.get(food, food) for food in allowed}
        for options in revision["inventory_options"].values():
            for option in options:
                assert task.s0.catalog[option["food_id"]]["name"] == option["catalog_name"]
                allowed.add(option["food_id"])
        assert task.s0.allowed_food_ids == allowed
        assert task.query == revision["new_query"]


def test_logged_options_have_their_own_evidenced_portions(v11, builder) -> None:
    from nutrienv.world.portion_evidence import portion_grams

    revisions = json.loads(builder.REVISIONS.read_text())["changes"]
    for revision in revisions:
        choices = revision.get("ledger_food_options", {})
        if not choices:
            continue
        task = v11[revision["task_id"]]
        for child in scored_oracles(task.oracle):
            if child.ledger is None:
                continue
            assert child.ledger_variants, task.id
            for specification in choices.values():
                for option in specification["options"]:
                    grams = portion_grams(option["food_id"], specification["portion"], task.s0.catalog)
                    assert any(
                        any(row.food_id == option["food_id"] and row.grams == grams for row in ledger)
                        for ledger in child.ledger_variants
                    ), (task.id, option["food_id"])


def test_builder_refuses_to_overwrite_an_independently_changed_query(builder, tmp_path) -> None:
    source = json.loads(builder.SOURCE.read_text(encoding="utf-8"))
    next(item for item in source["items"] if item["id"] == "adr29-fridge-03")["query"] = (
        "A separately reviewed dinner request."
    )
    path = tmp_path / "source.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(ValueError, match="adr29-fridge-03: query differs"):
        builder.build(path)


def test_builder_never_parses_natural_language(builder, monkeypatch):
    import nutrienv.world.portions as legacy

    def forbidden(*args, **kwargs):
        raise AssertionError("natural-language parsing must not author gold")

    monkeypatch.setattr(legacy, "resolve_portion", forbidden)
    out, _ = builder.build()
    assert len(out["items"]) == 63


def test_current_ruler_cannot_silently_lose_its_mass_scope(tmp_path):
    from nutrienv.bench.split import load_split

    payload = json.loads(EXAM_SPLIT_PATH.read_text())
    payload["items"][0]["s0"].pop("plan_scope")
    path = tmp_path / "missing-scope.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="explicit plan_scope"):
        load_split(path)
