"""Published exam entry: 240 items bound to a live catalog SHA-256."""

from __future__ import annotations

import collections
import json
from pathlib import Path

import pytest

from nutrienv.bench.split import load_exam

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
