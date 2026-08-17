"""Pilot-20 pool plan, drop helper, and published v1.0 exam shape."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam
from nutrienv.bench.validator import validate_draft, validate_oracle_grams
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import landing_verify  # noqa: E402
import run_pilot_20  # noqa: E402

CATALOG_V1 = ROOT / "data/fdc/catalog-v1.sqlite"
V10 = ROOT / "data/splits/v1.0-gold.json"


@pytest.fixture(scope="module")
def catalog_v1():
    if not CATALOG_V1.is_file():
        pytest.fail("data/fdc/catalog-v1.sqlite is missing")
    return load_catalog(CATALOG_V1)


def test_pool_plan_is_deterministic_and_covers_keys(catalog_v1) -> None:
    first = run_pilot_20.build_pool_plan()
    second = run_pilot_20.build_pool_plan()
    assert first == second
    assert len(first) == 20
    kinds = [(slot.family, slot.kind) for slot in first]
    assert kinds.count(("log", "single")) == 8
    assert kinds.count(("log", "meal")) == 6
    assert kinds.count(("evaluate", "meal")) == 6
    assert {slot.persona for slot in first} == {"everyday", "gym"}
    assert run_pilot_20.plan_covers_required_keys(first)
    for slot in first:
        for food_id in slot.food_ids:
            assert food_id in catalog_v1 or catalog_v1.canonical_id(food_id)
        pool = run_pilot_20.build_pool(catalog_v1, slot)
        if slot.kind == "single":
            assert len(pool.foods) == 1
        else:
            assert 2 <= len(pool.foods) <= 8
        if slot.target_key:
            food = pool.foods[0]
            keys = {alt.key for alt in food.alternatives}
            assert slot.target_key in keys, (slot.slot_id, slot.target_key, keys)
        if slot.evaluate_seed:
            row = run_pilot_20.evaluate_row_by_seed(slot.evaluate_seed)
            assert row.items


def test_drop_ids_removes_only_named_items() -> None:
    items = [{"id": "v10-log-0001"}, {"id": "v10-eval-0009"}, {"id": "v10-log-0015"}]
    kept = run_pilot_20.drop_ids(items, ["v10-eval-0009", " missing "])
    assert [row["id"] for row in kept] == ["v10-log-0001", "v10-log-0015"]


def test_apply_drop_updates_state_payload() -> None:
    state = {
        "payload": {
            "version": "v1.0-gold",
            "catalog": "data/fdc/catalog-v1.sqlite",
            "catalog_sha256": "abc",
            "items": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "notes": "pilot",
        },
        "meta": [
            {"task_id": "a"},
            {"task_id": "b"},
            {"task_id": "c"},
        ],
        "review": {
            "anomalies": [{"id": "b", "reasons": ["low_consistency"]}],
            "per_candidate": {"a": {}, "b": {}, "c": {}},
        },
    }
    updated = run_pilot_20.apply_drop(state, ["b"])
    assert [row["id"] for row in updated["payload"]["items"]] == ["a", "c"]
    assert updated["n_accepted"] == 2
    assert updated["dropped"] == ["b"]
    assert updated["review"]["anomalies"] == []
    assert set(updated["review"]["per_candidate"]) == {"a", "c"}


def test_exam_split_path_default_is_v10() -> None:
    assert EXAM_SPLIT_PATH.name == "v1.0-gold.json"
    assert EXAM_SPLIT_PATH.is_file()


def test_v10_gold_loads_and_passes_gates() -> None:
    tasks = load_exam(V10)
    assert len(tasks) == 20
    assert {task.family for task in tasks} <= {"log", "evaluate"}
    payload = json.loads(V10.read_text(encoding="utf-8"))
    assert payload["version"] == "v1.0-gold"
    assert payload["catalog"] == "data/fdc/catalog-v1.sqlite"
    digest = run_pilot_20.catalog_digest(load_catalog(CATALOG_V1))
    assert payload["catalog_sha256"] == digest
    for task in tasks:
        assert validate_draft(task) == [], (task.id, validate_draft(task))
        assert validate_oracle_grams(task) == [], (task.id, validate_oracle_grams(task))
    coverage = run_pilot_20.coverage_counts(tasks)
    for key in run_pilot_20.REQUIRED_KEYS:
        assert coverage[key] >= 1, coverage


def test_landing_verify_v10_helper() -> None:
    n, draft_bad, grams_bad = landing_verify.verify_v10_exam(V10)
    assert n == 20
    assert draft_bad == []
    assert grams_bad == []
