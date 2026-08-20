"""Composite serialization round-trips through load_exam / load_split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.freezer import task_to_item
from nutrienv.bench.pipeline.run_batch import write_composite_sample
from nutrienv.bench.realize import Oracle, Task, compose_oracles, scored_oracles
from nutrienv.bench.split import load_exam, load_split
from nutrienv.world.catalog_fixture import demo_catalog, demo_state
from nutrienv.world.types import LedgerRow

V05 = Path("data/splits/v0.5-gold.json")


def test_old_payloads_without_sub_oracles_still_load():
    tasks = load_split(V05)
    assert len(tasks) == 240
    assert all(task.oracle.sub_oracles is None for task in tasks)


def test_load_exam_rejects_short_sub_oracles(tmp_path: Path):
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["items"][0]["oracle"]["sub_oracles"] = [{"profile": "s0"}]
    dest = tmp_path / "short.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="sub_oracles"):
        load_split(dest)


def test_load_exam_round_trip_composite_json(tmp_path: Path):
    catalog = demo_catalog()
    payload = {
        "version": "v1.0-composite-sample",
        "catalog": "data/fdc/catalog-v1.sqlite",
        "catalog_sha256": "0" * 64,
        "items": [
            {
                "id": "v10-composite-0001",
                "family": "log",
                "persona": "everyday",
                "situations": ["multi_item_log"],
                "query": "Please log a cup of milk for lunch, then recommend dinner.",
                "s0": {
                    "profile": {
                        "user_id": "v10-composite-0001",
                        "allergies": ["peanut"],
                        "windows": {"kcal": [1800.0, 2200.0], "protein_g": [90.0, 140.0]},
                    },
                    "ledger": [
                        {"food_id": "banana", "grams": 118.0, "eaten_at": "yesterday-snack"}
                    ],
                },
                "oracle": {
                    "profile": "s0",
                    "sub_oracles": [
                        {
                            "profile": "s0",
                            "ledger_tail": [
                                {
                                    "food_id": "milk_whole",
                                    "grams": 244.0,
                                    "eaten_at": "today-lunch",
                                }
                            ],
                            "ledger": "s0_plus_tail",
                        },
                        {
                            "profile": "s0",
                            "last_plan": [],
                            "plan_must_be_safe": True,
                            "plan_must_fit_windows": True,
                            "plan_windows": {
                                "kcal": [1651.16, 2051.16],
                                "protein_g": [81.09, 131.09],
                            },
                            "ledger_tail": [
                                {
                                    "food_id": "milk_whole",
                                    "grams": 244.0,
                                    "eaten_at": "today-lunch",
                                }
                            ],
                            "ledger": "s0_plus_tail",
                        },
                    ],
                },
            }
        ],
    }
    dest = tmp_path / "composite.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    tasks = load_split(dest, catalog=catalog)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.family == "log"
    assert task.oracle.sub_oracles is not None
    assert len(task.oracle.sub_oracles) == 2
    log_oracle, rec_oracle = task.oracle.sub_oracles
    assert log_oracle.ledger_tail == [LedgerRow("milk_whole", 244.0, "today-lunch")]
    assert rec_oracle.last_plan == []
    assert rec_oracle.plan_must_be_safe
    assert rec_oracle.plan_windows is not None
    assert rec_oracle.ledger == (*task.s0.ledger, *log_oracle.ledger_tail)


def test_write_composite_sample_round_trips(tmp_path: Path):
    dest = tmp_path / "composite-sample.json"
    result = write_composite_sample(output_path=dest, n=2)
    assert result.path == dest
    assert result.accepted
    assert result.payload["version"] == "pipeline-composite-draft"
    assert all(task.oracle.sub_oracles for task in result.accepted)
    catalog = result.accepted[0].s0.catalog
    with pytest.raises(ValueError, match="version"):
        load_exam(dest)
    loaded = load_split(dest, catalog=catalog)
    assert len(loaded) == len(result.accepted)
    for task in loaded:
        assert len(scored_oracles(task.oracle)) == 2
        assert task.s0.profile.user_id
    assert result.payload["quota_ledger"]["composite_accepted"] == len(loaded)
    assert result.payload["quota_ledger"]["base_quota"] == 240


def test_omitted_last_verdict_loads_as_none(tmp_path: Path):
    for task in load_split(V05):
        assert task.oracle.last_verdict is None
        assert task.oracle.last_reasons == ()

    state = demo_state()
    task = Task(
        "draft-eval-1",
        "evaluate",
        "Is 100 g of rice okay for lunch?",
        state,
        Oracle(
            profile=state.profile,
            last_plan=[{"food_id": "white_rice", "grams": 100.0}],
            ledger=tuple(state.ledger),
        ),
    )
    item = task_to_item(task)
    assert "last_verdict" not in item["oracle"]
    dest = tmp_path / "split.json"
    dest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    loaded = load_split(dest, catalog=state.catalog)
    assert loaded[0].oracle.last_verdict is None
    assert loaded[0].oracle.last_reasons == ()


def test_empty_reject_child_freezes_and_loads_as_evaluate(tmp_path: Path):
    state = demo_state()
    lunch = LedgerRow("oats", 60.0, "today-lunch")
    log_oracle = Oracle(
        profile=state.profile,
        ledger_tail=[lunch],
        ledger=(*state.ledger, lunch),
    )
    reject_oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("kcal_hi",),
        ledger=tuple(state.ledger),
    )
    task = Task(
        "draft-comp-1",
        "log",
        "I ate oats; is leftover pizza okay tonight?",
        state,
        compose_oracles(log_oracle, reject_oracle),
    )
    item = task_to_item(task)
    child = item["oracle"]["sub_oracles"][1]
    assert child["last_verdict"] == "reject"
    assert child["last_plan"] == []
    assert child["last_reasons"] == ["kcal_hi"]
    assert "plan_must_fit_windows" not in child
    assert "allow_empty_plan" not in child

    dest = tmp_path / "split.json"
    dest.write_text(json.dumps({"items": [item]}), encoding="utf-8")
    loaded = load_split(dest, catalog=state.catalog)
    reject = loaded[0].oracle.sub_oracles[1]
    assert reject.last_verdict == "reject"
    assert reject.last_plan == []
    assert reject.last_reasons == ("kcal_hi",)
    assert reject.plan_must_fit_windows is False
    assert reject.allow_empty_plan is False


def test_reject_freeze_drops_prohibited_plan_flags(tmp_path: Path):
    state = demo_state()
    oracle = Oracle(
        profile=state.profile,
        last_plan=[],
        last_verdict="reject",
        last_reasons=("allergy",),
        plan_must_fit_windows=True,
        allow_empty_plan=True,
        plan_must_be_safe=True,
        ledger=tuple(state.ledger),
    )
    task = Task(
        "draft-eval-reject",
        "evaluate",
        "Is leftover pizza okay tonight?",
        state,
        oracle,
    )
    payload = task_to_item(task)["oracle"]
    assert payload["last_verdict"] == "reject"
    assert payload["last_plan"] == []
    assert "plan_must_fit_windows" not in payload
    assert "allow_empty_plan" not in payload

    dest = tmp_path / "split.json"
    dest.write_text(json.dumps({"items": [task_to_item(task)]}), encoding="utf-8")
    loaded = load_split(dest, catalog=state.catalog)[0].oracle
    assert loaded.last_verdict == "reject"
    assert loaded.plan_must_fit_windows is False
    assert loaded.allow_empty_plan is False
