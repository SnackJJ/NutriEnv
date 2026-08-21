"""Public seams for ticket 13: catalog JSON cells have pinned key order.

Seams (no archived-catalog rewrite, no catalog-v2 rewrite):

- ``build(...)`` writes ``foods`` JSON cells with sorted keys
- two builds from the same raw zip yield identical ``foods`` rows
- ``plan_fndds_only_rebuild`` reports a byte-level portions check
- archived v0.x still ``load_split``s; ``load_exam`` stays fail-closed
"""

from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_fdc_catalog as builder  # noqa: E402

_LIVE = ROOT / "data" / "fdc" / "archive" / "catalog.sqlite"
_V1 = ROOT / "data" / "fdc" / "archive" / "catalog-v1.sqlite"
_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"
_SPLIT = ROOT / "data" / "splits" / "archive" / "v0.5-gold.json"
# v0.5-gold pins this sha of data/fdc/archive/catalog.sqlite.
_LIVE_SHA256 = "ff2f26325cc0cc71c3230f82060997afaeefcad0051b09989c662ac0b0fa2d90"


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
