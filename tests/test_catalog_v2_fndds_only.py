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
_LIVE = ROOT / "data" / "fdc" / "catalog.sqlite"
_V1 = ROOT / "data" / "fdc" / "catalog-v1.sqlite"
_SPLIT = ROOT / "data" / "splits" / "v0.5-gold.json"
_V2 = ROOT / "data" / "fdc" / "catalog-v2.sqlite"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


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
    ids=["default-catalog", "catalog.sqlite", "catalog-v1.sqlite"],
)
def test_fndds_only_build_refuses_frozen_catalog_paths(dest, tmp_path) -> None:
    with pytest.raises(ValueError, match="fndds-only"):
        builder.build(include_branded=False, dest=dest, fndds_only=True)
    assert not _V2.exists()


def test_plan_lists_staple_swaps_without_writing_catalog_v2() -> None:
    before_live = _sha256(_LIVE)
    before_v1 = _sha256(_V1)
    existed = _V2.exists()
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE, reference_catalog=_V1, split_path=_SPLIT
    )
    swaps = {row["slug"]: row for row in plan["staple_swaps"]}
    assert set(swaps) == set(_SR_STAPLES)
    assert swaps["chicken_breast"]["old_fdc_id"] == "171477"
    assert swaps["chicken_breast"]["new_fdc_id"] == "2705956"
    assert swaps["tofu"]["old_fdc_id"] == "172448"
    assert swaps["tofu"]["new_fdc_id"] == "2707435"
    assert swaps["tuna"]["new_fdc_id"] == "2706311"
    assert plan["counts"]["survey_fndds_food"] == plan["counts"]["catalog_v2_foods"]
    assert plan["counts"]["survey_fndds_food"] != 5432
    assert plan["wrote_catalog_v2"] is False
    assert _V2.exists() is existed
    assert _sha256(_LIVE) == before_live
    assert _sha256(_V1) == before_v1


def test_plan_confirms_portion_facts_from_fndds_table_values() -> None:
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE, reference_catalog=_V1
    )
    facts = {row["slug"]: row for row in plan["staple_swaps"]}
    assert facts["chicken_breast"]["new_portions"]["piece"] == 105.0
    assert facts["chicken_breast"]["portion_fact"]["resolved_g"] == 105.0
    assert facts["chicken_breast"]["portion_fact"]["ok"] is True
    assert facts["chicken_breast"]["portion_fact"]["cut_noun_resolved_g"] is None
    assert facts["tuna"]["new_portions"]["can"] == 75.0
    assert facts["tofu"]["new_portions"]["piece"] == 120.0
    assert facts["olive_oil"]["new_portions"]["tbsp"] == 14.0
    assert all(row["portion_fact"]["ok"] for row in plan["staple_swaps"])
    assert all(row["new_data_type"] == "survey_fndds_food" for row in plan["staple_swaps"])


def test_dryrun_report_lists_gram_changes_and_staple_swaps(tmp_path) -> None:
    plan = builder.plan_fndds_only_rebuild(
        live_catalog=_LIVE, reference_catalog=_V1, split_path=_SPLIT
    )
    dest = tmp_path / "catalog-v2-dryrun.md"
    builder.write_catalog_v2_dryrun(plan, dest)
    text = dest.read_text(encoding="utf-8")
    assert "哪些食物克数会变" in text
    assert "哪些 staple 换条目" in text
    assert "2705956" in text
    assert "2707435" in text
    assert "2706311" in text
    assert str(plan["counts"]["survey_fndds_food"]) in text
    assert "catalog-v2.sqlite" in text
    assert not _V2.exists()
    assert "不写" in text


def test_cli_fndds_only_dry_run_writes_report_only(tmp_path) -> None:
    dest = tmp_path / "catalog-v2-dryrun.md"
    before_live = _sha256(_LIVE)
    rc = builder.main(
        ["--fndds-only", "--dry-run", "--report", str(dest)]
    )
    assert rc == 0
    assert dest.is_file()
    assert "2705956" in dest.read_text(encoding="utf-8")
    assert not _V2.exists()
    assert _sha256(_LIVE) == before_live
