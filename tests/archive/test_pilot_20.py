"""Pilot-20 pool plan, drop helper, and published exam entry."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam
from nutrienv.bench.validator import validate_draft
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import landing_verify  # noqa: E402
import run_pilot_20  # noqa: E402

CATALOG_V1 = ROOT / "data/fdc/catalog-v1.sqlite"
V05 = ROOT / "data/splits/v0.5-gold.json"


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


def test_awkward_query_rejects_piece_of_eggs() -> None:
    assert run_pilot_20.awkward_query("Please log a piece of eggs for lunch.")
    assert not run_pilot_20.awkward_query("Please log two eggs for lunch.")
    assert not run_pilot_20.awkward_query("Log an egg after the gym.")


def test_review_admissible_allows_single_unparseable_555() -> None:
    clean = {"anomalies": [], "per_candidate": {"t": {"models": {}}}}
    assert run_pilot_20.review_admissible(clean, "t") == (True, "clean")
    glitch = {
        "anomalies": [{"id": "t", "reasons": ["unparseable"]}],
        "per_candidate": {
            "t": {
                "models": {
                    "a": {
                        "consistency": None,
                        "naturalness": None,
                        "entailment": None,
                        "unparseable": True,
                    },
                    "b": {
                        "consistency": 5,
                        "naturalness": 5,
                        "entailment": 5,
                    },
                }
            }
        },
    }
    ok, note = run_pilot_20.review_admissible(glitch, "t")
    assert ok is True
    assert "unparseable" in note
    bad = {
        "anomalies": [{"id": "t", "reasons": ["disagreement"]}],
        "per_candidate": {"t": {"models": {}}},
    }
    assert run_pilot_20.review_admissible(bad, "t")[0] is False


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


def test_refreeze_from_state_accepts_pipeline_draft_after_drop(
    tmp_path: Path, catalog_v1
) -> None:
    from nutrienv.bench.pipeline.types import PIPELINE_VERSION, catalog_digest
    from nutrienv.bench.split import load_split

    source = json.loads(V05.read_text(encoding="utf-8"))
    keep_ids = {"v0-log-fuzzy-001", "v0-log-unit-001"}
    items = [item for item in source["items"] if item["id"] in keep_ids]
    assert len(items) == 2
    state = {
        "payload": {
            "version": PIPELINE_VERSION,
            "catalog": "data/fdc/catalog-v1.sqlite",
            "catalog_sha256": catalog_digest(catalog_v1),
            "items": items,
            "notes": "draft",
        },
        "meta": [{"task_id": item["id"]} for item in items],
        "review": {
            "anomalies": [],
            "per_candidate": {item["id"]: {} for item in items},
        },
    }
    state = run_pilot_20.apply_drop(state, ["v0-log-unit-001"])
    out = tmp_path / "draft.json"
    updated = run_pilot_20.refreeze_from_state(
        state, catalog=catalog_v1, output_path=out
    )
    assert out.is_file()
    loaded = load_split(out, catalog=catalog_v1)
    assert [task.id for task in loaded] == ["v0-log-fuzzy-001"]
    assert updated["payload"]["version"] == PIPELINE_VERSION


def test_exam_split_path_default_is_v05() -> None:
    assert EXAM_SPLIT_PATH.name == "v0.5-gold.json"
    assert EXAM_SPLIT_PATH.is_file()
    assert EXAM_SPLIT_PATH.resolve() == V05.resolve()


def test_v05_gold_loads_via_load_exam() -> None:
    tasks = load_exam(V05)
    assert len(tasks) == 240
    payload = json.loads(V05.read_text(encoding="utf-8"))
    assert payload["version"] == "v0.5-gold"
    assert payload["catalog"] == "data/fdc/catalog.sqlite"
    for task in tasks:
        issues = validate_draft(task)
        assert issues == [], (task.id, issues)


def test_landing_verify_published_exam_helper() -> None:
    n, draft_bad, grams_bad, tasks = landing_verify.verify_published_exam(V05)
    assert n == 240
    assert draft_bad == []
    assert {row[0] for row in grams_bad} == landing_verify.V05_ORACLE_GRAMS_EXEMPT_IDS
    assert landing_verify.unexpected_oracle_grams_failures(grams_bad) == []
    assert landing_verify.oracle_grams_gate_failures(grams_bad, tasks) == []


def test_mutating_exempt_item_grams_fails_oracle_grams_gate(tmp_path: Path) -> None:
    payload = json.loads(V05.read_text(encoding="utf-8"))
    item = next(row for row in payload["items"] if row["id"] == "v0-log-eaten-001")
    assert item["oracle"]["ledger_tail"][0]["grams"] == 150.0
    item["oracle"]["ledger_tail"][0]["grams"] = 999.0
    dest = tmp_path / "mutated-v05.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    n, draft_bad, grams_bad, tasks = landing_verify.verify_published_exam(dest)
    assert n == 240
    assert draft_bad == []
    gate_bad = landing_verify.oracle_grams_gate_failures(grams_bad, tasks)
    assert any(row[0] == "v0-log-eaten-001" for row in gate_bad)


def test_render_report_does_not_claim_v10_is_the_published_exam() -> None:
    text = run_pilot_20.render_report({"freeze_sha256": "abc123"})
    assert "EXAM_SPLIT_PATH` now points at `data/splits/v1.0-gold.json`" not in text
    assert "Freeze sha256 of `data/splits/v1.0-gold.json`" not in text
    assert "data/splits/v0.5-gold.json" in text
    assert "archive" in text.lower()
    assert "`abc123`" in text
    collapsed = " ".join(text.split())
    assert "rewrites the published exam" not in collapsed
    assert "rewrite the published exam" not in collapsed.lower()


def test_pilot_ops_do_not_claim_to_rewrite_the_published_exam() -> None:
    collapsed = " ".join((run_pilot_20.__doc__ or "").split())
    assert "rewrites the published exam" not in collapsed
    assert "rewrite the published exam" not in collapsed.lower()
    with pytest.raises(SystemExit) as excinfo:
        run_pilot_20.main(["--rerun-fallbacks"])
    assert "published exam" not in str(excinfo.value).lower()


def test_unexpected_oracle_grams_failures_flags_new_ids() -> None:
    known = [("v0-log-multi-001", ["legacy"])]
    extra = [("brand-new-item", ["grams"])]
    assert landing_verify.unexpected_oracle_grams_failures(known) == []
    assert landing_verify.unexpected_oracle_grams_failures(known + extra) == extra
