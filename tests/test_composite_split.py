"""Composite serialization round-trips through load_exam / load_split."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.run_batch import write_composite_sample
from nutrienv.bench.realize import scored_oracles
from nutrienv.bench.split import load_split
from nutrienv.world.catalog_fixture import demo_catalog
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
    assert all(task.oracle.sub_oracles for task in result.accepted)
    catalog = result.accepted[0].s0.catalog
    loaded = load_split(dest, catalog=catalog)
    assert len(loaded) == len(result.accepted)
    for task in loaded:
        assert len(scored_oracles(task.oracle)) == 2
        assert task.s0.profile.user_id
    assert result.payload["quota_ledger"]["composite_accepted"] == len(loaded)
    assert result.payload["quota_ledger"]["base_quota"] == 240
