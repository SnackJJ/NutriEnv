"""Public seams for ticket 13: catalog JSON cells have pinned key order.

Seams (no archived-catalog rewrite, no catalog-v2 rewrite):

- ``build(...)`` writes ``foods`` JSON cells with sorted keys
- two builds from the same raw zip yield identical ``foods`` rows
- ``plan_fndds_only_rebuild`` reports sqlite foods JSON cell byte diffs
- archived v0.x still ``load_split``s; ``load_exam`` stays fail-closed
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from nutrienv.bench.split import EXAM_SPLIT_PATH, load_exam, load_split

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_fdc_catalog as builder  # noqa: E402

_LIVE = ROOT / "data" / "fdc" / "archive" / "catalog.sqlite"
_V1 = ROOT / "data" / "fdc" / "archive" / "catalog-v1.sqlite"
_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"
_SPLIT = ROOT / "data" / "splits" / "archive" / "v0.5-gold.json"
# v0.5-gold pins this sha of data/fdc/archive/catalog.sqlite.
_LIVE_SHA256 = "ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90"
_V1_SHA256 = "f49e4f904905abbb8b4ebb02c908935f01776280a2c00b3de1a3e890cad5ae91"


def _csv(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _write_survey_zip(dest: Path) -> Path:
    """One food whose scan order is *not* JSON key order.

    Nutrient CSV order is sodium → kcal → protein. Portion seq_num order
    is fl_oz → cup → qns, the ticket 13 rebuild example.
    """
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(
            "food.csv",
            _csv(
                ["fdc_id", "description", "data_type", "food_category_id"],
                [
                    {
                        "fdc_id": "1",
                        "description": "Synthetic beverage",
                        "data_type": "survey_fndds_food",
                        "food_category_id": "9",
                    }
                ],
            ),
        )
        zf.writestr(
            "food_nutrient.csv",
            _csv(
                ["fdc_id", "nutrient_id", "amount"],
                [
                    {"fdc_id": "1", "nutrient_id": "1093", "amount": "5"},
                    {"fdc_id": "1", "nutrient_id": "1008", "amount": "10"},
                    {"fdc_id": "1", "nutrient_id": "1003", "amount": "1"},
                ],
            ),
        )
        zf.writestr(
            "food_portion.csv",
            _csv(
                [
                    "fdc_id",
                    "id",
                    "seq_num",
                    "portion_description",
                    "modifier",
                    "gram_weight",
                ],
                [
                    {
                        "fdc_id": "1",
                        "id": "10",
                        "seq_num": "1",
                        "portion_description": "1 fl oz",
                        "modifier": "",
                        "gram_weight": "31",
                    },
                    {
                        "fdc_id": "1",
                        "id": "20",
                        "seq_num": "2",
                        "portion_description": "1 cup",
                        "modifier": "",
                        "gram_weight": "248",
                    },
                    {
                        "fdc_id": "1",
                        "id": "30",
                        "seq_num": "3",
                        "portion_description": "Quantity not specified",
                        "modifier": "90000",
                        "gram_weight": "248",
                    },
                ],
            ),
        )
    return dest


def _point_raw_at(tmp_path: Path, survey: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "survey.zip").write_bytes(survey.read_bytes())
    monkeypatch.setattr(builder, "_RAW", raw)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_catalog_shas() -> dict[Path, str]:
    return {path: _sha256(path) for path in (_LIVE, _V1, _V2) if path.is_file()}


def _foods_rows(path: Path) -> list[tuple]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return list(
            conn.execute(
                "SELECT food_id, name, data_type, category, nutrients, "
                "portions, allergen_tags, aliases FROM foods"
            )
        )
    finally:
        conn.close()


def test_foods_json_cells_pin_key_order_not_scan_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    survey = _write_survey_zip(tmp_path / "survey.zip")
    _point_raw_at(tmp_path, survey, monkeypatch)
    dest = tmp_path / "catalog.sqlite"
    builder.build(include_branded=False, dest=dest, fndds_only=True)
    rows = _foods_rows(dest)
    assert len(rows) == 1
    food_id, name, data_type, category, nutrients, portions, tags, aliases = rows[0]
    assert food_id == "1"
    assert name == "Synthetic beverage"
    assert data_type == "survey_fndds_food"
    assert category == "9"
    assert nutrients == '{"kcal": 10.0, "protein_g": 1.0, "sodium_mg": 5.0}'
    assert portions == '{"cup": 248.0, "fl_oz": 31.0, "qns": 248.0}'
    assert tags == "[]"
    assert aliases == "[]"


def test_two_builds_from_the_same_zip_write_identical_foods_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _snapshot_catalog_shas()
    survey = _write_survey_zip(tmp_path / "survey.zip")
    _point_raw_at(tmp_path, survey, monkeypatch)
    first = tmp_path / "a.sqlite"
    second = tmp_path / "b.sqlite"
    builder.build(include_branded=False, dest=first, fndds_only=True)
    builder.build(include_branded=False, dest=second, fndds_only=True)
    assert _foods_rows(first) == _foods_rows(second)
    assert first.read_bytes() == second.read_bytes()
    for path, digest in before.items():
        assert _sha256(path) == digest


def _write_foods_sqlite(path: Path, cells: dict[str, str]) -> Path:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE foods ("
            "food_id TEXT PRIMARY KEY, name TEXT, data_type TEXT, category TEXT, "
            "nutrients TEXT, portions TEXT, allergen_tags TEXT, aliases TEXT)"
        )
        conn.execute(
            "INSERT INTO foods VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1",
                "Synthetic beverage",
                "survey_fndds_food",
                "9",
                cells["nutrients"],
                cells["portions"],
                cells["allergen_tags"],
                cells["aliases"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return path


# Ticket 13 example plus the other three foods JSON cells. Parsed values
# match; TEXT bytes do not (key order / JSON spacing).
_CANON_CELLS = {
    "nutrients": '{"kcal": 10.0, "protein_g": 1.0, "sodium_mg": 5.0}',
    "portions": '{"cup": 248.0, "fl_oz": 31.0, "qns": 248.0}',
    "allergen_tags": '["peanut", "shellfish"]',
    "aliases": '["milk", "whole milk"]',
}
_DRIFT_CELLS = {
    "nutrients": '{"sodium_mg": 5.0, "kcal": 10.0, "protein_g": 1.0}',
    "portions": '{"fl_oz": 31.0, "cup": 248.0, "qns": 248.0}',
    "allergen_tags": '["peanut","shellfish"]',
    "aliases": '["milk","whole milk"]',
}


def test_foods_json_cell_byte_check_detects_key_order_drift(tmp_path: Path) -> None:
    left = _write_foods_sqlite(tmp_path / "left.sqlite", _CANON_CELLS)
    right = _write_foods_sqlite(tmp_path / "right.sqlite", _DRIFT_CELLS)
    result = builder.diff_foods_json_cells(left, right)
    assert result["foods_compared"] == 1
    assert result["value_diffs"] == 0
    assert result["byte_diffs"] == 1
    assert result["key_order_only_diffs"] == 1
    assert result["byte_diff_columns"] == [
        "aliases",
        "allergen_tags",
        "nutrients",
        "portions",
    ]


def test_foods_json_cell_byte_check_is_zero_when_text_matches(tmp_path: Path) -> None:
    left = _write_foods_sqlite(tmp_path / "left.sqlite", _CANON_CELLS)
    right = _write_foods_sqlite(tmp_path / "right.sqlite", _CANON_CELLS)
    result = builder.diff_foods_json_cells(left, right)
    assert result["foods_compared"] == 1
    assert result["value_diffs"] == 0
    assert result["byte_diffs"] == 0
    assert result["key_order_only_diffs"] == 0
    assert result["byte_diff_columns"] == []


def test_plan_byte_check_build_uses_explicit_survey_zip(tmp_path: Path) -> None:
    before = _snapshot_catalog_shas()
    survey = _write_survey_zip(tmp_path / "survey.zip")
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE,
        survey_zip=survey,
    )
    cells = plan["raw_scan"]["json_cells"]
    assert cells["foods_compared"] == 1
    assert cells["key_order_only_diffs"] == 0
    for path, digest in before.items():
        assert _sha256(path) == digest


def test_plan_default_byte_check_flags_unsorted_dumps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Old json.dumps (no sort_keys) must not report zero sqlite-cell drift.

    Two consecutive same-code rebuilds keep insertion order, so they are not
    this check. The dry-run builds the explicit survey_zip and compares
    stored TEXT to independently sorted JSON.
    """
    before = _snapshot_catalog_shas()
    survey = _write_survey_zip(tmp_path / "survey.zip")
    monkeypatch.setattr(builder, "dump_catalog_json", lambda value: json.dumps(value))
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE,
        survey_zip=survey,
    )
    cells = plan["raw_scan"]["json_cells"]
    assert cells["foods_compared"] == 1
    assert cells["value_diffs"] == 0
    assert cells["key_order_only_diffs"] == 1
    assert "nutrients" in cells["byte_diff_columns"]
    assert "portions" in cells["byte_diff_columns"]
    for path, digest in before.items():
        assert _sha256(path) == digest


def test_plan_byte_check_detects_sqlite_key_order_drift(
    tmp_path: Path,
) -> None:
    before = _snapshot_catalog_shas()
    left = _write_foods_sqlite(tmp_path / "left.sqlite", _CANON_CELLS)
    right = _write_foods_sqlite(tmp_path / "right.sqlite", _DRIFT_CELLS)
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE,
        split_path=_SPLIT,
        sqlite_pair=(left, right),
    )
    cells = plan["raw_scan"]["json_cells"]
    assert plan["raw_scan"]["portion_map_diffs"] == 0
    assert cells["value_diffs"] == 0
    assert cells["key_order_only_diffs"] == 1
    assert cells["byte_diff_columns"] == [
        "aliases",
        "allergen_tags",
        "nutrients",
        "portions",
    ]
    dest = tmp_path / "catalog-v2-dryrun.md"
    builder.write_catalog_v2_dryrun(plan, dest)
    text = dest.read_text(encoding="utf-8")
    assert "sqlite" in text.lower()
    assert "key_order_only" in text or "仅序列化" in text
    for column in ("nutrients", "portions", "allergen_tags", "aliases"):
        assert f"`{column}`" in text
    assert str(cells["key_order_only_diffs"]) in text
    for path, digest in before.items():
        assert _sha256(path) == digest


def test_archived_v0x_stays_pinned_and_load_exam_is_fail_closed() -> None:
    payload = json.loads(_SPLIT.read_text(encoding="utf-8"))
    assert payload["catalog"] == "data/fdc/archive/catalog.sqlite"
    assert payload["catalog_sha256"] == _LIVE_SHA256
    assert _sha256(_LIVE) == _LIVE_SHA256
    assert _sha256(_V1) == _V1_SHA256
    tasks = load_split(_SPLIT)
    assert len(tasks) == 240
    with pytest.raises(ValueError, match="version"):
        load_exam(_SPLIT)
    assert EXAM_SPLIT_PATH.is_file()
    assert len(load_exam()) == 63
