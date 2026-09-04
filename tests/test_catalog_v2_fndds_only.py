"""Public seams for ticket 06 STEP 1: FNDDS-only builder mode + dry-run.

Seams (no catalog-v2.sqlite write, no default-pin change):

- ``ingest_sources(fndds_only=...)`` — which zips the builder will read
- ``staple_fdc_pins(fndds_only=...)`` — pinned staple FDC ids
- ``assign_staples(foods, fndds_only=...)`` — slug → food_id
- ``build(..., fndds_only=True)`` — refuses frozen catalog paths
- ``plan_fndds_only_rebuild`` — staple swaps + gram deltas, read-only
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_fdc_catalog as builder  # noqa: E402

_SR_STAPLES = (
    "chicken_breast",
    "tuna",
    "tofu",
    "salmon",
    "shrimp",
    "beef",
    "olive_oil",
    "black_beans",
    "peanut",
    "almond",
)
# Ticket-named + form-matched FNDDS targets (PortionFacts confirmed from
# catalog-v1 full-strategy rows, which are FNDDS food_portion first-wins).
_FNDDS_TARGETS = {
    "chicken_breast": "2705956",
    "tuna": "2706311",
    "tofu": "2707435",
    "salmon": "2706286",
    "shrimp": "2706363",
    "beef": "2705855",
    "olive_oil": "2710186",
    "black_beans": "2707361",
    "peanut": "2707514",
    "almond": "2707486",
}
_LIVE = ROOT / "data" / "fdc" / "archive" / "catalog.sqlite"
_V1 = ROOT / "data" / "fdc" / "archive" / "catalog-v1.sqlite"
_SPLIT = ROOT / "data" / "splits" / "archive" / "v0.5-gold.json"
_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"
_SURVEY_ZIP = ROOT / "data" / "fdc" / "raw" / "survey.zip"
_FNDDS_ZIP = ROOT / "data" / "fdc" / "raw" / "fndds.zip"
requires_fdc_raw = pytest.mark.skipif(
    not _SURVEY_ZIP.is_file() and not _FNDDS_ZIP.is_file(),
    reason="data/fdc/raw USDA zips are not shipped in the public clone",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_mini_survey(tmp_path: Path) -> Path:
    """Tiny survey.zip: 3 foods, 1 without kcal, 1 portion row."""
    import csv
    import io
    import zipfile

    def _csv(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue().encode("utf-8")

    dest = tmp_path / "survey.zip"
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr(
            "food.csv",
            _csv(
                ["fdc_id", "description", "data_type"],
                [
                    {"fdc_id": "1", "description": "Kept A", "data_type": "survey_fndds_food"},
                    {"fdc_id": "2", "description": "Kept B", "data_type": "survey_fndds_food"},
                    {"fdc_id": "9", "description": "No kcal", "data_type": "survey_fndds_food"},
                ],
            ),
        )
        zf.writestr(
            "food_nutrient.csv",
            _csv(
                ["fdc_id", "nutrient_id", "amount"],
                [
                    {"fdc_id": "1", "nutrient_id": "1008", "amount": "10"},
                    {"fdc_id": "2", "nutrient_id": "1008", "amount": "20"},
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
                        "portion_description": "1 cup",
                        "modifier": "",
                        "gram_weight": "100",
                    }
                ],
            ),
        )
    return dest


def test_survey_ingest_count_comes_from_zip_not_sqlite(tmp_path) -> None:
    stats = builder.survey_fndds_ingest_stats(_write_mini_survey(tmp_path))
    assert stats["food_csv_rows"] == 3
    assert stats["no_kcal"] == 1
    assert stats["no_kcal_ids"] == ["9"]
    assert stats["ingestible"] == 2
    assert stats["ingestible"] != 5431


def test_fndds_only_ingest_skips_sr_legacy() -> None:
    default = builder.ingest_sources()
    only = builder.ingest_sources(fndds_only=True)
    default_types = [row[1] for row in default]
    only_types = [row[1] for row in only]
    assert "sr_legacy_food" in default_types
    assert "survey_fndds_food" in default_types
    assert "sr_legacy_food" not in only_types
    assert only_types == ["survey_fndds_food"]


def test_fndds_only_pins_the_ten_sr_staples_to_fndds_ids() -> None:
    default = builder.staple_fdc_pins()
    only = builder.staple_fdc_pins(fndds_only=True)
    assert default["chicken_breast"] == "171477"
    assert only["chicken_breast"] == "2705956"
    assert only["tofu"] == "2707435"
    assert only["tuna"] == "2706311"
    for slug, fdc_id in _FNDDS_TARGETS.items():
        assert only[slug] == fdc_id
        assert slug in _SR_STAPLES
    # Default path still pins the live SR chicken; other SR staples stay unpinned.
    assert default.get("tofu") is None


def _food(fid: str, name: str, data_type: str) -> dict:
    return {
        "food_id": fid,
        "name": name,
        "data_type": data_type,
        "aliases": [],
    }


def test_assign_staples_fndds_only_uses_pins_and_skips_sr() -> None:
    foods = {
        "2705956": _food(
            "2705956",
            "Chicken breast, baked, broiled, or roasted, skin not eaten, from raw",
            "survey_fndds_food",
        ),
        "171477": _food(
            "171477",
            "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
            "sr_legacy_food",
        ),
        "2707435": _food("2707435", "Soybean curd", "survey_fndds_food"),
        "172448": _food(
            "172448",
            "Tofu, firm, prepared with calcium sulfate and magnesium chloride (nigari)",
            "sr_legacy_food",
        ),
    }
    default = builder.assign_staples(foods)
    only = builder.assign_staples(foods, fndds_only=True)
    assert default["chicken_breast"] == "171477"
    assert only["chicken_breast"] == "2705956"
    assert only["tofu"] == "2707435"
    assert default["tofu"] == "172448"


@pytest.mark.parametrize(
    "dest",
    [None, _LIVE, _V1],
    ids=["default-catalog", "archive/catalog.sqlite", "archive/catalog-v1.sqlite"],
)
def test_fndds_only_build_refuses_frozen_catalog_paths(dest, tmp_path) -> None:
    before = {p: _sha256(p) for p in (_LIVE, _V1, _V2) if p.is_file()}
    with pytest.raises(ValueError, match="fndds-only"):
        builder.build(include_branded=False, dest=dest, fndds_only=True)
    for path, digest in before.items():
        assert _sha256(path) == digest


@requires_fdc_raw
def test_plan_lists_staple_swaps_without_writing_catalog_v2() -> None:
    before_live = _sha256(_LIVE)
    before_v1 = _sha256(_V1)
    existed = _V2.exists()
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE, split_path=_SPLIT
    )
    swaps = {row["slug"]: row for row in plan["staple_swaps"]}
    assert set(swaps) == set(_SR_STAPLES)
    assert swaps["chicken_breast"]["old_fdc_id"] == "171477"
    assert swaps["chicken_breast"]["new_fdc_id"] == "2705956"
    assert swaps["tofu"]["old_fdc_id"] == "172448"
    assert swaps["tofu"]["new_fdc_id"] == "2707435"
    assert swaps["tuna"]["new_fdc_id"] == "2706311"
    assert (
        plan["counts"]["catalog_v2_foods"]
        == plan["counts"]["food_csv_rows"] - plan["counts"]["no_kcal"]
    )
    assert plan["counts"]["food_csv_rows"] != plan["counts"]["catalog_v2_foods"]
    assert plan["wrote_catalog_v2"] is False
    assert _V2.exists() is existed
    assert _sha256(_LIVE) == before_live
    assert _sha256(_V1) == before_v1


@requires_fdc_raw
def test_plan_zero_fndds_drift_is_independent_raw_scan() -> None:
    plan = builder.plan_fndds_only_rebuild(live_catalog=_LIVE)
    raw = plan["raw_scan"]
    assert raw["builder_foods_with_portions"] > 0
    assert raw["independent_foods_with_portions"] == raw["builder_foods_with_portions"]
    assert raw["portion_map_diffs"] == 0
    assert "sqlite" not in raw["source"]


@requires_fdc_raw
def test_plan_confirms_raw_portion_facts_then_resolver_keys() -> None:
    plan = builder.plan_fndds_only_rebuild(live_catalog=_LIVE)
    facts = {row["slug"]: row for row in plan["staple_swaps"]}
    chicken = facts["chicken_breast"]["portion_fact"]
    assert chicken["raw_description"] == "1 small breast"
    assert chicken["raw_grams"] == 105.0
    assert chicken["resolver_key"] == "piece"
    assert chicken["resolved_g"] == 105.0
    assert chicken["cut_noun_resolved_g"] == 105.0
    assert facts["tuna"]["portion_fact"]["raw_description"] == "1 small can"
    assert facts["tuna"]["portion_fact"]["raw_grams"] == 75.0
    assert facts["salmon"]["portion_fact"]["raw_description"] == "1 small/regular fillet"
    assert facts["shrimp"]["portion_fact"]["raw_description"] == "1 small/medium shrimp"
    assert facts["beef"]["portion_fact"]["raw_description"] == "1 small patty"
    assert facts["olive_oil"]["portion_fact"]["raw_description"] == "1 tablespoon"
    assert facts["tofu"]["portion_fact"]["raw_description"] == '1 piece (2-1/2" x 2-3/4" x 1")'
    assert facts["black_beans"]["portion_fact"]["raw_description"] == "1 cup"
    assert facts["peanut"]["portion_fact"]["raw_grams"] == 146.0
    assert facts["almond"]["portion_fact"]["raw_grams"] == 141.0
    assert all(row["portion_fact"]["ok"] for row in plan["staple_swaps"])
    beef_delta = next(d for d in plan["nutrition_deltas"] if d["slug"] == "beef")
    salmon_delta = next(d for d in plan["nutrition_deltas"] if d["slug"] == "salmon")
    assert "90/10" in beef_delta["disclosure"]
    assert "wild" in salmon_delta["disclosure"].lower()


@requires_fdc_raw
def test_dryrun_report_lists_gram_changes_and_staple_swaps(tmp_path) -> None:
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE, split_path=_SPLIT
    )
    dest = tmp_path / "catalog-v2-dryrun.md"
    builder.write_catalog_v2_dryrun(plan, dest)
    text = dest.read_text(encoding="utf-8")
    assert "哪些食物克数会变" in text
    assert "哪些 staple 换条目" in text
    assert "2705956" in text
    assert "2707435" in text
    assert "2706311" in text
    assert "1 small breast" in text
    assert "1 small can" in text
    assert "1 small/regular fillet" in text
    assert "1 small/medium shrimp" in text
    assert "1 small patty" in text
    assert "90/10" in text
    assert "wild" in text.lower()
    assert str(plan["counts"]["catalog_v2_foods"]) in text
    assert "survey.zip" in text
    assert "catalog-v2.sqlite" in text
    assert "不写" in text


@requires_fdc_raw
def test_cli_fndds_only_dry_run_writes_report_only(tmp_path) -> None:
    dest = tmp_path / "catalog-v2-dryrun.md"
    before_live = _sha256(_LIVE)
    before_v2 = _sha256(_V2) if _V2.is_file() else None
    rc = builder.main(
        ["--fndds-only", "--dry-run", "--report", str(dest)]
    )
    assert rc == 0
    assert dest.is_file()
    assert "2705956" in dest.read_text(encoding="utf-8")
    assert _sha256(_LIVE) == before_live
    if before_v2 is not None:
        assert _sha256(_V2) == before_v2


@requires_fdc_raw
def test_catalog_v2_is_fndds_only_with_approved_staple_pins() -> None:
    if not _V2.is_file():
        pytest.fail("data/fdc/catalog-v2.sqlite is missing; rebuild with --fndds-only")
    from nutrienv.world.catalog_store import load_catalog
    from nutrienv.world.portions import resolve_portion

    catalog = load_catalog(_V2)
    types = {row.get("data_type") for row in catalog.values() if isinstance(row, dict)}
    assert "sr_legacy_food" not in types
    assert types == {"survey_fndds_food"}
    survey = ROOT / "data" / "fdc" / "raw" / "survey.zip"
    if not survey.is_file():
        survey = ROOT / "data" / "fdc" / "raw" / "fndds.zip"
    assert len({catalog.canonical_id(key) for key in catalog}) == (
        builder.survey_fndds_ingest_stats(survey)["ingestible"]
    )
    assert catalog.canonical_id("chicken_breast") == "2705956"
    assert catalog.canonical_id("tuna") == "2706311"
    assert catalog.canonical_id("tofu") == "2707435"
    assert catalog.canonical_id("salmon") == "2706286"
    assert catalog.canonical_id("shrimp") == "2706363"
    assert catalog.canonical_id("beef") == "2705855"
    assert catalog.canonical_id("olive_oil") == "2710186"
    assert catalog.canonical_id("black_beans") == "2707361"
    assert catalog.canonical_id("peanut") == "2707514"
    assert catalog.canonical_id("almond") == "2707486"
    assert resolve_portion("chicken_breast", "a piece", catalog) == 105.0
    assert resolve_portion("tuna", "a can", catalog) == 75.0
    assert resolve_portion("tofu", "a piece", catalog) == 120.0
    assert resolve_portion("salmon", "a piece", catalog) == 140.0
    assert resolve_portion("shrimp", "a piece", catalog) == 10.0
    assert resolve_portion("beef", "a piece", catalog) == 65.0
    assert resolve_portion("olive_oil", "a tablespoon", catalog) == 14.0
    assert resolve_portion("black_beans", "a cup", catalog) == 180.0
    assert resolve_portion("peanut", "a cup", catalog) == 146.0
    assert resolve_portion("almond", "a cup", catalog) == 141.0
    assert resolve_portion("chicken_breast", "a chicken breast", catalog) == 105.0
