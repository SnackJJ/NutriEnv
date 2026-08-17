"""Parameterized generate tool: workers, model_quotas, id space, CLI."""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import pytest

from nutrienv.bench.pipeline import catalog_digest, pass_through_reviewer, run_batch
from nutrienv.bench.pipeline.expander import synthetic_expander
from nutrienv.bench.pipeline.run_batch import _table_only_judge
from nutrienv.bench.split import load_exam, load_split
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import generate_batch  # noqa: E402

CATALOG_V1 = ROOT / "data/fdc/catalog-v1.sqlite"
V10_REL = "data/fdc/catalog-v1.sqlite"


def _catalog() -> dict:
    return {
        "apple": {
            "name": "Apple, raw",
            "portions": {"piece": 182.0},
            "aliases": ["apple", "apples"],
            "allergen_tags": [],
        },
        "orange": {
            "name": "Orange, raw",
            "portions": {"piece": 131.0},
            "aliases": ["orange", "oranges"],
            "allergen_tags": [],
        },
        "milk_whole": {
            "name": "Milk, whole",
            "portions": {"cup": 244.0},
            "aliases": ["milk", "whole milk"],
            "allergen_tags": ["milk"],
        },
        "oats": {
            "name": "Oats, rolled",
            "portions": {"cup": 81.0},
            "aliases": ["oatmeal", "oats"],
            "allergen_tags": [],
        },
        "banana": {
            "name": "Banana, raw",
            "portions": {"piece": 118.0},
            "aliases": ["banana", "bananas"],
            "allergen_tags": [],
        },
        "egg": {
            "name": "Egg, whole",
            "portions": {"piece": 50.0},
            "aliases": ["eggs", "egg"],
            "allergen_tags": ["egg"],
        },
        "white_rice": {
            "name": "Rice, white",
            "portions": {"cup": 158.0},
            "aliases": ["rice"],
            "allergen_tags": [],
        },
        "broccoli": {
            "name": "Broccoli, cooked",
            "portions": {"cup": 156.0},
            "aliases": ["broccoli"],
            "allergen_tags": [],
        },
        "chicken_breast": {
            "name": "Chicken breast",
            "portions": {"piece": 172.0},
            "aliases": ["chicken"],
            "allergen_tags": [],
        },
        "tofu": {
            "name": "Tofu, firm",
            "portions": {"piece": 80.0},
            "aliases": ["tofu"],
            "allergen_tags": ["soy"],
        },
    }


def _ok_judge(_food: str, _grams: float) -> str:
    return "ok"


_PASS = {
    "items": [{"food": "milk_whole", "expression": "a cup"}],
    "query": "Please log a cup of milk for lunch.",
}


def _expander(payloads):
    def expand(_pool, *, persona, family):
        return payloads

    return expand


def _spec(tmp_path: Path, catalog, **overrides) -> dict:
    spec = {
        "seed": 7,
        "sampler_rule_version": "sampler-v1",
        "catalog_sha": catalog_digest(catalog),
        "persona": "everyday",
        "family_quotas": {"log": 4},
        "model_route": {},
        "catalog": "fixture",
        "output_path": tmp_path / "batch.json",
        "overwrite": True,
    }
    spec.update(overrides)
    return spec


class _RecordingExpander:
    def __init__(self) -> None:
        self.pool_ids: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, pool, *, persona, family):
        with self._lock:
            self.pool_ids.append(pool.pool_id)
        return synthetic_expander(pool, persona=persona, family=family)


def test_workers_must_be_at_least_one(tmp_path: Path) -> None:
    catalog = _catalog()
    with pytest.raises(ValueError, match="workers"):
        run_batch(
            _spec(tmp_path, catalog, family_quotas={"log": 1}),
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=catalog,
            workers=0,
        )


def test_parallel_matches_serial_freeze_bytes(tmp_path: Path) -> None:
    catalog = _catalog()
    serial_dir = tmp_path / "serial"
    parallel_dir = tmp_path / "parallel"
    serial_dir.mkdir()
    parallel_dir.mkdir()
    kwargs = dict(
        expander=_expander([_PASS]),
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
    )
    serial = run_batch(
        _spec(serial_dir, catalog, family_quotas={"log": 4}),
        workers=1,
        **kwargs,
    )
    parallel = run_batch(
        _spec(parallel_dir, catalog, family_quotas={"log": 4}),
        workers=4,
        **kwargs,
    )
    assert [(item.query, item.reason, item.family) for item in serial.rejected] == [
        (item.query, item.reason, item.family) for item in parallel.rejected
    ]
    assert [task.id for task in serial.accepted] == [task.id for task in parallel.accepted]
    assert serial.path is not None and parallel.path is not None
    left = serial.path.read_bytes()
    right = parallel.path.read_bytes()
    assert left == right
    assert hashlib.sha256(left).hexdigest() == hashlib.sha256(right).hexdigest()


def test_model_quotas_assign_distinct_pools(tmp_path: Path) -> None:
    catalog = _catalog()
    recorder = _RecordingExpander()
    result = run_batch(
        _spec(
            tmp_path,
            catalog,
            family_quotas={"log": 4},
            model_quotas={"deepseek-v4-flash-0731": 2, "qwen3.8-max": 2},
        ),
        expander=recorder,
        judge=_ok_judge,
        reviewer=pass_through_reviewer,
        catalog=catalog,
        workers=4,
    )
    assert {model: len(ids) for model, ids in result.model_pools.items()} == {
        "deepseek-v4-flash-0731": 2,
        "qwen3.8-max": 2,
    }
    assigned = [pool_id for ids in result.model_pools.values() for pool_id in ids]
    assert len(assigned) == len(set(assigned))
    assert set(recorder.pool_ids) == set(assigned)
    assert set(recorder.pool_ids) == {"log-0000", "log-0001", "log-0002", "log-0003"}


def test_model_quotas_must_match_family_total(tmp_path: Path) -> None:
    catalog = _catalog()
    with pytest.raises(ValueError, match="model_quotas sum"):
        run_batch(
            _spec(
                tmp_path,
                catalog,
                family_quotas={"log": 4},
                model_quotas={"deepseek-v4-flash-0731": 1, "qwen3.8-max": 1},
            ),
            expander=_expander([_PASS]),
            judge=_ok_judge,
            reviewer=pass_through_reviewer,
            catalog=catalog,
        )


def test_task_id_prefix_and_start_seq_do_not_collide(tmp_path: Path) -> None:
    assert CATALOG_V1.is_file()
    catalog = load_catalog(CATALOG_V1)
    digest = catalog_digest(catalog)

    def _one(prefix: str, start_seq: int, name: str):
        spec = {
            "seed": 20260817,
            "sampler_rule_version": "sampler-v1",
            "catalog_sha": digest,
            "persona": "everyday",
            "family_quotas": {"log": 1},
            "model_route": {},
            "catalog": V10_REL,
            "output_path": tmp_path / name,
            "overwrite": True,
            "task_id_prefix": prefix,
            "start_seq": start_seq,
        }
        return run_batch(
            spec,
            expander=synthetic_expander,
            judge=_table_only_judge,
            reviewer=pass_through_reviewer,
            catalog=catalog,
        )

    first = _one("v10a", 1, "a.json")
    second = _one("v10b", 100, "b.json")
    assert first.accepted and second.accepted
    first_ids = {task.id for task in first.accepted}
    second_ids = {task.id for task in second.accepted}
    assert first_ids.isdisjoint(second_ids)
    assert all(task_id.startswith("v10a-") for task_id in first_ids)
    assert all(task_id.startswith("v10b-") for task_id in second_ids)
    assert any(task_id.endswith("-0100") for task_id in second_ids)

    merged = dict(first.payload)
    merged["items"] = list(first.payload["items"]) + list(second.payload["items"])
    merged_path = tmp_path / "merged.json"
    merged_path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    loaded = load_split(merged_path, catalog=catalog)
    assert {task.id for task in loaded} == first_ids | second_ids
    exam = load_exam(merged_path)
    assert {task.id for task in exam} == first_ids | second_ids


def test_generate_batch_cli_synthetic_writes_loadable_payload(tmp_path: Path) -> None:
    out = tmp_path / "v1.0-batch.json"
    code = generate_batch.main(
        [
            "--synthetic",
            "--model-quota",
            "deepseek-v4-flash-0731:2",
            "--family",
            "log",
            "--output",
            str(out),
            "--force",
            "--workers",
            "2",
        ]
    )
    assert code == 0
    assert out.is_file()
    catalog = load_catalog(CATALOG_V1)
    tasks = load_split(out, catalog=catalog)
    assert tasks
    exam = load_exam(out)
    assert len(exam) == len(tasks)


def test_generate_batch_zero_accepted_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _empty(pool, *, persona, family):
        return {"items": [], "query": ""}

    monkeypatch.setattr(generate_batch, "synthetic_expander", _empty)
    out = tmp_path / "empty.json"
    code = generate_batch.main(
        [
            "--synthetic",
            "--model-quota",
            "deepseek-v4-flash-0731:2",
            "--family",
            "log",
            "--output",
            str(out),
            "--force",
        ]
    )
    assert code != 0
    assert not out.exists() or out.read_text(encoding="utf-8") == ""


def test_generate_batch_overwrite_guard(tmp_path: Path) -> None:
    out = tmp_path / "existing.json"
    out.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        generate_batch.main(
            [
                "--synthetic",
                "--model-quota",
                "deepseek-v4-flash-0731:1",
                "--family",
                "log",
                "--output",
                str(out),
            ]
        )
    assert out.read_text(encoding="utf-8") == "{}\n"
