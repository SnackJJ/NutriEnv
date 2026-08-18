"""Overwrite guard on freeze_tasks and published-split content hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nutrienv.bench.pipeline.freezer import freeze_tasks
from nutrienv.bench.split import load_exam
from nutrienv.world.catalog_store import load_catalog

ROOT = Path(__file__).resolve().parents[1]
V05 = ROOT / "data/splits/v0.5-gold.json"
CATALOG = ROOT / "data/fdc/catalog.sqlite"

V05_SHA256 = "bb4f246044308670f567c24bc6b099e23f617268b532a088c27187dbda66e520"


def _catalog():
    return load_catalog(CATALOG)


def _one_task():
    return [load_exam(V05)[0]]


def test_freeze_refuses_different_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "split.json"
    target.write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        freeze_tasks(
            _one_task(),
            catalog=_catalog(),
            output_path=target,
            overwrite=False,
        )
    assert target.read_text(encoding="utf-8") == "{}\n"


def test_freeze_overwrite_true_replaces(tmp_path: Path) -> None:
    target = tmp_path / "split.json"
    target.write_text("{}\n", encoding="utf-8")
    payload, path = freeze_tasks(
        _one_task(),
        catalog=_catalog(),
        output_path=target,
        overwrite=True,
    )
    assert path == target
    assert target.read_text(encoding="utf-8") != "{}\n"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "v0-log-fuzzy-001"


def test_v05_gold_sha256_is_pinned() -> None:
    digest = hashlib.sha256(V05.read_bytes()).hexdigest()
    assert digest == V05_SHA256
