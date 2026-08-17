"""Published exam entry: 240 items bound to a live catalog SHA-256."""

from __future__ import annotations

import collections
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from nutrienv.bench import split as split_mod
from nutrienv.bench.split import load_exam

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_react  # noqa: E402

V05 = Path("data/splits/v0.5-gold.json")

ALLOCATION = {
    "log": 48,
    "recommend": 72,
    "evaluate": 48,
    "update": 36,
    "constrain": 36,
}


def test_default_exam_is_240_with_allocation() -> None:
    tasks = load_exam()
    assert len(tasks) == 240
    assert len({task.id for task in tasks}) == 240
    assert collections.Counter(task.family for task in tasks) == ALLOCATION


def test_exam_missing_catalog_raises(tmp_path: Path) -> None:
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["catalog"] = str(tmp_path / "missing.sqlite")
    dest = tmp_path / "exam.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="exam catalog not found"):
        load_exam(dest)


def test_exam_sha_mismatch_raises(tmp_path: Path) -> None:
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["catalog_sha256"] = "0" * 64
    dest = tmp_path / "exam.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="catalog sha256 mismatch"):
        load_exam(dest)


def test_exam_wrong_version_raises(tmp_path: Path) -> None:
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["version"] = "v0.4-gold"
    dest = tmp_path / "exam.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        load_exam(dest)


def _bad_sha_exam(tmp_path: Path) -> Path:
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["catalog_sha256"] = "0" * 64
    dest = tmp_path / "exam.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")
    return dest


def _write_tiny_catalog(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE foods ("
            "food_id TEXT PRIMARY KEY, name TEXT NOT NULL, data_type TEXT, "
            "category TEXT, nutrients TEXT, portions TEXT, allergen_tags TEXT, "
            "aliases TEXT)"
        )
        conn.execute(
            "CREATE TABLE aliases (alias TEXT PRIMARY KEY, food_id TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE food_fts USING fts5("
            "food_id, name, aliases, tokenize='unicode61')"
        )
        conn.execute(
            "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "probe_only_food",
                "probe only zucchini",
                "survey_fndds_food",
                "veg",
                json.dumps({"kcal": 17.0}),
                json.dumps({"piece": 100.0}),
                json.dumps([]),
                json.dumps(["probe zucchini"]),
            ),
        )
        conn.execute(
            "INSERT INTO aliases(alias, food_id) VALUES (?, ?)",
            ("probe zucchini", "probe_only_food"),
        )
        conn.execute(
            "INSERT INTO food_fts(food_id, name, aliases) VALUES (?, ?, ?)",
            ("probe_only_food", "probe only zucchini", "probe zucchini"),
        )
        conn.commit()
    finally:
        conn.close()


def test_load_exam_attaches_the_validated_catalog(tmp_path: Path) -> None:
    catalog_path = tmp_path / "tiny.sqlite"
    _write_tiny_catalog(catalog_path)
    digest = hashlib.sha256(catalog_path.read_bytes()).hexdigest()
    payload = json.loads(V05.read_text(encoding="utf-8"))
    payload["catalog"] = str(catalog_path)
    payload["catalog_sha256"] = digest
    dest = tmp_path / "exam.json"
    dest.write_text(json.dumps(payload), encoding="utf-8")

    tasks = load_exam(dest)
    catalog = tasks[0].s0.catalog
    assert "probe_only_food" in catalog
    assert "milk_whole" not in catalog
    hits = catalog.search("probe zucchini")
    assert any(row["food_id"] == "probe_only_food" for row in hits)
    milk_hits = catalog.search("milk whole")
    assert not any(row["food_id"] == "milk_whole" for row in milk_hits)


def test_load_react_tasks_default_is_load_exam() -> None:
    tasks = run_react.load_react_tasks()
    assert len(tasks) == 240


def test_run_react_default_path_fails_closed_before_harness(
    tmp_path: Path, monkeypatch
) -> None:
    dest = _bad_sha_exam(tmp_path)
    monkeypatch.setattr(split_mod, "EXAM_SPLIT_PATH", dest)
    created: list[bool] = []

    def boom(*_args, **_kwargs):
        created.append(True)
        raise AssertionError("harness must not be created")

    monkeypatch.setattr(run_react, "ReActHarness", boom)
    with pytest.raises(ValueError, match="catalog sha256 mismatch"):
        run_react.main([])
    assert created == []


def test_run_react_limit_path_fails_closed_before_harness(
    tmp_path: Path, monkeypatch
) -> None:
    dest = _bad_sha_exam(tmp_path)
    monkeypatch.setattr(split_mod, "EXAM_SPLIT_PATH", dest)
    created: list[bool] = []

    def boom(*_args, **_kwargs):
        created.append(True)
        raise AssertionError("harness must not be created")

    monkeypatch.setattr(run_react, "ReActHarness", boom)
    with pytest.raises(ValueError, match="catalog sha256 mismatch"):
        run_react.main(["--limit", "1"])
    assert created == []


def test_explicit_split_uses_lenient_loader(tmp_path: Path) -> None:
    dest = _bad_sha_exam(tmp_path)
    tasks = run_react.load_react_tasks(dest)
    assert len(tasks) == 240


def test_run_react_split_default_is_none() -> None:
    args = run_react.build_parser().parse_args([])
    assert args.split is None
